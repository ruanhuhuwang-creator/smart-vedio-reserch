"""Real loopback HTTP + CUDA smoke test, independent of pytest's mock models.

Pass --source VIDEO or --download-sample for OpenCV's public moving-video sample.
Only a separate H.264 test fixture is encoded; the supplied source is untouched.
"""
import argparse
from hashlib import sha1
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen

import httpx

from backend.config import PROJECT_ROOT
from backend.services.indexing import file_hash


def download_sample(folder):
    metadata_url = "https://api.github.com/repos/opencv/opencv/contents/samples/data/vtest.avi?ref=4.10.0"
    with urlopen(metadata_url, timeout=30) as response:
        metadata = json.load(response)
    source = folder / "vtest.avi"
    partial = folder / "vtest.avi.partial"
    for attempt in range(5):
        offset = partial.stat().st_size if partial.exists() else 0
        # GitHub's blob endpoint avoids environments that block raw.githubusercontent.com.
        request = Request(metadata["git_url"], headers={"Range": f"bytes={offset}-",
                          "Accept": "application/vnd.github.raw+json", "User-Agent": "SmartVision-validation"})
        try:
            with urlopen(request, timeout=30) as response:
                mode = "ab" if response.status == 206 and offset else "wb"
                with partial.open(mode) as target:
                    while block := response.read(16384):
                        target.write(block)
            if partial.stat().st_size == metadata["size"]:
                break
        except OSError:
            if attempt == 4:
                raise
    assert partial.stat().st_size == metadata["size"], "Sample transfer incomplete"
    digest = sha1(f"blob {metadata['size']}\0".encode())
    with partial.open("rb") as data:
        for block in iter(lambda: data.read(1024 * 1024), b""):
            digest.update(block)
    assert digest.hexdigest() == metadata["sha"], "GitHub sample blob checksum mismatch"
    partial.rename(source)
    return source, metadata_url


def main():
    parser = argparse.ArgumentParser()
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--source", type=Path)
    source_group.add_argument("--download-sample", action="store_true")
    args = parser.parse_args()
    output = PROJECT_ROOT / "data" / "outputs" / "phase3_http_validation" / str(time.time_ns())
    output.mkdir(parents=True)
    source, provenance = download_sample(output) if args.download_sample else (args.source.resolve(), "user/local source")
    source_hash = file_hash(source)
    playable = output / "browser_fixture.mp4"
    ffmpeg = subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-t", "6", "-an",
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(playable)],
                            capture_output=True, timeout=60)
    assert ffmpeg.returncode == 0, ffmpeg.stderr.decode(errors="replace")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = dict(os.environ, PYTHONUTF8="1", SMARTVISION_DATABASE=str(output / "api.sqlite3"),
               SMARTVISION_VIDEO_DIR=str(output / "uploads"), TEMP=str(output), TMP=str(output))
    report = {"source": str(source), "source_provenance": provenance, "source_sha256": source_hash,
              "fixture": str(playable), "database": str(output / "api.sqlite3")}
    log = (output / "server.log").open("w", encoding="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1",
                               "--port", str(port), "--workers", "1"], cwd=PROJECT_ROOT, env=env, stdout=log, stderr=log)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False) as client:
            for _ in range(100):
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if server.poll() is not None:
                    raise RuntimeError("Uvicorn exited; inspect server.log")
                time.sleep(.1)
            else:
                raise RuntimeError("HTTP service not ready")
            assert client.get("/docs").status_code == 200
            assert "/api/videos" in client.get("/openapi.json").json()["paths"]
            with playable.open("rb") as media:
                uploaded = client.post("/api/videos", files={"file": ("pedestrians.mp4", media, "video/mp4")})
            assert uploaded.status_code == 201, uploaded.text
            report["upload"] = uploaded.json()
            video_id = uploaded.json()["video_id"]
            assert uploaded.json()["browser_compatible"]
            assert client.get(f"/api/videos/{video_id}/events").status_code == 409
            started = time.monotonic()
            submitted = client.post(f"/api/videos/{video_id}/analysis", json={})
            report["submit_seconds"] = time.monotonic() - started
            assert submitted.status_code == 202, submitted.text
            history = []

            def wait_task(task_id):
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    state = client.get(f"/api/tasks/{task_id}").json()
                    history.append(state)
                    if state["status"] in {"succeeded", "failed"}:
                        return state
                    assert client.get("/health").json()["status"] == "ok"
                    time.sleep(.1)
                raise RuntimeError("Analysis timed out")

            report["task"] = wait_task(submitted.json()["task_id"])
            assert report["task"]["status"] == "succeeded", report["task"]
            assert report["task"]["progress"] == 100
            person = client.get(f"/api/videos/{video_id}/events", params={"category": "person"})
            assert person.status_code == 200
            report["person_events"] = person.json()
            assert person.json()["events"], "Moving-video sample did not yield person events; inspect actual predictions"
            report["car_events"] = client.get(f"/api/videos/{video_id}/events", params={"category": "car"}).json()
            ranged = client.get(f"/api/videos/{video_id}/stream", headers={"Range": "bytes=0-1023"})
            assert ranged.status_code == 206
            with playable.open("rb") as media:
                assert ranged.content == media.read(1024)
            report["stream"] = {"status": ranged.status_code, "content_range": ranged.headers["content-range"]}
            assert client.get(f"/api/videos/{video_id}/stream", headers={"Range": "bytes=999999999-"}).status_code == 416
            again = client.post(f"/api/videos/{video_id}/analysis", json={})
            assert again.status_code == 202
            reused = wait_task(again.json()["task_id"])
            assert reused["status"] == "succeeded" and reused["index_reused"]
            report["reused_task"] = reused
            with source.open("rb") as original:
                raw_upload = client.post("/api/videos", files={"file": (source.name, original, "application/octet-stream")})
            assert raw_upload.status_code == 201, raw_upload.text
            report["raw_source_upload"] = raw_upload.json()
            if not raw_upload.json()["browser_compatible"]:
                incompatible = client.get(raw_upload.json()["stream_url"])
                assert incompatible.status_code == 415
                report["incompatible_stream_status"] = incompatible.status_code
            devices = re.findall(r"推理设备: (cuda:\d+|cpu)", (output / "server.log").read_text(encoding="utf-8"))
            report["observed_inference_devices"] = devices
            report["progress_history"] = history
            report["original_source_unchanged"] = file_hash(source) == source_hash
            assert report["original_source_unchanged"]
            from backend.database.repository import IndexRepository
            repo = IndexRepository(output / "api.sqlite3")
            report["index_counts"] = repo.counts(video_id)
            assert repo.get_video(video_id)["sampled_frames"] > 1
            # CUDA code only ran in the actual server process, not this client.
            with repo.connection() as conn:
                report["schema_version"] = conn.execute("PRAGMA user_version").fetchone()[0]
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({key: value for key, value in report.items() if key != "progress_history"}, ensure_ascii=False, indent=2))
    finally:
        server.terminate()
        server.wait(timeout=30)
        log.close()


if __name__ == "__main__":
    main()
