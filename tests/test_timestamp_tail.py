"""Bounded tail tolerance must not hide corrupt timelines or shift frames."""
import io
import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.core.analyzer import VideoAnalyzer
from backend.core.timestamps import VideoTimestamps
from backend.core.video_io import VideoInfo, VideoIOError, VideoWriter


def probe(monkeypatch, stamps, duration):
    monkeypatch.setattr("backend.core.timestamps.shutil.which", lambda _: "ffprobe")
    monkeypatch.setattr("backend.core.timestamps.subprocess.run", lambda *a, **kw:
                        SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
                            {"streams": [{"duration": duration}]})))
    monkeypatch.setattr("backend.core.timestamps.subprocess.Popen", lambda *a, **kw:
                        SimpleNamespace(stdout=io.StringIO("".join(
                            f"best_effort_timestamp_time={t}|duration_time=0.033333\n" for t in stamps)),
                            wait=lambda **kw: 0, poll=lambda: 0))


def test_real_failure_pattern_keeps_raw_pts_and_logs(monkeypatch, tmp_path, caplog):
    probe(monkeypatch, [10, 309.966667, 310, 309.9, 310], 300.033333)
    with VideoTimestamps(tmp_path / "unused.mp4", 30) as timing:
        rows = list(timing)
    assert [r.seconds for r in rows] == pytest.approx([0, 299.966667, 300, 299.9, 300])
    assert [r.indexable for r in rows] == [True, True, True, False, False]
    assert timing.skipped_tail_frames == 2 and timing.estimated_tail
    assert timing.previous == 300 and timing.duration_seconds == pytest.approx(300.033333)
    assert caplog.text.count("跳过异常尾帧索引") == 2


@pytest.mark.parametrize("stamps,duration", [
    ([0, 5, 5], 10),                  # Duplicate in the middle.
    ([0, 9.9, 9.6], 10),             # Backstep beyond 200 ms.
    ([0, 9.9, 9.8, 9.8, 9.8, 9.8], 10),  # More than three bad frames.
    ([0, 9.9, 9.8, 9.95], 10),       # Not a terminal suffix.
    ([0, 0], 0.1),                   # Short clip must not tolerate the entire timeline.
    ([0, 9.9, 9.8], 0),              # Unknown duration cannot prove tail position.
    ([0, 9.9, "N/A"], 10),          # Missing PTS remains fatal.
    ([0, 9.9, "nan"], 10),
])
def test_outside_tail_policy_still_fails(monkeypatch, tmp_path, stamps, duration):
    probe(monkeypatch, stamps, duration)
    with pytest.raises(VideoIOError, match="时间戳无效"):
        with VideoTimestamps(tmp_path / "unused.mp4", 30) as timing:
            list(timing)


@pytest.mark.parametrize("fps", [None, 2])
def test_scan_counts_all_frames_but_never_indexes_rejected_tail(monkeypatch, tmp_path, fps):
    source = tmp_path / "clip.mp4"
    with VideoWriter(source, VideoInfo(source, 12, 96, 64, 24)) as writer:
        for i in range(24):
            writer.write(np.full((64, 96, 3), i * 8, np.uint8))
    stamps = [i / 12 for i in range(21)] + [1.9, 1.85, 1.9]
    probe(monkeypatch, stamps, 2)
    calls = []
    detector = SimpleNamespace(detect=lambda frame: calls.append(float(frame.mean())) or [])
    records, progress = [], []
    summary = VideoAnalyzer(detector).scan(source, analysis_fps=fps,
                                          on_frame=records.append, on_progress=progress.append)
    assert summary.processed_frames == progress[-1].processed_frames == 24
    assert summary.skipped_tail_frames == 2
    assert all(r.frame_index <= 21 for r in records)
    expected = list(range(22)) if fps is None else [0, 6, 12, 18]
    assert [r.frame_index for r in records] == expected
    assert [r.timestamp_seconds for r in records] == pytest.approx([stamps[i] for i in expected])
    # Pixel values prove rejected frames are not passed to the detector, and
    # every retained timestamp stays paired with its original decoded frame.
    assert calls == pytest.approx([i * 8 for i in expected], abs=6)
