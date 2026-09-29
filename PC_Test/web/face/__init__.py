"""人脸识别子包：YOLOv8-face 检测 + 嵌入识别（ArcFace ONNX / 灰度余弦）。"""
from .engine import FaceEngine

__all__ = ["FaceEngine"]
