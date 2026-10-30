# 单帧检测工具：输入 OpenCV 图像，输出 Detection 列表；不负责视频循环和数据库。
# OpenCV 图像是 BGR 通道顺序；xyxy 是左上角(x1,y1)、右下角(x2,y2)，单位为像素。

from dataclasses import dataclass
import logging
import sys

import cv2
import numpy as np

from backend.config import DetectionConfig

logger = logging.getLogger(__name__)


class DetectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    xyxy: tuple[float, float, float, float]


class YOLODetector:
    def __init__(self, config: DetectionConfig = DetectionConfig()):
        import torch
        from ultralytics import YOLO

        # 同一个检测器对象重复处理很多帧，模型只在初始化时加载一次。
        self.config = config
        if getattr(sys, "frozen", False) and not config.weights.is_file():
            raise DetectionError("应用自带的 yolo26n.pt 权重缺失，请重新完整解压分发包")
        if config.device == "cuda" and not torch.cuda.is_available():
            raise DetectionError("指定了 CUDA，但 PyTorch 无法使用 CUDA；请检查驱动与 CUDA 版 PyTorch")
        self.device = "cuda:0" if config.device != "cpu" and torch.cuda.is_available() else "cpu"
        logger.info("PyTorch %s, CUDA runtime %s, available=%s, selected=%s",
                    getattr(torch, "__version__", "unknown"), getattr(getattr(torch, "version", None), "cuda", None),
                    torch.cuda.is_available(), self.device)
        if config.device == "auto" and self.device == "cpu":
            logger.warning("CUDA 不可用（无兼容 GPU、驱动不可用或设备被禁用），自动使用 CPU 推理")
        config.weights.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Ultralytics downloads official weights to this path only when missing.
            self.model = YOLO(str(config.weights))
            self.model.to(self.device)
        except Exception as exc:
            if "out of memory" in str(exc).lower():
                raise DetectionError("加载模型时 GPU 显存不足；关闭占用显存的程序或使用 --device cpu") from exc
            raise DetectionError(f"YOLO26n 加载失败；检查网络、权重路径和 PyTorch 环境: {exc}") from exc
        logger.info("YOLO 模型已加载，设备 %s，权重 %s", self.device, config.weights)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3 or frame.size == 0:
            raise ValueError("检测输入必须为非空 uint8 BGR 图像")
        try:
            result = self.model.predict(frame, conf=self.config.confidence,
                                        imgsz=self.config.image_size, device=self.device,
                                        batch=1, verbose=False)[0]
            if result.boxes is None:
                return []
            # 每行依次是 x1,y1,x2,y2,置信度,类别编号；先从 GPU 取回普通 Python 数据。
            rows = result.boxes.data.detach().cpu().tolist()
            return [Detection(int(row[5]), result.names[int(row[5])], float(row[4]),
                              tuple(float(x) for x in row[:4])) for row in rows]
        except Exception as exc:
            if "out of memory" in str(exc).lower():
                raise DetectionError("GPU 显存不足；关闭占用显存的程序，降低 image_size 或使用 --device cpu") from exc
            raise DetectionError(f"YOLO 推理失败 ({self.device}): {exc}") from exc

    @staticmethod
    def draw(frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
        # 复制后再画，调用者持有的原始帧不会被就地修改。
        annotated = frame.copy()
        h, w = frame.shape[:2]
        for item in detections:
            x1, y1, x2, y2 = [int(x) for x in item.xyxy]
            x1, x2 = max(0, min(w - 1, x1)), max(0, min(w - 1, x2))
            y1, y2 = max(0, min(h - 1, y1)), max(0, min(h - 1, y2))
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 220, 0), 2)
            cv2.putText(annotated, f"{item.class_name} {item.confidence:.2f}",
                        (x1, max(15, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 0), 1)
        return annotated
