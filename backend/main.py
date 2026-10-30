# 后端总入口。create_app 像组装机器：接好数据库、视频服务和任务队列，再挂上 API。
# 启动/关闭时执行 lifespan；真正的 YOLO 推理交给后台工作线程，不在健康检查里加载模型。

import asyncio
from contextlib import asynccontextmanager
import logging
import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes import router
from backend.api.upload_limit import UploadLimitMiddleware
from backend.config import APIConfig
from backend.core.detector import YOLODetector
from backend.database.api_repository import APIRepository
from backend.database.repository import IndexBusyError, IndexRepository
from backend.services.process_lock import ProcessLock
from backend.services.tasks import TaskManager
from backend.services.videos import VideoService

logger = logging.getLogger(__name__)


def create_app(config: APIConfig | None = None, *, detector_loader=YOLODetector, frontend_dir: Path | None = None):
    config = config or APIConfig.from_env()

    @asynccontextmanager
    async def lifespan(application):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        process_lock = ProcessLock(config.database)
        process_lock.acquire()
        application.state.process_lock = process_lock
        manager = None
        try:
            index = IndexRepository(config.database)
            repository = APIRepository(index)
            logger.info("SQLite 初始化成功: %s", config.database)
            videos = VideoService(repository, config)
            manager = TaskManager(repository, videos, config, detector_loader)
            # application.state 相当于本次服务共享的工具箱，路由通过 request.app.state 取用。
            application.state.index = index
            application.state.repository = repository
            application.state.videos = videos
            application.state.tasks = manager
            manager.start()
            # yield 前是服务启动准备；yield 后的 finally 是关闭时收尾。
            yield
        finally:
            stopped = True
            if manager is not None and manager.worker.ident is not None:
                stopped = await asyncio.to_thread(manager.stop)
            if stopped:
                process_lock.release()
            else:
                logger.error("工作线程尚未退出，进程锁继续保留；请等待或结束本服务进程")

    application = FastAPI(title="SmartVision", version="0.3.0", lifespan=lifespan,
                          docs_url=None if frontend_dir is not None else "/docs")
    if frontend_dir is not None:
        from fastapi.openapi.docs import get_swagger_ui_html

        @application.get("/docs", include_in_schema=False)
        def local_docs():
            return get_swagger_ui_html(openapi_url="/openapi.json", title="SmartVision API",
                                      swagger_js_url="/assets/swagger-ui-bundle.js",
                                      swagger_css_url="/assets/swagger-ui.css",
                                      swagger_favicon_url="/assets/swagger-favicon.png")
    application.add_middleware(UploadLimitMiddleware, max_bytes=config.max_upload_bytes)
    application.add_middleware(CORSMiddleware, allow_origins=list(config.cors_origins),
                               allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "Range"],
                               expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"])
    application.include_router(router)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Avoid echoing untrusted payloads or serializing NaN/Infinity error inputs.
        return JSONResponse({"detail": [{key: error[key] for key in ("loc", "msg", "type")}
                                         for error in exc.errors()]}, status_code=422)

    @application.exception_handler(IndexBusyError)
    async def index_conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @application.exception_handler(sqlite3.OperationalError)
    async def database_unavailable(request, exc):
        logger.exception("数据库暂时不可用")
        return JSONResponse({"detail": "数据库暂时不可用，请稍后重试并检查服务日志"}, status_code=503)

    @application.get("/health", tags=["health"])
    def health():
        manager = getattr(application.state, "tasks", None)
        return {"status": "ok" if manager is None or manager.worker.is_alive() else "degraded",
                "service": "SmartVision", "version": "0.3.0"}

    if frontend_dir is not None:
        from backend.api.static import serve_frontend
        serve_frontend(application, frontend_dir)

    return application


app = create_app()
