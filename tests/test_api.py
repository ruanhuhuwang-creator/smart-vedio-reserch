from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.config import APIConfig
from backend.config import DetectionConfig
from backend.core.detector import Detection, DetectionError
from backend.core.video_io import VideoInfo, VideoWriter
from backend.database.api_repository import APIRepository
from backend.database.repository import IndexRepository
from backend.main import create_app
from backend.services.indexing import IndexingService


class Controller:
    def __init__(self):
        self.calls = 0
        self.loads = 0
        self.block_at = None
        self.fail_at = None
        self.started = threading.Event()
        self.release = threading.Event()
        self.active = 0
        self.max_active = 0

    def loader(self, config):
        self.loads += 1
        controller = self

        class Detector:
            device = "mock"

            def detect(self, frame):
                controller.calls += 1
                controller.active += 1
                controller.max_active = max(controller.max_active, controller.active)
                try:
                    if controller.calls == controller.block_at:
                        controller.started.set()
                        if not controller.release.wait(10):
                            raise RuntimeError("test gate timed out")
                    if controller.calls == controller.fail_at:
                        raise DetectionError("injected YOLO failure")
                    return [Detection(0, "person", .95, (1, 1, 30, 40)),
                            Detection(2, "car", .9, (30, 10, 60, 50))]
                finally:
                    controller.active -= 1
        return Detector()


@pytest.fixture
def settings(tmp_path):
    weights = tmp_path / "fake.pt"
    weights.write_bytes(b"offline-test-weights")
    return APIConfig(database=tmp_path / "api.sqlite3", video_dir=tmp_path / "uploads", weights=weights)


@pytest.fixture
def video(tmp_path):
    if not shutil.which("ffprobe"):
        pytest.skip("FFprobe required")
    path = tmp_path / "source.mp4"
    with VideoWriter(path, VideoInfo(path, 12, 96, 64, 24)) as writer:
        for i in range(24):
            writer.write(np.full((64, 96, 3), i * 7, np.uint8))
    return path


@pytest.fixture
def h264(video, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    path = tmp_path / "browser.mp4"
    result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-c:v", "libx264",
                             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], capture_output=True)
    assert result.returncode == 0, result.stderr
    return path


@pytest.fixture
def api(settings):
    controller = Controller()
    app = create_app(settings, detector_loader=controller.loader)
    with TestClient(app) as client:
        try:
            yield client, app, controller
        finally:
            controller.release.set()


def upload(client, path, filename="video.mp4", extra=b""):
    response = client.post("/api/videos", files={"file": (filename, path.read_bytes() + extra, "video/mp4")})
    assert response.status_code == 201, response.text
    return response.json()


def submit(client, video_id, **kwargs):
    response = client.post(f"/api/videos/{video_id}/analysis", json=kwargs)
    assert response.status_code == 202, response.text
    return response.json()


def terminal(client, task_id, timeout=8):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        task = response.json()
        if task["status"] in {"succeeded", "failed"}:
            return task
        time.sleep(.02)
    pytest.fail("task did not finish")


def test_upload_list_detail_and_dedup(api, video):
    client, app, control = api
    item = upload(client, video, "../../test.mp4")
    assert item["filename"] == "test.mp4" and item["duration"] == 2
    assert item["analysis_status"] == "not_analyzed" and not item["index_available"]
    assert "path" not in item
    assert len(list(app.state.videos.root.iterdir())) == 1
    stored = next(app.state.videos.root.iterdir())
    assert stored.name != "test.mp4" and stored.read_bytes() == video.read_bytes()
    assert upload(client, video)["video_id"] == item["video_id"]
    assert len(list(app.state.videos.root.iterdir())) == 1
    listing = client.get("/api/videos?offset=0&limit=1").json()
    assert listing["total"] == 1 and listing["items"][0]["video_id"] == item["video_id"]
    assert client.get("/api/videos?offset=1&limit=1").json()["items"] == []
    assert client.get(f"/api/videos/{item['video_id']}").json() == item
    assert control.loads == 0


@pytest.mark.parametrize("filename,data,expected", [("fake.mp4", b"not a video", 422),
                                                     ("file.txt", b"content", 415), ("empty.mp4", b"", 422)])
def test_invalid_upload_cleaned(api, filename, data, expected):
    client, app, _ = api
    result = client.post("/api/videos", files={"file": (filename, data)})
    assert result.status_code == expected
    assert list(app.state.videos.root.iterdir()) == []
    assert client.get("/api/videos").json()["total"] == 0


def test_upload_limits(settings, video):
    with TestClient(create_app(replace(settings, max_upload_bytes=32))) as client:
        assert client.post("/api/videos", files={"file": ("large.mp4", video.read_bytes())}).status_code == 413
        assert client.post("/api/videos", content=b"x" * 70000).status_code == 413
        body = b"--bound\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.mp4\"\r\n\r\n" + b"x" * 70000 + b"\r\n--bound--\r\n"
        response = client.post("/api/videos", content=(body[i:i+4096] for i in range(0, len(body), 4096)),
                               headers={"Content-Type": "multipart/form-data; boundary=bound"})
        assert response.status_code == 413
        assert list(settings.video_dir.iterdir()) == []


def test_async_task_progress_conflict_and_success(api, video):
    client, app, control = api
    video_id = upload(client, video)["video_id"]
    assert client.get(f"/api/videos/{video_id}/events").status_code == 409
    control.block_at = 2
    before = time.monotonic()
    task = submit(client, video_id)
    assert time.monotonic() - before < 1
    assert task["status"] == "queued"
    assert control.started.wait(4)
    running = client.get(f"/api/tasks/{task['task_id']}").json()
    assert running["status"] == "running"
    assert 0 < running["progress"] < 100 and running["processed_frames"] >= 1
    assert running["progress_is_estimate"]
    not_ready = client.get(f"/api/videos/{video_id}/events")
    assert not_ready.status_code == 409 and not_ready.json()["detail"]["analysis_status"] == "running"
    assert client.post(f"/api/videos/{video_id}/analysis", json={}).status_code == 409
    assert client.get("/health").json()["status"] == "ok"
    control.release.set()
    done = terminal(client, task["task_id"])
    assert done["status"] == "succeeded" and done["progress"] == 100
    assert done["processed_frames"] == 24 and not done["progress_is_estimate"]
    assert done["started_at"] and done["finished_at"] and done["error_message"] is None
    assert client.get(f"/api/videos/{video_id}").json()["filename"] == "video.mp4"
    assert control.max_active == 1 and control.loads == 1


def test_events_filters_reuse_and_model_cache(api, video):
    client, app, control = api
    vid = upload(client, video)["video_id"]
    first = terminal(client, submit(client, vid)["task_id"])
    assert first["status"] == "succeeded"
    events = client.get(f"/api/videos/{vid}/events?category=person").json()["events"]
    assert events[0]["category"] == "person" and events[0]["start_time"] == 0 and events[0]["end_time"] == 1.5
    assert client.get(f"/api/videos/{vid}/events?category=car").json()["events"]
    assert client.get(f"/api/videos/{vid}/events?category=bicycle").json()["events"] == []
    assert client.get(f"/api/videos/{vid}/events?start_time=2").json()["events"] == []
    assert client.get(f"/api/videos/{vid}/events?end_time=1&start_time=0.5").json()["events"]
    assert client.get(f"/api/videos/{vid}/events?end_time=0&start_time=1").status_code == 422
    calls = control.calls
    second = terminal(client, submit(client, vid)["task_id"])
    assert second["index_reused"] and control.calls == calls
    rebuilt = terminal(client, submit(client, vid, force_rebuild=True, imgsz=416)["task_id"])
    assert rebuilt["status"] == "succeeded" and not rebuilt["index_reused"]
    assert control.loads == 1  # Changing inference size does not load a second GPU model.
    assert app.state.index.counts(vid) == {"detections": 8, "events": 2}


def test_failed_force_keeps_old_index_and_worker_survives(api, video):
    client, app, control = api
    vid = upload(client, video)["video_id"]
    terminal(client, submit(client, vid)["task_id"])
    old = client.get(f"/api/videos/{vid}/events").json()["events"]
    control.fail_at = control.calls + 2
    failed = terminal(client, submit(client, vid, force_rebuild=True)["task_id"])
    assert failed["status"] == "failed" and "injected YOLO failure" in failed["error_message"]
    assert failed["progress"] < 100 and failed["finished_at"]
    response = client.get(f"/api/videos/{vid}/events").json()
    assert response["events"] == old and response["using_previous_index"]
    assert app.state.index.counts(vid) == {"detections": 8, "events": 2}
    assert terminal(client, submit(client, vid, force_rebuild=True)["task_id"])["status"] == "succeeded"


def test_first_failure_has_no_fake_empty_events(api, video):
    client, _, control = api
    vid = upload(client, video)["video_id"]
    control.fail_at = 1
    assert terminal(client, submit(client, vid)["task_id"])["status"] == "failed"
    response = client.get(f"/api/videos/{vid}/events")
    assert response.status_code == 409 and response.json()["detail"]["analysis_status"] == "failed"


@pytest.mark.parametrize("body", [{"sample_fps": 0}, {"sample_fps": 1000}, {"imgsz": 8192},
                                  {"confidence": 0}, {"force_rebuild": "yes"}, {"path": "C:/Windows/win.ini"}])
def test_analysis_parameter_validation(api, video, body):
    client, _, _ = api
    vid = upload(client, video)["video_id"]
    assert client.post(f"/api/videos/{vid}/analysis", json=body).status_code == 422


def test_queue_capacity_and_serial_execution(settings, video):
    control = Controller()
    control.block_at = 1
    app = create_app(replace(settings, queue_capacity=1), detector_loader=control.loader)
    with TestClient(app) as client:
        try:
            a = upload(client, video, extra=b"\0" * 8)["video_id"]
            b = upload(client, video, extra=b"\0" * 16)["video_id"]
            c = upload(client, video, extra=b"\0" * 24)["video_id"]
            first = submit(client, a)
            assert control.started.wait(4)
            second = submit(client, b)
            assert client.get(f"/api/tasks/{second['task_id']}").json()["status"] == "queued"
            assert client.post(f"/api/videos/{c}/analysis", json={}).status_code == 429
            control.release.set()
            assert terminal(client, first["task_id"])["status"] == "succeeded"
            assert terminal(client, second["task_id"])["status"] == "succeeded"
            assert control.max_active == 1 and control.loads == 1
        finally:
            control.release.set()


@pytest.mark.parametrize("range_header,code", [("bytes=0-31", 206), ("bytes=-16", 206),
                                              ("bytes=99999999-", 416), ("bytes=20-10", 400), ("invalid", 400)])
def test_stream_ranges(api, h264, range_header, code):
    client, _, _ = api
    vid = upload(client, h264)["video_id"]
    response = client.get(f"/api/videos/{vid}/stream", headers={"Range": range_header})
    assert response.status_code == code
    if range_header == "bytes=0-31":
        assert response.content == h264.read_bytes()[:32]
        assert response.headers["content-range"].startswith("bytes 0-31/")
        assert response.headers["accept-ranges"] == "bytes"
    elif range_header == "bytes=-16":
        assert response.content == h264.read_bytes()[-16:]


def test_codec_path_missing_and_not_found(api, video, h264, tmp_path):
    client, app, _ = api
    vid = upload(client, video)["video_id"]
    assert client.get(f"/api/videos/{vid}/stream").status_code == 415
    managed = upload(client, h264)["video_id"]
    actual = client.get(f"/api/videos/{managed}/stream?path=C:/Windows/win.ini")
    assert actual.status_code == 200 and actual.content == h264.read_bytes()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"server secret")
    with app.state.index.transaction() as conn:
        conn.execute("UPDATE videos SET path=? WHERE id=?", (str(outside), managed))
    assert client.get(f"/api/videos/{managed}/stream").status_code == 404
    app.state.videos.registered_path(app.state.videos.get(vid)).unlink()
    assert client.get(f"/api/videos/{vid}/stream").status_code == 404
    assert client.get("/api/videos/999").status_code == 404
    assert client.get("/api/videos/999/events").status_code == 404
    assert client.get("/api/tasks/missing").status_code == 404
    assert client.post("/api/videos/999/analysis", json={}).status_code == 404


def test_restart_interrupt_recovery(settings, video):
    with TestClient(create_app(settings)) as client:
        vid = upload(client, video)["video_id"]
    index = IndexRepository(settings.database)
    api_repo = APIRepository(index)
    running = api_repo.create_task(vid, {"sample_fps": 2, "imgsz": 640, "confidence": .35, "force_rebuild": False})
    api_repo.start(running["task_id"])
    with index.transaction() as conn:
        conn.execute("UPDATE videos SET status='analyzing' WHERE id=?", (vid,))
    with TestClient(create_app(settings)) as client:
        task = client.get(f"/api/tasks/{running['task_id']}").json()
        assert task["status"] == "failed" and "上次停止" in task["error_message"]
        assert task["finished_at"]
        assert client.get(f"/api/videos/{vid}/events").status_code == 409


def test_single_process_lock_and_cors(api, settings):
    client, _, _ = api
    with pytest.raises(RuntimeError, match="单进程"):
        with TestClient(create_app(settings)):
            pass
    good = client.options("/api/videos", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert good.headers["access-control-allow-origin"] == "http://localhost:5173"
    bad = client.options("/api/videos", headers={"Origin": "https://other.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_v1_migration_preserves_records(tmp_path):
    database = tmp_path / "old.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.executescript(Path("backend/database/schema.sql").read_text(encoding="utf8"))
        conn.execute("INSERT INTO videos(id,content_sha256,name,path,duration,fps,width,height,status,analysis_key) "
                     "VALUES(1,'hash','old.mp4','old.mp4',2,12,96,64,'completed','key')")
        conn.execute("INSERT INTO detections(video_id,frame_index,timestamp,class_id,class_name,confidence,x1,y1,x2,y2) "
                     "VALUES(1,0,0,0,'person',.9,1,1,2,2)")
        conn.execute("INSERT INTO events(video_id,class_name,start_time,end_time,sample_count) VALUES(1,'person',0,1.5,4)")
    repo = IndexRepository(database)
    IndexRepository(database)  # Repeated initialization must not repeat ALTERs or lose data.
    assert repo.counts(1) == {"detections": 1, "events": 1}
    assert repo.get_video(1)["analysis_key"] == "key"
    with repo.connection() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_progress_is_not_success(api, video):
    client, app, _ = api
    vid = upload(client, video)["video_id"]
    task = app.state.repository.create_task(vid, {})
    app.state.repository.start(task["task_id"])
    app.state.repository.progress(task["task_id"], 3, None)
    unknown = client.get(f"/api/tasks/{task['task_id']}").json()
    assert unknown["progress"] is None and unknown["total_frames"] is None
    app.state.repository.progress(task["task_id"], 24, 24)
    running = client.get(f"/api/tasks/{task['task_id']}").json()
    assert running["status"] == "running" and running["progress"] == 99
    app.state.repository.failed(task["task_id"], "publication failed")
    assert client.get(f"/api/tasks/{task['task_id']}").json()["status"] == "failed"


def test_upload_adopts_existing_cli_index(settings, video):
    controller = Controller()
    repository = IndexRepository(settings.database)
    original = IndexingService(repository, controller.loader).analyze(
        video, detection=DetectionConfig(weights=settings.weights))
    with TestClient(create_app(settings, detector_loader=controller.loader)) as client:
        registered = upload(client, video)
        assert registered["video_id"] == original.video_id and registered["index_available"]
        assert client.get(f"/api/videos/{original.video_id}/events?category=person").json()["events"]
        reused = terminal(client, submit(client, original.video_id)["task_id"])
        assert reused["index_reused"] and controller.loads == 1 and controller.calls == 4


def test_nonfinite_json_rejected(api, video):
    client, _, control = api
    vid = upload(client, video)["video_id"]
    result = client.post(f"/api/videos/{vid}/analysis", content='{"sample_fps":NaN}',
                         headers={"Content-Type": "application/json"})
    assert result.status_code == 422 and control.loads == 0


def test_restart_fails_queued_and_preserves_previous_index(settings, video):
    controller = Controller()
    with TestClient(create_app(settings, detector_loader=controller.loader)) as client:
        vid = upload(client, video)["video_id"]
        terminal(client, submit(client, vid)["task_id"])
        old_events = client.get(f"/api/videos/{vid}/events").json()["events"]
        other_id = upload(client, video, extra=b"\0" * 8)["video_id"]
    index = IndexRepository(settings.database)
    repo = APIRepository(index)
    parameters = {"sample_fps": 2, "imgsz": 640, "confidence": .35, "force_rebuild": True}
    running = repo.create_task(vid, parameters)
    repo.start(running["task_id"])
    queued = repo.create_task(other_id, parameters)
    with index.transaction() as conn:
        conn.execute("UPDATE videos SET status='analyzing' WHERE id=?", (vid,))
    with TestClient(create_app(settings)) as client:
        for task in [running, queued]:
            assert client.get(f"/api/tasks/{task['task_id']}").json()["status"] == "failed"
        result = client.get(f"/api/videos/{vid}/events").json()
        assert result["events"] == old_events and result["using_previous_index"]
