"""YOLOv8-face 人脸检测器（合并自 yolo_face_detection/src/detector.py）。

ultralytics 采用懒加载：未安装时由 FaceEngine 捕获异常并回退模拟模式，
不影响 web 服务其它功能。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class FaceDetection:
    bbox: tuple[float, float, float, float]
    confidence: float
    class_id: int
    label: str = "face"

    def xyxy_int(self) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = self.bbox
        return int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))

    def to_dict(self) -> dict[str, Any]:
        return {
            "bbox": [round(value, 2) for value in self.bbox],
            "confidence": round(self.confidence, 4),
            "class_id": self.class_id,
            "label": self.label,
        }


class YOLOFaceDetector:
    """可复用的图像/帧人脸检测 API。"""

    def __init__(
        self,
        model_path: str | Path,
        conf_threshold: float = 0.35,
        iou_threshold: float = 0.45,
        image_size: int = 640,
        device: str | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Detection model not found: {self.model_path}. "
                "Place yolov8n-face.pt under PC_Test/models/face/ or update config."
            )

        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.image_size = image_size
        self.device = device
        from ultralytics import YOLO  # 懒加载
        self.model = YOLO(str(self.model_path))

    def detect(self, image: np.ndarray) -> list[FaceDetection]:
        if image is None or image.size == 0:
            return []

        results = self.model.predict(
            source=image,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            imgsz=self.image_size,
            device=self.device,
            verbose=False,
        )
        if not results:
            return []

        boxes = results[0].boxes
        if boxes is None:
            return []

        detections: list[FaceDetection] = []
        names = results[0].names or {}
        for box in boxes:
            bbox_values = box.xyxy[0].detach().cpu().numpy().astype(float).tolist()
            confidence = float(box.conf[0].detach().cpu().item())
            class_id = int(box.cls[0].detach().cpu().item()) if box.cls is not None else 0
            label = str(names.get(class_id, "face"))
            detections.append(
                FaceDetection(
                    bbox=tuple(bbox_values),
                    confidence=confidence,
                    class_id=class_id,
                    label=label,
                )
            )
        return detections
