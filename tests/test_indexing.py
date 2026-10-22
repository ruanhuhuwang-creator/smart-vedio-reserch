from dataclasses import replace
import shutil
import subprocess
import io
from types import SimpleNamespace

import numpy as np
import pytest

from backend.config import DetectionConfig, IndexConfig
from backend.core.analyzer import FrameResult, ScanSummary, VideoAnalyzer
from backend.core.detector import Detection, DetectionError
from backend.core.video_io import VideoInfo, VideoWriter
from backend.core.video_io import VideoIOError
from backend.core.timestamps import VideoTimestamps
from backend.database.repository import IndexBusyError, IndexRepository
from backend.services.events import Event, merge_observations
from backend.services.indexing import IndexingService, file_hash
from backend.services.search import SearchService


def merge(rows, duration=10, gap=1, minimum=2):
    return list(merge_observations(rows, duration=duration, merge_gap=gap, min_samples=minimum))


def test_merge_classes_misses_and_duplicates():
    rows = [("car", 1), ("car", 1.5), ("person", 0), ("person", 0),
            ("person", 0.5), ("person", 1.5), ("person", 4)]
    assert merge(rows) == [Event("car", 1, 1.5, 2), Event("person", 0, 1.5, 3)]
    assert merge(rows, gap=0.6) == [Event("car", 1, 1.5, 2), Event("person", 0, 0.5, 2)]


def test_empty_singleton_and_duration_bounds():
    assert merge([]) == []
    assert merge([("person", 3)] * 4) == []
    assert merge([("person", 0.5), ("person", 1), ("person", 2)], duration=1) == [Event("person", 0.5, 1, 2)]
    assert merge([("person", 0), ("person", 0.5)], minimum=3) == []


@pytest.mark.parametrize("rows", [[("person", -1)], [("person", float("nan"))],
                                  [("person", 1), ("person", 0)]])
def test_bad_observations(rows):
    with pytest.raises(ValueError):
        merge(rows)


@pytest.mark.parametrize("kwargs", [{"analysis_fps": 0}, {"analysis_fps": float("inf")},
                                    {"merge_gap": -1}, {"min_samples": 1}])
def test_invalid_index_config(kwargs):
    with pytest.raises(ValueError):
        IndexConfig(**kwargs)


@pytest.fixture
def indexing_clip(tmp_path):
    if not shutil.which("ffprobe"):
        pytest.skip("FFprobe required for timestamp integration tests")
    path = tmp_path / "input.mp4"
    info = VideoInfo(path, 12, 96, 64, 24)
    with VideoWriter(path, info) as writer:
        for index in range(24):
            writer.write(np.full((64, 96, 3), index * 8, np.uint8))
    return path


class SequenceDetector:
    device = "mock"

    def __init__(self, sequence=None):
        self.calls = 0
        self.sequence = sequence

    def detect(self, frame):
        index = self.calls
        self.calls += 1
        if self.sequence is not None and index not in self.sequence:
            return []
        return [Detection(0, "person", 0.9, (5, 5, 30, 40))] * 2


@pytest.fixture
def setup_index(tmp_path):
    weights = tmp_path / "fake-model.pt"
    weights.write_bytes(b"fake weights for offline unit tests")
    config = DetectionConfig(weights=weights)
    repo = IndexRepository(tmp_path / "test.sqlite3")
    return repo, config


@pytest.mark.parametrize("fps,expected", [(2, [0, 0.5, 1, 1.5]), (3, [0, 0.333333, 0.666667, 1, 1.333333, 1.666667]),
                                          (100, [i / 12 for i in range(24)]), (None, [i / 12 for i in range(24)])])
def test_sampling_pts_and_source_preserved(indexing_clip, fps, expected):
    records = []
    original_hash = file_hash(indexing_clip)
    detector = SequenceDetector()
    summary = VideoAnalyzer(detector).scan(indexing_clip, analysis_fps=fps, on_frame=records.append)
    assert [r.timestamp_seconds for r in records] == pytest.approx(expected, abs=1e-6)
    assert summary.processed_frames == 24
    assert summary.analyzed_frames == len(expected) == detector.calls
    assert summary.duration_seconds == pytest.approx(2)
    assert file_hash(indexing_clip) == original_hash
    assert list(indexing_clip.parent.glob("*.mp4")) == [indexing_clip]


def test_index_once_search_many_and_remerge(indexing_clip, setup_index):
    repo, config = setup_index
    loads = []
    detector = SequenceDetector()
    service = IndexingService(repo, lambda cfg: loads.append(cfg) or detector)
    first = service.analyze(indexing_clip, detection=config)
    search = SearchService(repo)
    assert not first.reused
    assert repo.counts(first.video_id) == {"detections": 8, "events": 1}
    result = search.search(" PERSON ", first.video_id)
    assert result[0]["start_time"] == 0
    assert result[0]["end_time"] == 1.5
    assert result[0]["sample_count"] == 4  # Not eight boxes.
    for _ in range(3):
        assert search.search("person", first.video_id) == result
    assert search.search("car", first.video_id) == []
    assert search.search("person' OR 1=1 --") == []
    second = service.analyze(indexing_clip, detection=config)
    assert second.reused and second.video_id == first.video_id
    assert len(loads) == 1 and detector.calls == 4
    service.rebuild_events(first.video_id, merge_gap=0.1)
    assert search.search("person") == []
    assert repo.counts(first.video_id)["detections"] == 8
    service.analyze(indexing_clip, detection=config)  # Rebuild default events, no inference.
    assert search.search("person") == result
    assert len(loads) == 1


def test_empty_detections_and_short_miss(indexing_clip, setup_index):
    repo, config = setup_index
    empty = IndexingService(repo, lambda cfg: SequenceDetector(set())).analyze(indexing_clip, detection=config)
    assert repo.get_video(empty.video_id)["status"] == "completed"
    assert repo.counts(empty.video_id) == {"detections": 0, "events": 0}
    missed = IndexingService(repo, lambda cfg: SequenceDetector({0, 1, 3})).analyze(
        indexing_clip, detection=config, force=True)
    assert missed.video_id == empty.video_id
    assert SearchService(repo).search("person")[0]["end_time"] == 1.5
    singleton = IndexingService(repo, lambda cfg: SequenceDetector({0})).analyze(
        indexing_clip, detection=config, force=True)
    assert repo.counts(singleton.video_id) == {"detections": 2, "events": 0}


def test_force_parameter_change_and_duplicate_copy(indexing_clip, setup_index):
    repo, config = setup_index
    loads = []
    service = IndexingService(repo, lambda cfg: loads.append(cfg) or SequenceDetector())
    first = service.analyze(indexing_clip, detection=config)
    second = service.analyze(indexing_clip, detection=config, indexing=IndexConfig(analysis_fps=3))
    assert second.video_id == first.video_id and not second.reused
    assert repo.counts(first.video_id)["detections"] == 12
    assert repo.get_video(first.video_id)["sampled_frames"] == 6
    assert [r["timestamp"] for r in repo.raw_detections(first.video_id)][::2] == pytest.approx(
        [0, 1/3, 2/3, 1, 4/3, 5/3], abs=1e-6)
    copy = indexing_clip.with_name("copy.mp4")
    shutil.copyfile(indexing_clip, copy)
    third = service.analyze(copy, detection=config, indexing=IndexConfig(analysis_fps=3))
    assert third.reused and third.video_id == first.video_id and len(loads) == 2
    changed_size = service.analyze(copy, detection=replace(config, image_size=416), indexing=IndexConfig(analysis_fps=3))
    assert not changed_size.reused
    assert repo.counts(changed_size.video_id)["detections"] == 12


def test_failed_reanalysis_rolls_back(indexing_clip, setup_index):
    repo, config = setup_index
    service = IndexingService(repo, lambda cfg: SequenceDetector())
    first = service.analyze(indexing_clip, detection=config)
    old_raw = repo.raw_detections(first.video_id)
    old_events = SearchService(repo).search("person")
    class Broken(SequenceDetector):
        def detect(self, frame):
            if self.calls == 1:
                raise DetectionError("injected error")
            return super().detect(frame)
    broken = IndexingService(repo, lambda cfg: Broken())
    with pytest.raises(DetectionError):
        broken.analyze(indexing_clip, detection=config, force=True)
    assert repo.get_video(first.video_id)["status"] == "completed"
    assert "injected error" in repo.get_video(first.video_id)["last_error"]
    assert repo.raw_detections(first.video_id) == old_raw
    assert SearchService(repo).search("person") == old_events


def test_claim_busy_recovery_and_database_order(setup_index, tmp_path):
    repo, _ = setup_index
    info = VideoInfo(tmp_path / "seed.mp4", 12, 96, 64, 24)
    video_id, _ = repo.claim("hash", info, "key")
    with pytest.raises(IndexBusyError):
        repo.claim("hash", info, "key")
    repo.recover(video_id)
    assert repo.get_video(video_id)["status"] == "failed"
    video_id, _ = repo.claim("hash", info, "key")
    with repo.replace_index(video_id) as writer:
        for index, stamp in enumerate([0, 0.5, 1.5, 1.9]):
            writer.add_frame(FrameResult(index, stamp, [Detection(0, "person", 0.9, (1, 1, 2, 2))], True))
        writer.merge_events(2, 0.6, 2, merge_observations)
        writer.complete(ScanSummary(info, 2, 24, 4, 4, 0, 0, False), "key", DetectionConfig(), IndexConfig())
    assert [row["start_time"] for row in SearchService(repo).search("person")] == [0, 1.5]


def test_non_integral_source_fps_and_tail(tmp_path):
    if not shutil.which("ffprobe"):
        pytest.skip("FFprobe required")
    source = tmp_path / "fractional.mp4"
    with VideoWriter(source, VideoInfo(source, 29.97, 96, 64, 40)) as writer:
        for _ in range(40):
            writer.write(np.zeros((64, 96, 3), np.uint8))
    rows = []
    summary = VideoAnalyzer(SequenceDetector()).scan(source, analysis_fps=2, on_frame=rows.append)
    assert [row.frame_index for row in rows] == [0, 15, 30]
    assert [row.timestamp_seconds for row in rows] == pytest.approx([0, 15/29.97, 30/29.97], abs=1e-5)
    assert all(row.timestamp_seconds < summary.duration_seconds for row in rows)


def test_vfr_real_pts(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg required")
    # Vary intervals without changing frame order. H.264 adds B-frame reordering.
    raw = tmp_path / "raw.mp4"
    with VideoWriter(raw, VideoInfo(raw, 10, 96, 64, 6)) as writer:
        for _ in range(6):
            writer.write(np.zeros((64, 96, 3), np.uint8))
    vfr = tmp_path / "vfr.mp4"
    result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(raw), "-vf",
                             "setpts='if(lt(N,3),N*0.1/TB,(0.3+(N-3)*0.4)/TB)'",
                             "-fps_mode", "vfr", "-c:v", "libx264", str(vfr)], capture_output=True)
    assert result.returncode == 0, result.stderr
    records = []
    summary = VideoAnalyzer(SequenceDetector()).scan(vfr, analysis_fps=None, on_frame=records.append)
    assert [r.timestamp_seconds for r in records] == pytest.approx([0, 0.1, 0.2, 0.3, 0.7, 1.1], abs=1e-6)
    sampled = []
    VideoAnalyzer(SequenceDetector()).scan(vfr, analysis_fps=2, on_frame=sampled.append)
    assert [r.timestamp_seconds for r in sampled] == pytest.approx([0, 0.7, 1.1], abs=1e-6)
    assert summary.duration_seconds >= 1.1


def test_ffprobe_missing_marks_failure(indexing_clip, setup_index, monkeypatch):
    repo, config = setup_index
    monkeypatch.setattr("backend.core.timestamps.shutil.which", lambda name: None)
    with pytest.raises(VideoIOError, match="FFprobe"):
        IndexingService(repo, lambda cfg: SequenceDetector()).analyze(indexing_clip, detection=config)
    video = repo.get_video(1)
    assert video["status"] == "failed" and "FFprobe" in video["last_error"]
    assert repo.counts(1) == {"detections": 0, "events": 0}


@pytest.mark.parametrize("lines,valid", [
    ("best_effort_timestamp_time=10.0|duration_time=0.1\n"
     "best_effort_timestamp_time=10.5|duration_time=0.1\n", True),
    ("best_effort_timestamp_time=N/A\n", False),
    ("best_effort_timestamp_time=0.0\nbest_effort_timestamp_time=0.0\n", False)])
def test_original_timestamp_offset_and_invalid_pts(tmp_path, monkeypatch, lines, valid):
    stdout = io.StringIO(lines)
    process = SimpleNamespace(stdout=stdout, wait=lambda **kw: 0, poll=lambda: 0)
    monkeypatch.setattr("backend.core.timestamps.shutil.which", lambda name: "ffprobe")
    monkeypatch.setattr("backend.core.timestamps.subprocess.run", lambda *a, **kw:
                        SimpleNamespace(returncode=0, stdout='{"streams":[]}', stderr=""))
    monkeypatch.setattr("backend.core.timestamps.subprocess.Popen", lambda *a, **kw: process)
    if valid:
        with VideoTimestamps(tmp_path / "virtual.mp4", 10) as timing:
            assert [t.seconds for t in timing] == [0, 0.5]
        assert timing.duration_seconds == pytest.approx(0.6)
    else:
        with pytest.raises(VideoIOError, match="时间戳无效"):
            with VideoTimestamps(tmp_path / "virtual.mp4", 10) as timing:
                list(timing)
    assert stdout.closed
