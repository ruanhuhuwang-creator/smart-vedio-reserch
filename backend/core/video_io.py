# 视频读写工具：像翻书一样一次读一帧，不把整段视频装进内存。
# with VideoReader(...) 进入时打开文件，离开时释放资源，报错也会释放。

"""Streaming OpenCV I/O. Only one frame is kept at a time."""
from dataclasses import dataclass
from pathlib import Path
import math

import cv2
import numpy as np


class VideoIOError(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    fps: float
    width: int
    height: int
    total_frames: int

    @property
    def duration_seconds(self) -> float:
        return self.total_frames / self.fps


class VideoReader:
    def __init__(self, path: Path, *, strict_frame_count: bool = True):
        self.path = Path(path).resolve()
        self.strict_frame_count = strict_frame_count
        self.capture = None
        self.frames_read = 0

    def __enter__(self):
        if not self.path.is_file():
            raise VideoIOError(f"输入视频不存在: {self.path}")
        self.frames_read = 0
        self.capture = cv2.VideoCapture(str(self.path))
        try:
            if not self.capture.isOpened():
                raise VideoIOError(f"无法打开视频，文件可能损坏或编码不受支持: {self.path}")
            fps = self.capture.get(cv2.CAP_PROP_FPS)
            width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            count = self.capture.get(cv2.CAP_PROP_FRAME_COUNT)
            if not math.isfinite(fps) or fps <= 0 or width <= 0 or height <= 0:
                raise VideoIOError("视频元数据无效（FPS 或分辨率）")
            self.info = VideoInfo(self.path, fps, width, height,
                                  int(count) if math.isfinite(count) and count > 0 else 0)
            return self
        except BaseException:
            self.capture.release()
            raise

    def __iter__(self):
        if self.capture is None or not self.capture.isOpened():
            raise VideoIOError("视频读取器未打开")
        while True:
            success, frame = self.capture.read()
            if not success:
                if self.frames_read == 0:
                    raise VideoIOError("视频无法解码任何帧")
                if self.strict_frame_count and self.info.total_frames and self.frames_read < self.info.total_frames:
                    raise VideoIOError(f"视频提前结束或帧损坏: 已读 {self.frames_read}/{self.info.total_frames}")
                break
            self.frames_read += 1
            yield frame

    def __exit__(self, *args):
        if self.capture is not None:
            self.capture.release()


class VideoWriter:
    def __init__(self, path: Path, info: VideoInfo):
        self.path, self.info = Path(path).resolve(), info
        self.writer = None
        self.frames_written = 0

    def __enter__(self):
        if self.path.suffix.lower() != ".mp4":
            raise VideoIOError("输出文件扩展名必须为 .mp4")
        if self.info.width % 2 or self.info.height % 2:
            raise VideoIOError("mp4v 编码要求偶数宽高；为避免静默裁剪，拒绝奇数分辨率")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.writer = cv2.VideoWriter(str(self.path), cv2.VideoWriter_fourcc(*"mp4v"),
                                      self.info.fps, (self.info.width, self.info.height))
        if not self.writer.isOpened():
            self.writer.release()
            raise VideoIOError("MP4 编码器初始化失败，请检查 OpenCV 编码支持和输出目录权限")
        return self

    def write(self, frame: np.ndarray):
        if self.writer is None or not self.writer.isOpened():
            raise VideoIOError("视频写入器未打开")
        if frame.dtype != np.uint8 or frame.shape != (self.info.height, self.info.width, 3):
            raise VideoIOError("输出帧必须为原始尺寸的 uint8 BGR 图像")
        self.writer.write(frame)
        self.frames_written += 1

    def __exit__(self, *args):
        if self.writer is not None:
            self.writer.release()


def verify_video(path: Path, expected: VideoInfo, frame_count: int) -> None:
    """Decode output to catch failures that VideoWriter.write cannot report."""
    with VideoReader(path) as reader:
        info = reader.info
        if (info.width, info.height) != (expected.width, expected.height) or abs(info.fps - expected.fps) > 0.01:
            raise VideoIOError("编码后分辨率或 FPS 与输入不一致")
        actual = sum(1 for _ in reader)
        if actual != frame_count:
            raise VideoIOError(f"编码后帧数错误: {actual}，预期 {frame_count}")
