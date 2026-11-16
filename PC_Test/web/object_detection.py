"""ONNX 物体检测。只消费共享摄像头快照，不直接打开摄像头。"""
import ast
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import cv2
import numpy as np


class ObjectDetector:
    def __init__(self, model_path):
        import onnxruntime as ort
        self.lock = threading.Lock()
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        meta = self.session.get_modelmeta().custom_metadata_map
        self.names = ast.literal_eval(meta.get("names", "{}"))
        self.input = self.session.get_inputs()[0]
        shape = self.input.shape
        if len(shape) != 4 or shape[0] != 1 or shape[1] != 3 or not all(isinstance(v, int) for v in shape[2:]):
            raise ValueError("需要固定 batch=1、NCHW 三通道模型")
        self.height, self.width = shape[2:]
        if not self.names or self.session.get_outputs()[0].shape[1] != 4 + len(self.names):
            raise ValueError("需要 YOLO 原始输出 [1, 4+类别数, 候选数]")
        self.sha256 = hashlib.sha256(Path(model_path).read_bytes()).hexdigest()

    def info(self):
        return {"loaded": True, "classes": self.names, "input_size": [self.width, self.height],
                "sha256": self.sha256, "provider": self.session.get_providers()[0]}

    def detect(self, jpeg):
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("无效图像")
        h, w = image.shape[:2]
        scale = min(self.width / w, self.height / h)
        nw, nh = round(w * scale), round(h * scale)
        left, top = (self.width - nw) // 2, (self.height - nh) // 2
        canvas = np.full((self.height, self.width, 3), 114, dtype=np.uint8)
        canvas[top:top+nh, left:left+nw] = cv2.resize(image, (nw, nh))
        tensor = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255
        started = time.monotonic()
        with self.lock:
            rows = self.session.run(None, {self.input.name: tensor})[0][0].T
        boxes, scores, classes = [], [], []
        for row in rows:
            cls = int(np.argmax(row[4:]))
            score = float(row[4+cls])
            if not np.isfinite(row).all() or score < 0.4:
                continue
            cx, cy, bw, bh = row[:4]
            x1 = float(np.clip((cx-bw/2-left)/scale, 0, w))
            y1 = float(np.clip((cy-bh/2-top)/scale, 0, h))
            x2 = float(np.clip((cx+bw/2-left)/scale, 0, w))
            y2 = float(np.clip((cy+bh/2-top)/scale, 0, h))
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append([x1, y1, x2-x1, y2-y1]); scores.append(score); classes.append(cls)
        detections = []
        for cls in sorted(set(classes)):
            ids = [i for i, c in enumerate(classes) if c == cls]
            kept = cv2.dnn.NMSBoxes([boxes[i] for i in ids], [scores[i] for i in ids], 0.4, 0.45)
            for k in np.asarray(kept).reshape(-1):
                i = ids[int(k)]
                x, y, bw, bh = boxes[i]
                detections.append({"class_id": cls, "label": self.names[cls], "confidence": scores[i],
                                   "box": [round(x, 1), round(y, 1), round(x+bw, 1), round(y+bh, 1)]})
        return {"time": datetime.now(timezone.utc).isoformat(), "width": w, "height": h,
                "inference_ms": round((time.monotonic()-started)*1000, 1), "detections": detections,
                "model_sha256": self.sha256}
