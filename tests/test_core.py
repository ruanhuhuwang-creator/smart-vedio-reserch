from types import SimpleNamespace
import asyncio
import sys

import cv2
import numpy as np
import pytest
import httpx

from backend.config import DetectionConfig
from backend.core.analyzer import VideoAnalyzer
from backend.core.detector import Detection, DetectionError, YOLODetector
from backend.core.video_io import VideoInfo, VideoIOError, VideoReader, VideoWriter, verify_video
from backend.main import app


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "input.mp4"
    info = VideoInfo(path, 12.0, 96, 64, 6)
    with VideoWriter(path, info) as writer:
        for index in range(6):
            writer.write(np.full((64, 96, 3), index * 30, np.uint8))
    return path, info


class FakeDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        return [Detection(0, "person", 0.9, (5, 5, 40, 45))]

    draw = staticmethod(YOLODetector.draw)


def test_read_write_order(clip):
    path, info = clip
    verify_video(path, info, 6)
    with VideoReader(path) as reader:
        means = [float(frame.mean()) for frame in reader]
    assert all(a < b for a, b in zip(means, means[1:]))
    assert not reader.capture.isOpened()


@pytest.mark.parametrize("interval", [1, 2])
def test_analysis(clip, tmp_path, interval):
    path, info = clip
    detector = FakeDetector()
    records, progress = [], []
    output = tmp_path / "output.mp4"
    summary = VideoAnalyzer(detector).analyze(path, output, frame_interval=interval,
                                            on_frame=records.append, on_progress=progress.append)
    verify_video(output, info, 6)
    assert summary.processed_frames == 6
    assert detector.calls == summary.analyzed_frames == 6 // interval
    assert [r.frame_index for r in records] == list(range(6))
    assert records[-1].timestamp_seconds == 5 / 12
    assert progress[-1].processed_frames == 6
    with VideoReader(output) as reader:
        annotated = next(iter(reader))
    assert annotated[5, 20, 1] > 100


def test_failed_analysis_cleans_partial(clip, tmp_path):
    class BrokenDetector(FakeDetector):
        def detect(self, frame):
            raise DetectionError("mock failure")
    output = tmp_path / "failed.mp4"
    with pytest.raises(DetectionError):
        VideoAnalyzer(BrokenDetector()).analyze(clip[0], output)
    assert not output.exists()
    assert not list(tmp_path.glob("*.partial.mp4"))


def test_existing_output_and_same_input_preserved(clip, tmp_path):
    path, _ = clip
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"user data")
    analyzer = VideoAnalyzer(FakeDetector())
    with pytest.raises(FileExistsError):
        analyzer.analyze(path, output)
    assert output.read_bytes() == b"user data"
    with pytest.raises(ValueError):
        analyzer.analyze(path, path)


def test_missing_and_corrupt_input(tmp_path):
    with pytest.raises(VideoIOError, match="不存在"):
        with VideoReader(tmp_path / "missing.mp4"):
            pass
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"invalid video")
    with pytest.raises(VideoIOError):
        with VideoReader(corrupt):
            pass


def test_premature_end_releases(clip):
    with pytest.raises(VideoIOError, match="提前结束"):
        with VideoReader(clip[0]) as reader:
            reader.info = VideoInfo(clip[0], 12, 96, 64, 100)
            list(reader)
    assert not reader.capture.isOpened()


def test_invalid_frame_and_odd_dimensions(tmp_path):
    info = VideoInfo(tmp_path / "x.mp4", 12, 96, 64, 1)
    with VideoWriter(info.path, info) as writer:
        with pytest.raises(VideoIOError, match="原始尺寸"):
            writer.write(np.zeros((10, 10, 3), np.uint8))
    with pytest.raises(VideoIOError, match="偶数"):
        with VideoWriter(tmp_path / "odd.mp4", VideoInfo(info.path, 12, 95, 64, 1)):
            pass


def test_encoder_failure(monkeypatch, tmp_path):
    state = {"released": False}
    writer = SimpleNamespace(isOpened=lambda: False,
                             release=lambda: state.update(released=True))
    monkeypatch.setattr(cv2, "VideoWriter", lambda *args: writer)
    with pytest.raises(VideoIOError, match="编码器"):
        with VideoWriter(tmp_path / "fail.mp4", VideoInfo(tmp_path, 12, 96, 64, 1)):
            pass
    assert state["released"]


def test_config_and_health():
    with pytest.raises(ValueError):
        DetectionConfig(confidence=2)
    with pytest.raises(ValueError):
        DetectionConfig(device="invalid")
    async def request_health():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/health")
    response = asyncio.run(request_health())
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_detector_mapping_and_oom():
    class Data:
        def detach(self): return self
        def cpu(self): return self
        def tolist(self): return [[1, 2, 30, 40, 0.8, 0]]
    detector = YOLODetector.__new__(YOLODetector)
    detector.config, detector.device = DetectionConfig(), "cpu"
    calls = []
    detector.model = SimpleNamespace(predict=lambda *a, **kw: (
        calls.append(kw) or [SimpleNamespace(boxes=SimpleNamespace(data=Data()), names={0: "person"})]))
    result = detector.detect(np.zeros((64, 96, 3), np.uint8))
    assert result[0] == Detection(0, "person", 0.8, (1., 2., 30., 40.))
    assert calls[0]["imgsz"] == 640
    assert calls[0]["conf"] == 0.35
    def oom(*a, **kw): raise RuntimeError("CUDA out of memory")
    detector.model.predict = oom
    with pytest.raises(DetectionError, match="显存不足"):
        detector.detect(np.zeros((64, 96, 3), np.uint8))


@pytest.mark.parametrize("available,requested,expected", [
    (False, "auto", "cpu"), (True, "auto", "cuda:0"), (True, "cpu", "cpu")])
def test_device_selection_and_single_load(monkeypatch, tmp_path, available, requested, expected):
    loads = []
    model = SimpleNamespace(to=lambda device: None, predict=lambda *a, **kw: [SimpleNamespace(boxes=None)])
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: available)))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=lambda path: loads.append(path) or model))
    detector = YOLODetector(DetectionConfig(weights=tmp_path / "model.pt", device=requested))
    for _ in range(3):
        assert detector.detect(np.zeros((64, 96, 3), np.uint8)) == []
    assert detector.device == expected
    assert len(loads) == 1


def test_explicit_cuda_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=lambda path: None))
    with pytest.raises(DetectionError, match="无法使用 CUDA"):
        YOLODetector(DetectionConfig(device="cuda"))
