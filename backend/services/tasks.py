"""One bounded in-process queue and one inference worker, with durable SQLite state."""
import json
import logging
from pathlib import Path
import queue
import threading
import time

from fastapi import HTTPException

from backend.config import DetectionConfig, IndexConfig, PROJECT_ROOT
from backend.core.detector import YOLODetector
from backend.services.indexing import IndexingService, file_hash

logger = logging.getLogger(__name__)


class AnalysisInterrupted(RuntimeError):
    pass


class DetectorCache:
    def __init__(self, loader=YOLODetector):
        self.loader = loader
        self.detector = None
        self.key = None

    def get(self, config):
        key = (str(config.weights), file_hash(config.weights) if config.weights.is_file() else None, config.device)
        if self.detector is None or key != self.key:
            self.detector = None
            self.detector = self.loader(config)
            self.key = (str(config.weights), file_hash(config.weights) if config.weights.is_file() else None, config.device)
        self.detector.config = config
        return self.detector


class TaskManager:
    def __init__(self, repository, videos, config, detector_loader=YOLODetector):
        self.repository, self.videos, self.config = repository, videos, config
        self.queue = queue.Queue(maxsize=config.queue_capacity)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.accepting = False
        self.cache = DetectorCache(detector_loader)
        self.indexing = IndexingService(repository.index, self.cache.get)
        self.worker = threading.Thread(target=self._run, name="smartvision-analysis", daemon=True)

    def start(self):
        self.repository.recover_interrupted()
        self.accepting = True
        self.worker.start()

    def submit(self, video_id, parameters):
        self.videos.registered_path(self.videos.get(video_id))
        with self.lock:
            if not self.accepting or not self.worker.is_alive():
                raise HTTPException(503, "任务工作者未就绪")
            # Conflict takes precedence over capacity when retrying a video.
            row = self.videos.get(video_id)
            if row.get("active_task_id") or row["status"] == "analyzing":
                raise HTTPException(409, "该视频已有执行中或排队中的分析任务")
            if self.queue.full():
                raise HTTPException(429, "分析队列已满，请稍后重试", headers={"Retry-After": "5"})
            task = self.repository.create_task(video_id, parameters)
            self.queue.put_nowait(task["task_id"])
            return task

    def _run(self):
        while not self.stop_event.is_set():
            try:
                task_id = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if self.stop_event.is_set():
                    self.repository.failed(task_id, "服务关闭，任务未执行")
                else:
                    self._execute(task_id)
            except Exception:
                logger.exception("分析工作者异常，任务 %s", task_id)
                try:
                    self.repository.failed(task_id, "任务工作者异常，请检查服务器日志")
                except Exception:
                    logger.exception("无法持久化任务错误 %s", task_id)
            finally:
                self.queue.task_done()

    def _execute(self, task_id):
        if not self.repository.start(task_id):
            return
        task = self.repository.task(task_id)
        try:
            row = self.videos.get(task["video_id"])
            path = self.videos.registered_path(row)
            if file_hash(path) != row["content_sha256"]:
                raise RuntimeError("已上传文件内容发生改变，请重新上传")
            parameters = json.loads(task["parameters_json"])
            config = DetectionConfig(weights=self.config.weights, image_size=parameters["imgsz"],
                                     confidence=parameters["confidence"])
            last_update = 0.0

            def progress(value):
                nonlocal last_update
                if self.stop_event.is_set():
                    raise AnalysisInterrupted("服务关闭，分析已中断；索引已回滚")
                now = time.monotonic()
                if now - last_update >= 0.25 or value.processed_frames == value.total_frames:
                    self.repository.progress(task_id, value.processed_frames, value.total_frames)
                    last_update = now

            summary = self.indexing.analyze(
                path, detection=config, indexing=IndexConfig(analysis_fps=parameters["sample_fps"]),
                force=parameters["force_rebuild"], on_progress=progress,
                on_device=lambda device: logger.info("任务 %s 推理设备: %s", task_id, device),
                on_start=lambda info: self.repository.progress(task_id, 0, info.total_frames))
            video = self.repository.index.get_video(summary.video_id)
            self.repository.succeeded(task_id, video["total_frames"], summary.reused)
        except BaseException as exc:
            logger.exception("分析任务失败 %s", task_id)
            error = f"{type(exc).__name__}: {exc}"
            for root in (self.videos.root, self.config.weights.parent, self.config.database.parent, PROJECT_ROOT):
                error = error.replace(str(root), "<storage>")
            self.repository.failed(task_id, error)

    def stop(self):
        with self.lock:
            self.accepting = False
            self.stop_event.set()
            while True:
                try:
                    task_id = self.queue.get_nowait()
                except queue.Empty:
                    break
                self.repository.failed(task_id, "服务关闭，排队任务未执行；请重新提交")
                self.queue.task_done()
        self.worker.join(timeout=30)
        if not self.worker.is_alive():
            self.cache.detector = None
        return not self.worker.is_alive()
