# API 数据协议：Pydantic 负责检查请求参数，并声明响应字段、生成 OpenAPI 文档。
# 例如 imgsz 只允许三个值；额外字段会被拒绝，前端不能任意传 YOLO 参数。
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from backend.config import DetectionConfig, IndexConfig


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sample_fps: float = Field(default=IndexConfig().analysis_fps, ge=0.25, le=30)
    imgsz: Literal[416, 640, 960] = DetectionConfig().image_size
    confidence: float = Field(default=DetectionConfig().confidence, ge=0.05, le=1)
    force_rebuild: bool = Field(default=False, strict=True)


class VideoResponse(BaseModel):
    video_id: int
    filename: str
    duration: float
    fps: float
    width: int
    height: int
    resolution: str
    analysis_status: str
    created_at: str
    index_available: bool
    active_task_id: str | None
    video_codec: str
    browser_compatible: bool
    compatibility_message: str | None
    stream_url: str


class VideoList(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[VideoResponse]


class TaskResponse(BaseModel):
    task_id: str
    video_id: int
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    cancel_requested: bool = False
    progress: float | None
    progress_is_estimate: bool
    processed_frames: int
    total_frames: int | None
    index_reused: bool
    created_at: str
    started_at: str | None
    finished_at: str | None
    error_message: str | None


class EventResponse(BaseModel):
    event_id: int
    video_id: int
    category: str
    start_time: float
    end_time: float
    duration: float
    max_count: int = Field(ge=0, description="事件内各采样帧检测框数量的最大值，不是去重累计数量")


class EventList(BaseModel):
    video_id: int
    analysis_status: str
    index_available: bool
    using_previous_index: bool
    events: list[EventResponse]
