"""OpenCV 摄像头封装（合并自 yolo_face_detection/src/camera.py）。"""
from __future__ import annotations

import cv2


class CameraStream:
    def __init__(self, index: int = 0, width: int | None = None,
                 height: int | None = None):
        self.index = index
        self.width = width
        self.height = height
        self.capture: cv2.VideoCapture | None = None

    def open(self) -> None:
        self.capture = cv2.VideoCapture(self.index)
        if self.width:
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if not self.capture.isOpened():
            raise RuntimeError(f"Cannot open camera index {self.index}")

    def read(self):
        if self.capture is None:
            self.open()
        ok, frame = self.capture.read()
        if not ok:
            raise RuntimeError("Cannot read frame from camera")
        return frame

    def release(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
