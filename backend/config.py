# 配置总表：模型参数、抽帧参数、上传限制和存储位置都从这里取。
# 开发时数据放项目 data；EXE 模式放用户 LOCALAPPDATA，避免写进只读依赖目录。

from dataclasses import dataclass
from pathlib import Path
import math
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))
PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
DATA_ROOT = (Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "SmartVision"
             if FROZEN else PROJECT_ROOT / "data")
DEFAULT_DATABASE = DATA_ROOT / "smartvision.sqlite3"


@dataclass(frozen=True)
class APIConfig:
    database: Path = DEFAULT_DATABASE
    video_dir: Path = DATA_ROOT / "videos"
    weights: Path = PROJECT_ROOT / "models" / "yolo26n.pt"
    max_upload_bytes: int = 512 * 1024 * 1024
    queue_capacity: int = 4
    max_video_pixels: int = 3840 * 2160
    max_duration_seconds: float = 21600
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    def __post_init__(self):
        if self.max_upload_bytes <= 0 or not 1 <= self.queue_capacity <= 32:
            raise ValueError("上传限制必须为正数，队列容量必须在 1～32 之间")
        if self.max_video_pixels <= 0 or not math.isfinite(self.max_duration_seconds) or self.max_duration_seconds <= 0:
            raise ValueError("视频尺寸与时长限制必须为正数")
        if "*" in self.cors_origins:
            raise ValueError("CORS 不允许通配来源")

    @classmethod
    def from_env(cls):
        return cls(
            database=Path(os.getenv("SMARTVISION_DATABASE", str(DEFAULT_DATABASE))),
            video_dir=Path(os.getenv("SMARTVISION_VIDEO_DIR", str(DATA_ROOT / "videos"))),
            max_upload_bytes=int(os.getenv("SMARTVISION_MAX_UPLOAD_BYTES", 512 * 1024 * 1024)),
            queue_capacity=int(os.getenv("SMARTVISION_QUEUE_CAPACITY", 4)),
            cors_origins=tuple(x.strip() for x in os.getenv("SMARTVISION_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()))


@dataclass(frozen=True)
class IndexConfig:
    # None means detect every decoded frame.
    analysis_fps: float | None = 2.0
    merge_gap: float = 1.0
    min_samples: int = 2

    def __post_init__(self):
        if self.analysis_fps is not None and (not math.isfinite(self.analysis_fps) or self.analysis_fps <= 0):
            raise ValueError("analysis_fps 必须为正数；逐帧模式使用 None")
        if not math.isfinite(self.merge_gap) or self.merge_gap < 0:
            raise ValueError("merge_gap 必须为有限非负数")
        if not isinstance(self.min_samples, int) or self.min_samples < 2:
            raise ValueError("min_samples 至少为 2，避免孤立检测直接形成可靠事件")


@dataclass(frozen=True)
class DetectionConfig:
    weights: Path = PROJECT_ROOT / "models" / "yolo26n.pt"
    confidence: float = 0.35
    image_size: int = 640
    device: str = "auto"

    def __post_init__(self):
        if not 0 < self.confidence <= 1:
            raise ValueError("confidence 必须在 (0, 1] 范围内")
        if self.image_size <= 0:
            raise ValueError("image_size 必须大于 0")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device 必须是 auto、cpu 或 cuda")
