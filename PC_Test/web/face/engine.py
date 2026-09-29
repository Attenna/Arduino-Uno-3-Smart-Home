"""统一人脸引擎：YOLOv8-face 检测 + 嵌入识别 + 无模型模拟回退。

对外保持别组 smart_home/face_recognition.py 的 API 契约（recognize_from_base64 /
get_status / save_config / reload_model / known_faces …），内部把「检测」与「身份
识别」升级为 yolo_face_detection 项目的真实实现：

    simulation_mode=true  ：随机返回 FACE00x，无模型/无摄像头时前端仍可演示
    simulation_mode=false ：YOLOFaceDetector 检测人脸；若 data/face/embeddings.pkl
                            存在（scripts/enroll_faces.py 生成），再用嵌入比对给出
                            身份（ArcFace ONNX 或零依赖灰度余弦）。
"""
from __future__ import annotations

import base64
import json
import logging
import random
from pathlib import Path

from ..config import (AUTHORIZED_DIR, EMBEDDINGS_PATH, FACE_MODEL_PATH,
                      RECOGNITION_MODEL_PATH, FACE_CONFIG_PATH,
                      load_config)
from ..utils import ConnectionHealth, RequestThrottler

logger = logging.getLogger(__name__)

# 模拟模式默认人脸库（与前端演示数据对应）
_DEFAULT_KNOWN_FACES = {
    "FACE001": "管理员",
    "FACE002": "家庭成员A",
    "FACE003": "家庭成员B",
}


class FaceEngine:
    def __init__(self, config_path: str | Path | None = None,
                 web_cfg: dict | None = None):
        self.config_path = str(config_path or FACE_CONFIG_PATH)
        self.web_cfg = (web_cfg or load_config()).get("face", {})
        self.config = self._load_config()
        self.detector = None
        self.recognizer = None
        self._model_loaded = False
        self.simulation_mode = self.config.get("simulation_mode", True)
        self.throttler = RequestThrottler(
            min_interval=float(self.config.get("recognition_interval", 1.5)))
        self.health = ConnectionHealth("FaceRecognition")
        if not self.simulation_mode:
            self._load_model()

    # ==================== 配置 ====================

    def _default_config(self) -> dict:
        recog = dict(self.web_cfg.get("recognition", {}))
        return {
            "model_path": self.web_cfg.get("model_path", "models/face/yolov8n-face.pt"),
            "model_format": "pt",
            "confidence_threshold": self.web_cfg.get("confidence_threshold", 0.4),
            "iou_threshold": self.web_cfg.get("iou_threshold", 0.45),
            "image_size": 640,
            "device": None,
            "camera_device": 0,
            "camera_width": 640,
            "camera_height": 480,
            "camera_fps": 15,
            "max_faces": self.web_cfg.get("max_faces", 5),
            "recognition_interval": 1.5,
            "embeddings_path": str(EMBEDDINGS_PATH),
            "authorized_dir": str(AUTHORIZED_DIR),
            "recognition": {
                "enabled": recog.get("enabled", True),
                "method": recog.get("method", "simple_grayscale_cosine"),
                "model_path": recog.get("model_path"),
                "similarity_threshold": recog.get("similarity_threshold", 0.5),
                "image_size": recog.get("image_size", 112),
            },
            "simulation_mode": self.web_cfg.get("simulation_mode", True),
            "known_faces": dict(_DEFAULT_KNOWN_FACES),
        }

    def _load_config(self) -> dict:
        path = Path(self.config_path)
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    saved = json.load(f)
                cfg = self._default_config()
                cfg.update(saved)
                return cfg
            except Exception as e:
                logger.warning("人脸配置加载失败: %s，使用默认配置", e)
        return self._default_config()

    def save_config(self, config: dict) -> None:
        path = Path(self.config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        self.config = config

    # ==================== 模型加载 ====================

    def reload_model(self) -> bool:
        self.simulation_mode = self.config.get("simulation_mode", True)
        if not self.simulation_mode:
            return self._load_model()
        self.detector = None
        self.recognizer = None
        self._model_loaded = False
        return False

    def _load_model(self) -> bool:
        """加载 YOLO 检测器 + 可选嵌入识别器；任一不可用则回退模拟。"""
        model_path = self.config.get("model_path", "")
        if not Path(model_path).exists():
            logger.warning("人脸模型不存在: %s，使用模拟模式", model_path)
            self._fallback_simulation()
            return False
        try:
            from .detector import YOLOFaceDetector

            self.detector = YOLOFaceDetector(
                model_path=model_path,
                conf_threshold=float(self.config.get("confidence_threshold", 0.4)),
                iou_threshold=float(self.config.get("iou_threshold", 0.45)),
                image_size=int(self.config.get("image_size", 640)),
                device=self.config.get("device"),
            )
        except ImportError:
            logger.warning("ultralytics 未安装，使用模拟模式。pip install ultralytics")
            self._fallback_simulation()
            return False
        except Exception as e:
            logger.error("YOLO 模型加载失败: %s，使用模拟模式", e)
            self._fallback_simulation()
            return False

        # 识别器可选：embeddings 存在才启用
        recog_cfg = self.config.get("recognition", {})
        if recog_cfg.get("enabled", True):
            # 路径一律以代码常量为准（按当前机器/容器解析）；
            # data/face/face_config.json 可能存着另一台机器的绝对路径（移植/挂载场景）
            embeddings = str(EMBEDDINGS_PATH)
            if Path(embeddings).exists():
                try:
                    from .recognizer import FaceRecognizer

                    self.recognizer = FaceRecognizer(
                        embeddings_path=embeddings,
                        model_path=str(RECOGNITION_MODEL_PATH),
                        method=recog_cfg.get("method", "simple_grayscale_cosine"),
                        similarity_threshold=float(
                            recog_cfg.get("similarity_threshold", 0.5)),
                        image_size=int(recog_cfg.get("image_size", 112)),
                    )
                    logger.info("人脸身份识别已启用: %s（%d 人）",
                                self.recognizer.method,
                                len(self.recognizer.identities))
                except Exception as e:
                    logger.warning("嵌入识别器不可用（仅检测）: %s", e)
                    self.recognizer = None
            else:
                logger.info("未找到 %s，仅做人脸检测；运行 enroll_faces.py 启用身份识别",
                            embeddings)

        self._model_loaded = True
        self.simulation_mode = False
        logger.info("YOLOv8 人脸模型加载成功: %s", model_path)
        return True

    def _fallback_simulation(self) -> None:
        self.detector = None
        self.recognizer = None
        self._model_loaded = False
        self.simulation_mode = True
        self.config["simulation_mode"] = True

    # ==================== 识别入口 ====================

    def recognize_from_base64(self, image_base64: str) -> dict:
        if not self.throttler.can_execute():
            wait = self.throttler.time_until_next()
            return {"detected": False, "face_id": None, "confidence": 0,
                    "faces": [], "mode": "throttled",
                    "message": f"请求过于频繁，请等待 {wait:.1f} 秒"}
        if self.simulation_mode:
            result = self._simulate_recognition()
            if result["detected"]:
                self.health.record_success()
            return result
        try:
            import cv2
            import numpy as np

            raw = image_base64
            if "," in raw:
                raw = raw.split(",", 1)[1]
            img_array = np.frombuffer(base64.b64decode(raw), dtype=np.uint8)
            frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if frame is None:
                return self._empty_result("yolov8", error="图像解码失败")
            return self.recognize_from_frame(frame, _already_throttled=True)
        except Exception as e:
            logger.error("Base64 识别失败: %s", e)
            self.health.record_failure(str(e))
            return self._empty_result("yolov8", error=str(e))

    def recognize_from_frame(self, frame, _already_throttled: bool = False) -> dict:
        if not _already_throttled:
            if not self.throttler.can_execute():
                wait = self.throttler.time_until_next()
                return {"detected": False, "face_id": None, "confidence": 0,
                        "faces": [], "mode": "throttled",
                        "message": f"请求过于频繁，请等待 {wait:.1f} 秒"}
        if self.simulation_mode:
            result = self._simulate_recognition()
            if result["detected"]:
                self.health.record_success()
            return result
        return self._yolov8_recognize(frame)

    def _yolov8_recognize(self, frame) -> dict:
        try:
            import cv2

            detections = self.detector.detect(frame)
            faces: list[dict] = []
            best = None  # (优先授权身份的识别分, 检测置信度, face_info)

            for det in detections:
                x1, y1, x2, y2 = det.xyxy_int()
                info = {
                    "face_id": None,
                    "person_name": None,
                    "confidence": round(det.confidence, 3),
                    "score": None,
                    "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                }
                rank = (-1.0, det.confidence)

                if self.recognizer is not None:
                    h, w = frame.shape[:2]
                    crop = frame[max(y1, 0):min(y2, h), max(x1, 0):min(x2, w)]
                    if crop.size > 0:
                        rec = self.recognizer.recognize(crop)
                        info["score"] = round(rec.score, 3)
                        if rec.authorized:
                            info["face_id"] = rec.identity
                            info["person_name"] = rec.identity
                            rank = (rec.score, det.confidence)

                faces.append(info)
                if best is None or rank > best[0]:
                    best = (rank, info)

            if best is not None:
                self.health.record_success()
                info = best[1]
                mode = "recognition" if self.recognizer is not None else "yolov8"
                return {
                    "detected": True,
                    "face_id": info["face_id"],
                    "person_name": info["person_name"],
                    "confidence": info["confidence"],
                    "faces": faces,
                    "mode": mode,
                }

            return {"detected": False, "face_id": None, "confidence": 0,
                    "faces": [], "mode": "yolov8"}
        except Exception as e:
            logger.error("YOLO 帧识别失败: %s", e)
            self.health.record_failure(str(e))
            return self._empty_result("yolov8", error=str(e))

    def _simulate_recognition(self) -> dict:
        known_faces = self.config.get("known_faces", _DEFAULT_KNOWN_FACES)
        face_ids = list(known_faces)
        if random.random() < 0.7 and face_ids:
            face_id = random.choice(face_ids)
            conf = round(random.uniform(0.75, 0.99), 3)
            return {
                "detected": True,
                "face_id": face_id,
                "person_name": known_faces.get(face_id),
                "confidence": conf,
                "faces": [{
                    "face_id": face_id,
                    "person_name": known_faces.get(face_id),
                    "confidence": conf,
                    "bbox": {"x1": 150, "y1": 80, "x2": 450, "y2": 400},
                }],
                "mode": "simulation",
            }
        return {"detected": False, "face_id": None, "confidence": 0,
                "faces": [], "mode": "simulation"}

    @staticmethod
    def _empty_result(mode: str, error: str | None = None) -> dict:
        result = {"detected": False, "face_id": None, "confidence": 0,
                  "faces": [], "mode": mode}
        if error:
            result["error"] = error
        return result

    # ==================== 状态 / 已知人脸 ====================

    def get_status(self) -> dict:
        recog_cfg = self.config.get("recognition", {})
        status = {
            "model_loaded": self._model_loaded,
            "simulation_mode": self.simulation_mode,
            "mode": "simulation" if self.simulation_mode else (
                "recognition" if self.recognizer is not None else "yolov8"),
            "model_path": self.config.get("model_path", ""),
            "confidence_threshold": self.config.get("confidence_threshold", 0.4),
            "camera_device": self.config.get("camera_device", 0),
            "known_faces": self.config.get("known_faces", {}),
            "recognition": {
                "enabled": bool(recog_cfg.get("enabled", True)),
                "method": (self.recognizer.method if self.recognizer is not None
                           else recog_cfg.get("method")),
                "identities": (len(self.recognizer.identities)
                               if self.recognizer is not None else 0),
            },
        }
        status.update(self.health.get_status())
        return status

    def add_known_face(self, face_id: str, name: str) -> bool:
        known = self.config.setdefault("known_faces", {})
        known[face_id] = name
        self.save_config(self.config)
        return True

    def remove_known_face(self, face_id: str) -> bool:
        known = self.config.get("known_faces", {})
        if face_id in known:
            del known[face_id]
            self.save_config(self.config)
            return True
        return False
