from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable, Protocol
from uuid import uuid4

import numpy as np
import math

from backend.core.detector import Detection
from backend.core.video_io import VideoInfo, VideoReader, VideoWriter, verify_video
from backend.core.timestamps import VideoTimestamps
from backend.core.video_io import VideoIOError


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> list[Detection]: ...
    def draw(self, frame: np.ndarray, detections: list[Detection]) -> np.ndarray: ...


@dataclass(frozen=True)
class FrameResult:
    frame_index: int
    timestamp_seconds: float
    detections: list[Detection]
    analyzed: bool


@dataclass(frozen=True)
class Progress:
    processed_frames: int
    total_frames: int
    elapsed_seconds: float


@dataclass(frozen=True)
class AnalysisSummary:
    input_info: VideoInfo
    output_path: Path
    processed_frames: int
    analyzed_frames: int
    detection_count: int
    elapsed_seconds: float
    inference_seconds: float


@dataclass(frozen=True)
class ScanSummary:
    input_info: VideoInfo
    duration_seconds: float
    processed_frames: int
    analyzed_frames: int
    detection_count: int
    elapsed_seconds: float
    inference_seconds: float
    estimated_tail: bool
    skipped_tail_frames: int = 0


class VideoAnalyzer:
    def __init__(self, detector: Detector):
        self.detector = detector

    def scan(self, input_path: Path, *, analysis_fps: float | None = 2.0,
             on_frame: Callable[[FrameResult], None] | None = None,
             on_progress: Callable[[Progress], None] | None = None,
             on_start: Callable[[VideoInfo], None] | None = None) -> ScanSummary:
        """Index-only scan: select real PTS >= next sampling boundary; no encoding.

        None selects every frame. Sampling above the source FPS is capped by the
        available frames. Missed boundaries on VFR do not cause duplicate inference.
        """
        if analysis_fps is not None and (not math.isfinite(analysis_fps) or analysis_fps <= 0):
            raise ValueError("analysis_fps 必须为有限正数")
        started = perf_counter()
        processed = analyzed = count = 0
        inference = 0.0
        next_boundary = 0.0
        with VideoReader(input_path, strict_frame_count=False) as reader, VideoTimestamps(reader.path, reader.info.fps) as timing:
            info = reader.info
            if on_start:
                on_start(info)
            timestamps = iter(timing)
            for index, frame in enumerate(reader):
                stamp = next(timestamps, None)
                if stamp is None:
                    raise VideoIOError("FFprobe 时间戳数量少于 OpenCV 解码帧数")
                if stamp.indexable and (analysis_fps is None or stamp.seconds + 1e-6 >= next_boundary):
                    before = perf_counter()
                    detections = self.detector.detect(frame)
                    inference += perf_counter() - before
                    analyzed += 1
                    count += len(detections)
                    if on_frame:
                        on_frame(FrameResult(index, stamp.seconds, detections, True))
                    if analysis_fps is not None:
                        next_boundary = (math.floor((stamp.seconds + 1e-6) * analysis_fps) + 1) / analysis_fps
                processed += 1
                if on_progress:
                    on_progress(Progress(processed, info.total_frames, perf_counter() - started))
            if next(timestamps, None) is not None:
                raise VideoIOError("FFprobe 时间戳数量多于 OpenCV 解码帧数")
            duration = timing.duration_seconds
            if duration <= timing.previous:
                raise VideoIOError("视频时长小于最后一帧时间戳")
            return ScanSummary(info, duration, processed, analyzed, count,
                               perf_counter() - started, inference, timing.estimated_tail,
                               timing.skipped_tail_frames)

    def analyze(self, input_path: Path, output_path: Path, *, frame_interval: int = 1,
                on_frame: Callable[[FrameResult], None] | None = None,
                on_progress: Callable[[Progress], None] | None = None,
                on_start: Callable[[VideoInfo], None] | None = None) -> AnalysisSummary:
        """Stream frames and optional index records; never retain the full video/results.

        When frame_interval > 1, skipped frames are still written, unannotated.
        Timestamps assume constant FPS, matching OpenCV's writer.
        """
        input_path, output_path = Path(input_path).resolve(), Path(output_path).resolve()
        if frame_interval < 1:
            raise ValueError("frame_interval 必须大于等于 1")
        if input_path == output_path:
            raise ValueError("输入和输出路径不能相同")
        if output_path.exists():
            raise FileExistsError(f"输出已存在，请选择新路径: {output_path}")
        if output_path.suffix.lower() != ".mp4":
            raise ValueError("输出文件必须为 .mp4")
        # Keep incomplete output private; publish only after full decode verification.
        temporary = output_path.with_name(f".{output_path.stem}.{uuid4().hex}.partial.mp4")
        start = perf_counter()
        processed = analyzed = detection_count = 0
        inference_seconds = 0.0
        try:
            with VideoReader(input_path) as reader:
                info = reader.info
                if on_start:
                    on_start(info)
                with VideoWriter(temporary, info) as writer:
                    for index, frame in enumerate(reader):
                        should_analyze = index % frame_interval == 0
                        detections = []
                        if should_analyze:
                            inference_start = perf_counter()
                            detections = self.detector.detect(frame)
                            inference_seconds += perf_counter() - inference_start
                            analyzed += 1
                            detection_count += len(detections)
                            frame = self.detector.draw(frame, detections)
                        writer.write(frame)
                        processed += 1
                        if on_frame:
                            on_frame(FrameResult(index, index / info.fps, detections, should_analyze))
                        if on_progress:
                            on_progress(Progress(processed, info.total_frames, perf_counter() - start))
            verify_video(temporary, info, processed)
            # rename on Windows refuses to overwrite an existing destination.
            if output_path.exists():
                raise FileExistsError(f"输出已存在: {output_path}")
            temporary.rename(output_path)
            return AnalysisSummary(info, output_path, processed, analyzed, detection_count,
                                   perf_counter() - start, inference_seconds)
        finally:
            temporary.unlink(missing_ok=True)
