"""Real YOLO/CLI validation using the existing phase-one clip, no downloads."""
import json
import os
import subprocess
import sys
import time

import numpy as np

from backend.config import PROJECT_ROOT
from backend.core.video_io import VideoInfo, VideoWriter
from backend.database.repository import IndexRepository
from backend.services.indexing import file_hash
from backend.services.search import SearchService


def main():
    os.environ["PYTHONUTF8"] = "1"
    source = PROJECT_ROOT / "data" / "outputs" / "validation" / "example_clip.mp4"
    if not source.is_file():
        raise RuntimeError("请先运行第一阶段 tests.validate_runtime 生成测试视频")
    output = PROJECT_ROOT / "data" / "outputs" / "phase2_validation" / str(time.time_ns())
    output.mkdir(parents=True)
    db = output / "index.sqlite3"
    logs = []
    before_hash = file_hash(source)

    def run(*args):
        completed = subprocess.run([sys.executable, "-m", "backend.index_cli", *map(str, args), "--db", str(db)],
                                   cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8")
        logs.append(" ".join(map(str, args)) + "\n" + completed.stdout + completed.stderr)
        (output / "cli.log").write_text("\n\n".join(logs), encoding="utf-8")
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return completed.stdout

    first = run("analyze", source)
    repo = IndexRepository(db)
    rows = SearchService(repo).search("person")
    assert rows and rows[0]["start_time"] == 0 and rows[0]["end_time"] == 1.5
    video_id = rows[0]["video_id"]
    times = sorted({r["timestamp"] for r in repo.raw_detections(video_id)})
    assert times == [0, 0.5, 1, 1.5]
    baseline = {"video": repo.get_video(video_id), "counts": repo.counts(video_id), "person_events": rows}
    repeated = run("analyze", source)
    assert "复用已有索引" in repeated
    assert "推理设备" not in repeated
    assert repo.counts(video_id) == baseline["counts"]
    for _ in range(2):
        assert json.loads(run("search", "person", "--video-id", video_id, "--json")) == rows
    assert json.loads(run("search", "car", "--video-id", video_id, "--json")) == []
    run("rebuild-events", "--video-id", video_id, "--merge-gap", 0.1)
    assert SearchService(repo).search("person", video_id) == []
    assert repo.counts(video_id)["detections"] == baseline["counts"]["detections"]
    run("rebuild-events", "--video-id", video_id, "--merge-gap", 1)
    assert SearchService(repo).search("person", video_id) == rows

    run("analyze", source, "--analysis-fps", 3, "--imgsz", 416)
    raw = repo.raw_detections(video_id)
    times_3fps = sorted({r["timestamp"] for r in raw})
    assert times_3fps == [0, 0.333333, 0.666667, 1, 1.333333, 1.666667]
    counts_3fps = repo.counts(video_id)
    run("analyze", source, "--analysis-fps", 3, "--imgsz", 416, "--force")
    assert repo.counts(video_id) == counts_3fps
    run("analyze", source, "--every-frame", "--imgsz", 960)
    assert repo.get_video(video_id)["sampled_frames"] == 24
    counts_every_frame = repo.counts(video_id)
    # Restore the default 2 FPS index so the saved DB is useful for the README demo.
    run("analyze", source)
    assert repo.counts(video_id) == baseline["counts"]

    black = output / "black.mp4"
    with VideoWriter(black, VideoInfo(black, 12, 96, 64, 12)) as writer:
        for _ in range(12):
            writer.write(np.zeros((64, 96, 3), np.uint8))
    run("analyze", black)
    with repo.connection() as connection:
        blank_id = connection.execute("SELECT id FROM videos WHERE path=?", (str(black),)).fetchone()[0]
    assert repo.counts(blank_id) == {"detections": 0, "events": 0}
    assert json.loads(run("search", "person", "--video-id", blank_id, "--json")) == []
    assert file_hash(source) == before_hash
    assert not list(output.glob("*detected*.mp4"))
    assert "torch" not in sys.modules
    report = {"database": str(db), "source_sha256": before_hash, "default_2fps": baseline,
              "timestamps_3fps_416": times_3fps, "counts_3fps_416": counts_3fps,
              "counts_every_frame_960": counts_every_frame, "blank_video_id": blank_id,
              "blank_counts": repo.counts(blank_id), "source_unchanged": True,
              "repeat_reuses_index": True, "search_process_imported_torch": False,
              "no_annotated_output": True}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
