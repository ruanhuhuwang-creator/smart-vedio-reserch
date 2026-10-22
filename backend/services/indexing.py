from dataclasses import dataclass
from contextlib import nullcontext
from hashlib import sha256
from importlib.metadata import version, PackageNotFoundError
import json
from pathlib import Path
from time import perf_counter

from backend.config import DetectionConfig, IndexConfig
from backend.core.analyzer import VideoAnalyzer
from backend.core.detector import YOLODetector
from backend.core.video_io import VideoReader
from backend.database.repository import IndexRepository
from backend.services.events import merge_observations


def file_hash(path: Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class IndexSummary:
    video_id: int
    reused: bool
    sampled_frames: int
    detection_count: int
    elapsed_seconds: float


class IndexingService:
    def __init__(self, repository: IndexRepository, detector_factory=YOLODetector):
        self.repository = repository
        self.detector_factory = detector_factory

    def analyze(self, input_path: Path, *, detection: DetectionConfig = DetectionConfig(),
                indexing: IndexConfig = IndexConfig(), force: bool = False,
                on_start=None, on_progress=None, on_device=None, check_cancel=None, publish_guard=None) -> IndexSummary:
        started = perf_counter()
        if check_cancel:
            check_cancel()
        path = Path(input_path).resolve()
        with VideoReader(path) as reader:
            info = reader.info
        if on_start:
            on_start(info)
        stat = path.stat()
        content_hash = file_hash(path)
        if check_cancel:
            check_cancel()
        detector = None
        # Download missing weights before computing the stable cache key.
        if not detection.weights.is_file():
            detector = self.detector_factory(detection)
        try:
            package_version = version("ultralytics")
        except PackageNotFoundError:
            package_version = "unknown"
        settings = {"analysis_fps": indexing.analysis_fps, "confidence": detection.confidence,
                    "image_size": detection.image_size, "model_version": package_version,
                    "weights": file_hash(detection.weights) if detection.weights.is_file() else str(detection.weights)}
        key = sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
        video_id, reused = self.repository.claim(content_hash, info, key, force=force)
        if reused:
            video = self.repository.get_video(video_id)
            if video["merge_gap"] != indexing.merge_gap or video["min_samples"] != indexing.min_samples:
                with (publish_guard() if publish_guard else nullcontext()):
                    if check_cancel:
                        check_cancel()
                    self.rebuild_events(video_id, indexing.merge_gap, indexing.min_samples)
            return IndexSummary(video_id, True, video["sampled_frames"],
                                self.repository.counts(video_id)["detections"], perf_counter() - started)
        try:
            detector = detector or self.detector_factory(detection)
            if on_device:
                on_device(getattr(detector, "device", "mock"))
            if check_cancel:
                check_cancel()
            with self.repository.replace_index(video_id, publish_guard=publish_guard) as writer:
                summary = VideoAnalyzer(detector).scan(path, analysis_fps=indexing.analysis_fps,
                                                      on_frame=writer.add_frame, on_progress=on_progress)
                now = path.stat()
                if (now.st_size, now.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
                    raise RuntimeError("分析期间源视频发生改变，索引已回滚，请等待录制/复制完成后重试")
                writer.merge_events(summary.duration_seconds, indexing.merge_gap,
                                    indexing.min_samples, merge_observations)
                writer.complete(summary, key, detection, indexing)
                if check_cancel:
                    check_cancel()
            return IndexSummary(video_id, False, summary.analyzed_frames,
                                summary.detection_count, perf_counter() - started)
        except BaseException as exc:
            self.repository.fail(video_id, str(exc) or type(exc).__name__)
            raise

    def rebuild_events(self, video_id: int, merge_gap: float = 1.0, min_samples: int = 2):
        IndexConfig(merge_gap=merge_gap, min_samples=min_samples)
        self.repository.rebuild_events(video_id, merge_gap, min_samples, merge_observations)
