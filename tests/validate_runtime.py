"""Opt-in real-model validation: python -m tests.validate_runtime.

Downloads the official Ultralytics bus example, generates a short clip,
checks CUDA/CPU inference and the CLI, and starts a real HTTP server.
Not part of offline pytest tests.
"""
from dataclasses import asdict
from http.client import IncompleteRead
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

import cv2
import numpy as np
import torch

from backend.config import DetectionConfig, PROJECT_ROOT
from backend.core.detector import YOLODetector
from backend.core.video_io import VideoInfo, VideoReader, VideoWriter, verify_video


def main():
    os.environ["PYTHONUTF8"] = "1"
    output_dir = PROJECT_ROOT / "data" / "outputs" / "validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "bus.jpg"
    if not image_path.exists():
        image_url = "https://raw.githubusercontent.com/ultralytics/ultralytics/main/ultralytics/assets/bus.jpg"
        for attempt in range(3):
            try:
                with urlopen(f"{image_url}?attempt={attempt}", timeout=30) as response:
                    image_path.write_bytes(response.read())
                break
            except (OSError, IncompleteRead):
                if attempt == 2:
                    raise
                time.sleep(1)
    # imdecode/tofile also support Unicode Windows paths on older OpenCV builds.
    image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Could not decode official example")
    report = {"python": sys.version, "torch": torch.__version__, "cuda_runtime": torch.version.cuda,
              "cuda_available": torch.cuda.is_available()}
    if torch.cuda.is_available():
        report["gpu"] = torch.cuda.get_device_name(0)
        report["gpu_memory_bytes"] = torch.cuda.get_device_properties(0).total_memory
        report["gpu_compute_capability"] = torch.cuda.get_device_capability(0)
        report["torch_cuda_architectures"] = torch.cuda.get_arch_list()
        torch.cuda.reset_peak_memory_stats()
    detector = YOLODetector()
    detections = detector.detect(image)
    assert any(d.class_name == "person" for d in detections), detections
    assert any(d.class_name == "bus" for d in detections), detections
    report["device"] = detector.device
    report["image_detections"] = [asdict(d) for d in detections]
    success, encoded = cv2.imencode(".jpg", detector.draw(image, detections))
    assert success
    encoded.tofile(output_dir / "bus_detected.jpg")
    cpu_detector = YOLODetector(DetectionConfig(device="cpu"))
    report["cpu_detection_count"] = len(cpu_detector.detect(image))
    assert report["cpu_detection_count"] > 0
    video = output_dir / "example_clip.mp4"
    info = VideoInfo(video, 12.0, 640, 480, 24)
    with VideoWriter(video, info) as writer:
        for index in range(24):
            frame = cv2.resize(image, (640, 480))
            cv2.putText(frame, str(index), (500, 460), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
            writer.write(frame)
    verify_video(video, info, 24)
    # Use unique output so repeated validation preserves earlier results.
    output_video = output_dir / f"detected_{time.time_ns()}.mp4"
    cli = subprocess.run([sys.executable, "-m", "backend.cli", str(video), str(output_video)],
                         cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (output_dir / "cli.log").write_text(cli.stdout + cli.stderr, encoding="utf-8")
    assert cli.returncode == 0, cli.stdout + cli.stderr
    verify_video(output_video, info, 24)
    with VideoReader(video) as reader:
        original = next(iter(reader))
    with VideoReader(output_video) as reader:
        annotated = next(iter(reader))
    assert np.abs(original.astype(float) - annotated.astype(float)).mean() > 1
    success, encoded = cv2.imencode(".jpg", annotated)
    assert success
    encoded.tofile(output_dir / "video_first_frame.jpg")
    report["video"] = {"input": str(video), "output": str(output_video), "frames": 24,
                       "fps": 12, "size": [640, 480], "source": "generated from official bus image, not real surveillance"}
    bad = subprocess.run([sys.executable, "-m", "backend.cli", str(output_dir / "missing.mp4"),
                          str(output_dir / "unused.mp4")], cwd=PROJECT_ROOT, capture_output=True)
    assert bad.returncode == 1
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port)],
                              cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                    report["health"] = json.load(response)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Health endpoint did not become ready")
        assert report["health"]["status"] == "ok"
    finally:
        server.terminate()
        server.wait(timeout=10)
    if torch.cuda.is_available():
        report["peak_gpu_allocated_bytes_image_test"] = torch.cuda.max_memory_allocated()
    (output_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
