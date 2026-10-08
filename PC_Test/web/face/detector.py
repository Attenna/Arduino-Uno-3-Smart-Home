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
    # YOLOv8-face 的五点顺序：左眼、右眼、鼻尖、左嘴角、右嘴角。
    # 某些只输出人脸框的权重没有关键点，此时为 None，由上层退回普通裁剪。
    landmarks: tuple[tuple[float, float], ...] | None = None

    def xyxy_int(self) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = self.bbox
        return int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))

    def to_dict(self) -> dict[str, Any]:
        result = {
            "bbox": [round(value, 2) for value in self.bbox],
            "confidence": round(self.confidence, 4),
            "class_id": self.class_id,
            "label": self.label,
        }
        if self.landmarks is not None:
            result["landmarks"] = [
                [round(x, 2), round(y, 2)] for x, y in self.landmarks
            ]
        return result


def extract_five_landmarks(result: Any, index: int) -> tuple[tuple[float, float], ...] | None:
    """从 Ultralytics Result 中安全提取一张脸的五点坐标。

    YOLOv8-face 权重并不完全统一：带关键点的模型通过 result.keypoints.xy
    暴露 Nx5x2；纯检测权重只有 boxes。后者返回 None，调用方继续走兼容裁剪。
    """
    keypoints = getattr(result, "keypoints", None)
    xy = getattr(keypoints, "xy", None)
    if xy is None:
        return None
    try:
        if hasattr(xy, "detach"):
            xy = xy.detach()
        if hasattr(xy, "cpu"):
            xy = xy.cpu()
        points = np.asarray(xy, dtype=np.float32)[index, :5, :2]
    except (IndexError, TypeError, ValueError):
        return None
    if points.shape != (5, 2) or not np.isfinite(points).all():
        return None
    # 全零是 Ultralytics 对不可见关键点的常见占位，不能拿来估仿射矩阵。
    if np.allclose(points, 0.0) or np.any(np.all(np.isclose(points, 0.0), axis=1)):
        return None
    return tuple((float(x), float(y)) for x, y in points)


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

        result = results[0]
        boxes = result.boxes
        if boxes is None:
            return []

        detections: list[FaceDetection] = []
        names = result.names or {}
        for index, box in enumerate(boxes):
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
                    landmarks=extract_five_landmarks(result, index),
                )
            )
        return detections
