"""Stream presentation timestamps from FFprobe, without keeping a video in memory."""
from dataclasses import dataclass
import json
import math
import logging
from pathlib import Path
import shutil
import subprocess
import tempfile

from backend.core.video_io import VideoIOError
from backend.core.subprocess_utils import hidden_process_options

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrameTimestamp:
    seconds: float
    duration: float
    indexable: bool = True


class VideoTimestamps:
    def __init__(self, path: Path, fps: float):
        self.path, self.fps = Path(path), fps
        self.process = None
        self.errors = None
        self.origin = None
        self.previous = -1.0
        self.last_end = 0.0
        self.duration_seconds = 0.0
        self.estimated_tail = False
        self.skipped_tail_frames = 0

    def _can_skip_tail(self, relative: float) -> bool:
        """Only tolerate a tiny terminal suffix; never invent replacement PTS."""
        window = min(0.5, self.duration_seconds * 0.1)
        return (self.duration_seconds > 0 and self.skipped_tail_frames < 3
                and relative >= self.duration_seconds - window
                and self.previous <= self.duration_seconds + 1 / self.fps
                and 0 <= self.previous - relative <= 0.2 + 1e-6)

    def __enter__(self):
        executable = shutil.which("ffprobe")
        if not executable:
            raise VideoIOError("索引分析需要 FFprobe，请安装 FFmpeg 并将 bin 目录加入 PATH")
        metadata = subprocess.run(
            [executable, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=duration", "-of", "json", str(self.path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            **hidden_process_options())
        if metadata.returncode:
            raise VideoIOError(f"FFprobe 无法读取视频: {metadata.stderr[:1000]}")
        streams = json.loads(metadata.stdout).get("streams", [])
        try:
            duration = float(streams[0].get("duration", 0)) if streams else 0
            if math.isfinite(duration) and duration > 0:
                self.duration_seconds = duration
        except (ValueError, TypeError):
            pass
        self.errors = tempfile.TemporaryFile()
        try:
            self.process = subprocess.Popen(
                [executable, "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "frame=best_effort_timestamp_time,duration_time,pkt_duration_time", "-of",
                 "compact=p=0:nk=0", str(self.path)],
                stdout=subprocess.PIPE, stderr=self.errors, text=True,
                encoding="utf-8", errors="replace", **hidden_process_options())
            return self
        except BaseException:
            self.errors.close()
            raise

    def __iter__(self):
        if self.process is None:
            raise VideoIOError("时间戳读取器未打开")
        for line in self.process.stdout:
            fields = dict(part.split("=", 1) for part in line.strip().split("|") if "=" in part)
            if not fields:
                continue
            if "best_effort_timestamp_time" not in fields:
                if "side_data_type" in fields:
                    continue
                raise VideoIOError("视频帧缺少原始时间戳，拒绝建立不准确索引")
            try:
                pts = float(fields["best_effort_timestamp_time"])
                if not math.isfinite(pts):
                    raise ValueError("非有限 PTS")
                if self.origin is None:
                    self.origin = pts
                relative = pts - self.origin
                indexable = relative > self.previous
                if not indexable and not self._can_skip_tail(relative):
                    raise ValueError(f"PTS 不严格递增（前值 {self.previous:.6f} 秒，"
                                     f"当前 {relative:.6f} 秒，超出片尾容错范围）")
                if indexable and self.skipped_tail_frames:
                    raise ValueError("异常 PTS 后仍有新的递增帧，不属于可忽略的连续尾帧")
                raw_duration = fields.get("duration_time", fields.get("pkt_duration_time", "0"))
                duration = float(raw_duration) if raw_duration != "N/A" else 0.0
                if not math.isfinite(duration) or duration <= 0:
                    duration = 1 / self.fps
                    self.estimated_tail = True
            except (ValueError, TypeError) as exc:
                raise VideoIOError(f"视频时间戳无效: {exc}") from exc
            if indexable:
                self.previous = relative
                self.last_end = relative + duration
            else:
                self.skipped_tail_frames += 1
                self.estimated_tail = True
                logger.warning("跳过异常尾帧索引 #%d: PTS=%.6f 秒，前值=%.6f 秒；"
                               "保留原视频及帧对应关系，不补造时间戳",
                               self.skipped_tail_frames, relative, self.previous)
            # Yield once per decoded frame, including rejected tail frames, so
            # OpenCV and FFprobe remain aligned. The analyzer skips inference.
            yield FrameTimestamp(relative, duration, indexable)
        return_code = self.process.wait(timeout=30)
        self.errors.seek(0)
        error = self.errors.read(2000).decode("utf-8", errors="replace").strip()
        if return_code or error:
            raise VideoIOError(f"FFprobe 解码失败: {error or return_code}")
        if self.duration_seconds > 0 and self.last_end > self.duration_seconds + 0.01:
            logger.warning("容器声明时长短于实际解码帧结束时间，索引采用解码 PTS 范围")
        # Some VFR containers report frame_count/nominal_fps instead of the
        # actual presentation span. Never discard valid decoded tail frames.
        self.duration_seconds = max(self.duration_seconds, self.last_end)

    def __exit__(self, *args):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=10)
            self.process.stdout.close()
        if self.errors is not None:
            self.errors.close()
