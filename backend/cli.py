"""Run from the project root: python -m backend.cli INPUT OUTPUT."""
import argparse
import logging
from pathlib import Path
import sys
from time import perf_counter

from backend.config import DetectionConfig
from backend.core.analyzer import VideoAnalyzer, Progress
from backend.core.detector import YOLODetector
from backend.core.video_io import VideoReader


def main(argv: list[str] | None = None) -> int:
    defaults = DetectionConfig()
    parser = argparse.ArgumentParser(description="SmartVision 视频目标检测")
    parser.add_argument("input", type=Path, help="输入视频路径")
    parser.add_argument("output", type=Path, help="输出 MP4 路径（不得已存在）")
    parser.add_argument("--confidence", type=float, default=defaults.confidence)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default=defaults.device)
    parser.add_argument("--imgsz", type=int, default=defaults.image_size)
    args = parser.parse_args(argv)
    started = perf_counter()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        config = DetectionConfig(confidence=args.confidence, device=args.device, image_size=args.imgsz)
        if args.input.resolve() == args.output.resolve():
            raise ValueError("输入和输出路径不能相同")
        if args.output.exists():
            raise FileExistsError(f"输出已存在: {args.output}")
        if args.output.suffix.lower() != ".mp4":
            raise ValueError("输出文件必须为 .mp4")
        # Fail for invalid input before loading/downloading the model.
        with VideoReader(args.input) as reader:
            info = reader.info
            duration = f"{info.duration_seconds:.2f}s" if info.total_frames else "未知"
            print(f"视频: {info.path.name} | 时长: {duration} | "
                  f"FPS: {info.fps:.3f} | 分辨率: {info.width}x{info.height} | 帧数: {info.total_frames}", flush=True)
        detector = YOLODetector(config)
        print(f"推理设备: {detector.device}", flush=True)
        last_update = -1.0

        def report(progress: Progress):
            nonlocal last_update
            if progress.elapsed_seconds - last_update >= 1 or progress.processed_frames == progress.total_frames:
                total = str(progress.total_frames) if progress.total_frames else "未知"
                percentage = f" ({100 * progress.processed_frames / progress.total_frames:.1f}%)" if progress.total_frames else ""
                print(f"进度: {progress.processed_frames}/{total}{percentage} | {progress.elapsed_seconds:.1f}s", flush=True)
                last_update = progress.elapsed_seconds

        summary = VideoAnalyzer(detector).analyze(args.input, args.output, on_progress=report)
        print(f"完成: {summary.processed_frames} 帧，{summary.detection_count} 个检测结果 | "
              f"总耗时: {perf_counter() - started:.2f}s | "
              f"分析及输出验证: {summary.elapsed_seconds:.2f}s | 推理: {summary.inference_seconds:.2f}s")
        print(f"输出: {summary.output_path}")
        return 0
    except KeyboardInterrupt:
        print("处理已取消，未完成的临时输出已清理", file=sys.stderr)
        return 130
    except Exception as exc:
        logging.error("处理失败: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
