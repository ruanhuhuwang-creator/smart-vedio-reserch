"""Managed uploads: clients supply bytes and display names, never server paths."""
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from backend.core.video_io import VideoReader
from backend.core.subprocess_utils import hidden_process_options
from backend.database.api_repository import APIRepository


def public_video(row):
    task_status = row.get("latest_task_status")
    if row.get("active_task_id"):
        status = task_status
    elif row["status"] == "analyzing":
        status = "running"
    elif task_status == "failed":
        status = "failed"
    elif row["analysis_key"]:
        status = "completed"
    elif row["last_error"]:
        status = "failed"
    else:
        status = "not_analyzed"
    return {"video_id": row["id"], "filename": row["name"], "duration": row["duration"],
            "fps": row["fps"], "width": row["width"], "height": row["height"],
            "resolution": f"{row['width']}x{row['height']}", "analysis_status": status,
            "created_at": row["created_at"], "index_available": bool(row["analysis_key"]),
            "active_task_id": row.get("active_task_id"), "video_codec": row["video_codec"],
            "browser_compatible": bool(row["browser_compatible"]),
            "compatibility_message": row["compatibility_message"], "stream_url": f"/api/videos/{row['id']}/stream"}


class VideoService:
    def __init__(self, repository: APIRepository, config):
        self.repository, self.config = repository, config
        self.root = config.video_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, video_id):
        row = self.repository.video(video_id)
        if not row:
            raise HTTPException(404, "视频不存在")
        return row

    def registered_path(self, row):
        path = Path(row["path"]).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise HTTPException(404, "已登记的视频文件不可用")
        return path

    def probe(self, path):
        executable = shutil.which("ffprobe")
        if not executable:
            raise HTTPException(503, "服务器缺少 FFprobe，请检查 FFmpeg 安装")
        try:
            result = subprocess.run([executable, "-v", "error", "-show_entries",
                                     "stream=codec_type,codec_name,pix_fmt,width,height,duration:format=duration",
                                     "-of", "json", str(path)], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=30,
                                    **hidden_process_options())
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(422, "视频探测超时，文件无法验证") from exc
        if result.returncode:
            raise HTTPException(422, "文件不能作为有效视频解码")
        metadata = json.loads(result.stdout)
        streams = metadata.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        if not video:
            raise HTTPException(422, "文件没有视频画面")
        if video.get("width", 0) * video.get("height", 0) > self.config.max_video_pixels:
            raise HTTPException(422, "视频分辨率超过服务器限制（默认最多 4K 像素数）")
        duration = 0.0
        for value in (video.get("duration"), metadata.get("format", {}).get("duration")):
            try:
                duration = float(value)
                if math.isfinite(duration) and duration > 0:
                    break
            except (TypeError, ValueError):
                continue
        if not math.isfinite(duration) or duration <= 0 or duration > self.config.max_duration_seconds:
            raise HTTPException(422, "视频时长未知或超过服务器限制")
        try:
            with VideoReader(path, strict_frame_count=False) as reader:
                next(iter(reader))
                info = reader.info
        except Exception as exc:
            raise HTTPException(422, "OpenCV 无法读取有效的视频画面") from exc
        audio_ok = all(s.get("codec_name") in {"aac", "mp3"} for s in streams if s.get("codec_type") == "audio")
        compatible = (path.suffix.lower() == ".mp4" and video.get("codec_name") == "h264"
                      and video.get("pix_fmt") in {"yuv420p", "yuvj420p"} and audio_ok)
        message = None if compatible else "原视频编码/容器未保证浏览器兼容；播放需要 MP4/H.264 8-bit yuv420p，音轨为 AAC/MP3（或无音轨）；本服务不自动转码"
        return info, duration, video.get("codec_name", "unknown"), compatible, message

    async def upload(self, upload: UploadFile):
        filename = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not filename or len(filename) > 255 or any(ord(c) < 32 for c in filename):
            raise HTTPException(400, "文件名无效")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".mp4", ".mov", ".avi"}:
            raise HTTPException(415, "只支持 MP4、MOV、AVI 视频")
        internal = uuid4().hex
        partial = self.root / f".upload-{internal}.partial"
        final = self.root / f"{internal}{suffix}"
        retained = False
        try:
            size = 0
            digest = sha256()
            with partial.open("xb") as target:
                while block := await upload.read(1024 * 1024):
                    size += len(block)
                    if size > self.config.max_upload_bytes:
                        raise HTTPException(413, "上传文件超过大小限制")
                    digest.update(block)
                    await run_in_threadpool(target.write, block)
            partial.rename(final)
            info, duration, codec, compatible, message = await run_in_threadpool(self.probe, final)
            video_id, retained = await run_in_threadpool(
                self.repository.register_upload, digest.hexdigest(), filename, final, info,
                duration, codec, compatible, message)
            row = self.get(video_id)
            if not retained:
                # Existing managed copy might have been removed externally.
                self.registered_path(row)
            return public_video(row)
        finally:
            await upload.close()
            partial.unlink(missing_ok=True)
            if not retained:
                final.unlink(missing_ok=True)
