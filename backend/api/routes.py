# HTTP 接口目录：浏览器访问 URL 后，FastAPI 把请求交给下方对应函数。
# 这里只接收参数、调用服务、整理响应；上传/排队/推理/查询各自由专门模块完成。

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from starlette.responses import FileResponse

from backend.schemas.api import AnalysisRequest, EventList, TaskResponse, VideoList, VideoResponse
from backend.services.search import SearchService
from backend.services.videos import public_video

router = APIRouter(prefix="/api")


@router.post("/videos", response_model=VideoResponse, status_code=201, tags=["videos"])
async def upload_video(request: Request, file: UploadFile = File(...)):
    return await request.app.state.videos.upload(file)


@router.get("/videos", response_model=VideoList, tags=["videos"])
def list_videos(request: Request, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    total, rows = request.app.state.repository.videos(offset, limit)
    return {"total": total, "offset": offset, "limit": limit, "items": [public_video(row) for row in rows]}


@router.get("/videos/{video_id}", response_model=VideoResponse, tags=["videos"])
def video_detail(video_id: int, request: Request):
    return public_video(request.app.state.videos.get(video_id))


@router.post("/videos/{video_id}/analysis", status_code=202, response_model=TaskResponse, tags=["analysis"])
def create_analysis(video_id: int, body: AnalysisRequest, request: Request):
    # 202 表示已接单，不表示分析成功；前端还要 GET /api/tasks/{task_id} 查看最终状态。
    return request.app.state.tasks.submit(video_id, body.model_dump())


@router.get("/tasks/{task_id}", response_model=TaskResponse, tags=["analysis"])
def task_detail(task_id: str, request: Request):
    task = request.app.state.repository.task(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


@router.post("/tasks/{task_id}/cancel", response_model=TaskResponse, status_code=202, tags=["analysis"])
def cancel_analysis(task_id: str, request: Request):
    return request.app.state.tasks.cancel(task_id)


@router.get("/videos/{video_id}/events", response_model=EventList, tags=["events"])
def video_events(video_id: int, request: Request, category: str | None = Query(None, min_length=1, max_length=80),
                 start_time: float | None = Query(None, ge=0, allow_inf_nan=False),
                 end_time: float | None = Query(None, ge=0, allow_inf_nan=False)):
    row = request.app.state.videos.get(video_id)
    video = public_video(row)
    # 尚无索引不能返回空数组冒充“没有人”；用 409 明确告诉前端现在还不能查。
    if not video["index_available"]:
        raise HTTPException(409, {"code": "index_not_ready", "analysis_status": video["analysis_status"],
                                  "active_task_id": video["active_task_id"], "message": "尚无有效索引，请先完成分析"})
    try:
        events = SearchService(request.app.state.index).search(category, video_id, start_time, end_time, include_counts=True)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"video_id": video_id, "analysis_status": video["analysis_status"], "index_available": True,
            "using_previous_index": video["analysis_status"] in {"queued", "running", "failed", "cancelled"},
            "events": [{"event_id": item["event_id"], "video_id": video_id, "category": item["class_name"],
                        "start_time": item["start_time"], "end_time": item["end_time"], "duration": item["duration"],
                        "max_count": item["max_count"]}
                       for item in events]}


@router.get("/videos/{video_id}/stream", tags=["videos"], response_class=FileResponse,
            responses={200: {"content": {"video/mp4": {}}},
                       206: {"description": "Partial Content", "content": {"video/mp4": {}}}})
def stream_video(video_id: int, request: Request):
    service = request.app.state.videos
    row = service.get(video_id)
    path = service.registered_path(row)
    if not row["browser_compatible"]:
        raise HTTPException(415, {"code": "unsupported_browser_codec", "codec": row["video_codec"],
                                  "message": row["compatibility_message"]})
    # FileResponse 处理浏览器的 Range（按字节分段读取），拖动播放不必下载整段视频。
    return FileResponse(path, media_type="video/mp4", filename=row["name"], content_disposition_type="inline",
                        headers={"X-Content-Type-Options": "nosniff"})
