# 索引命令行入口：analyze 建索引，search 查已存结果，rebuild-events 重新合并时间段。
# 只有需要新检测时才调用 YOLO，普通搜索不重新分析视频。

"""Index/search command line, without changing the phase-one export CLI."""
import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path
import sys

from backend.config import DEFAULT_DATABASE, DetectionConfig, IndexConfig
from backend.database.repository import IndexRepository
from backend.services.indexing import IndexingService
from backend.services.search import SearchService


def parser():
    command = argparse.ArgumentParser(description="SmartVision 视频索引与类别检索")
    commands = command.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="默认 2 FPS 分析入库，不生成标注视频")
    analyze.add_argument("input", type=Path)
    mode = analyze.add_mutually_exclusive_group()
    mode.add_argument("--analysis-fps", type=float, default=IndexConfig().analysis_fps)
    mode.add_argument("--every-frame", action="store_true", help="逐帧分析入库")
    analyze.add_argument("--imgsz", type=int, default=DetectionConfig().image_size)
    analyze.add_argument("--confidence", type=float, default=DetectionConfig().confidence)
    analyze.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    analyze.add_argument("--force", action="store_true", help="原子替换旧索引，避免重复记录")
    search = commands.add_parser("search", help="查询已有事件，不调用模型")
    search.add_argument("category", help="COCO 类别名，例如 person 或 car")
    search.add_argument("--video-id", type=int)
    search.add_argument("--json", action="store_true")
    rebuild = commands.add_parser("rebuild-events", help="从原始检测记录重新合并，不调用模型")
    rebuild.add_argument("--video-id", type=int, required=True)
    recover = commands.add_parser("recover", help="确认旧进程已停止后恢复中断任务状态")
    recover.add_argument("--video-id", type=int, required=True)
    for child in [analyze, rebuild]:
        child.add_argument("--merge-gap", type=float, default=IndexConfig().merge_gap)
        child.add_argument("--min-samples", type=int, default=IndexConfig().min_samples)
    for child in [analyze, search, rebuild, recover]:
        child.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    return command


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if args.command != "analyze" and not args.db.is_file():
            raise FileNotFoundError(f"数据库不存在: {args.db}；请先分析视频或检查 --db 路径")
        repository = IndexRepository(args.db)
        if args.command == "search":
            rows = SearchService(repository).search(args.category, args.video_id)
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            elif rows:
                for row in rows:
                    print(f"视频 {row['video_id']} | {row['video_name']} | {row['class_name']} | "
                          f"{row['start_time']:.3f}s - {row['end_time']:.3f}s | "
                          f"长度 {row['duration']:.3f}s | {row['sample_count']} 次采样支持")
            else:
                print("未找到符合条件的事件（不代表视频中绝对不存在该目标）")
            return 0
        if args.command == "recover":
            repository.recover(args.video_id)
            print(f"视频 {args.video_id} 状态已恢复，可重新分析")
            return 0
        service = IndexingService(repository)
        if args.command == "rebuild-events":
            service.rebuild_events(args.video_id, args.merge_gap, args.min_samples)
            print(f"视频 {args.video_id} 事件已重新合并，原始检测记录保留")
            return 0
        detection = DetectionConfig(confidence=args.confidence, image_size=args.imgsz, device=args.device)
        indexing = IndexConfig(analysis_fps=None if args.every_frame else args.analysis_fps,
                               merge_gap=args.merge_gap, min_samples=args.min_samples)
        last_update = -1.0

        def on_start(info):
            print(f"视频: {info.path.name} | FPS: {info.fps:.3f} | 分辨率: {info.width}x{info.height} | "
                  f"分析: {'逐帧' if indexing.analysis_fps is None else str(indexing.analysis_fps) + ' FPS'}", flush=True)

        def on_progress(progress):
            nonlocal last_update
            if progress.elapsed_seconds - last_update >= 1 or progress.processed_frames == progress.total_frames:
                print(f"进度: {progress.processed_frames}/{progress.total_frames or '未知'} | "
                      f"{progress.elapsed_seconds:.2f}s", flush=True)
                last_update = progress.elapsed_seconds

        summary = service.analyze(args.input, detection=detection, indexing=indexing, force=args.force,
                                  on_start=on_start, on_progress=on_progress,
                                  on_device=lambda device: print(f"推理设备: {device}", flush=True))
        print(f"{'复用已有索引，未重新推理' if summary.reused else '分析入库完成'} | "
              f"视频ID: {summary.video_id} | 采样帧: {summary.sampled_frames} | "
              f"原始检测: {summary.detection_count} | 耗时: {summary.elapsed_seconds:.2f}s")
        print(f"数据库: {repository.path}")
        return 0
    except KeyboardInterrupt:
        print("索引分析已取消，本次事务已回滚", file=sys.stderr)
        return 130
    except Exception as exc:
        logging.error("操作失败: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
