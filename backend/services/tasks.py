# 后台任务管理器：可以理解为一张待办单队列，只有一个工作线程依次取单执行。
# HTTP 提交后马上给 task_id；任务状态写进 SQLite，前端拿 task_id 定期查询。

"""One bounded in-process queue and one inference worker, with durable SQLite state."""
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
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


class UserCancelled(AnalysisInterrupted):
    pass


@dataclass
class TaskControl:
    # 每张任务单有自己的停止信号，停止 A 不会误停正在处理的 B。
    cancel: threading.Event = field(default_factory=threading.Event)
    published: bool = False


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
        # 置信度/尺寸改变可更新配置；权重/设备改变才重建检测器，避免每帧加载大模型。
        self.detector.config = config
        return self.detector


class TaskManager:
    def __init__(self, repository, videos, config, detector_loader=YOLODetector):
        self.repository, self.videos, self.config = repository, videos, config
        self.queue = queue.Queue(maxsize=config.queue_capacity)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.accepting = False
        self.controls: dict[str, TaskControl] = {}
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
            self.controls[task["task_id"]] = TaskControl()
            self.queue.put_nowait(task["task_id"])
            return task

    def cancel(self, task_id):
        with self.lock:
            task = self.repository.task(task_id)
            if task is None:
                raise HTTPException(404, "任务不存在")
            if task["status"] == "cancelled":
                return task
            if task["status"] not in {"queued", "running"}:
                raise HTTPException(409, "任务已结束或正在提交结果，无法停止；请刷新任务状态")
            control = self.controls.setdefault(task_id, TaskControl())
            if control.published:
                raise HTTPException(409, "结果已提交，无法停止；请刷新任务状态")
            self.repository.request_cancel(task_id)
            # set 只表示“请停止”；推理不能被随意强杀，工作线程到检查点才真正退出本任务。
            control.cancel.set()
            if task["status"] == "queued":
                self.repository.cancelled(task_id)
                # Remove only this queued item and release its capacity. A worker
                # that already fetched it will see the terminal DB state at start.
                with self.queue.mutex:
                    try:
                        self.queue.queue.remove(task_id)
                    except ValueError:
                        pass
                    else:
                        self.queue.unfinished_tasks -= 1
                        self.queue.not_full.notify()
                        if not self.queue.unfinished_tasks:
                            self.queue.all_tasks_done.notify_all()
                self.controls.pop(task_id, None)
            logger.info("用户请求停止任务 %s (%s)", task_id, task["status"])
            return self.repository.task(task_id)

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
                with self.lock:
                    self.controls.pop(task_id, None)
                self.queue.task_done()

    def _execute(self, task_id):
        with self.lock:
            if not self.repository.start(task_id):
                return
            control = self.controls.setdefault(task_id, TaskControl())
        task = self.repository.task(task_id)

        def check_cancel():
            if control.cancel.is_set():
                raise UserCancelled("用户停止分析；本次索引已回滚")
            if self.stop_event.is_set():
                raise AnalysisInterrupted("服务关闭，分析已中断；索引已回滚")

        @contextmanager
        def publish_guard():
            # Serialize the final atomic publication with cancellation acceptance.
            # Once publication wins, a late stop returns 409, never 'cancelled'
            # while silently replacing the previous valid index.
            # 与 cancel 共用这把锁：要么先接受取消，要么先完成提交，避免状态与索引不一致。
            with self.lock:
                check_cancel()
                yield
                control.published = True

        try:
            check_cancel()
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
                check_cancel()
                now = time.monotonic()
                # 限制写进度的频率，避免每帧都写数据库；取消检查仍然每次回调都执行。
                if now - last_update >= 0.25 or value.processed_frames == value.total_frames:
                    self.repository.progress(task_id, value.processed_frames, value.total_frames)
                    last_update = now

            summary = self.indexing.analyze(
                path, detection=config, indexing=IndexConfig(analysis_fps=parameters["sample_fps"]),
                force=parameters["force_rebuild"], on_progress=progress,
                check_cancel=check_cancel, publish_guard=publish_guard,
                on_device=lambda device: logger.info("任务 %s 推理设备: %s", task_id, device),
                on_start=lambda info: self.repository.progress(task_id, 0, info.total_frames))
            with self.lock:
                if not control.published:
                    check_cancel()
                video = self.repository.index.get_video(summary.video_id)
                self.repository.succeeded(task_id, video["total_frames"], summary.reused)
        except UserCancelled:
            self.repository.cancelled(task_id)
            logger.info("任务 %s 已停止，本次未完成索引已丢弃", task_id)
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
