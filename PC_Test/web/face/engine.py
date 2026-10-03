"""统一人脸引擎：YOLOv8-face 检测 + 嵌入识别 + 无模型模拟回退。

对外保持别组 smart_home/face_recognition.py 的 API 契约（recognize_from_base64 /
get_status / save_config / reload_model / known_faces …），内部把「检测」与「身份
识别」升级为 yolo_face_detection 项目的真实实现：

    simulation_mode=true  ：随机返回 FACE00x，无模型/无摄像头时前端仍可演示
    simulation_mode=false ：YOLOFaceDetector 检测人脸；若 data/face/embeddings.pkl
                            存在（scripts/enroll_faces.py 生成），再用嵌入比对给出
                            身份（ArcFace ONNX 或零依赖灰度余弦）。

除了离线脚本，门禁页也能直接录入：``enroll_faces()`` 把浏览器截来的帧里检出的
人脸存进 data/face/authorized/<姓名>/，只重算这一个身份的均值原型并热加载识别器，
不必停服务重跑 enroll_faces.py。
"""
from __future__ import annotations

import base64
import json
import logging
import random
import re
import shutil
import threading
import time
from pathlib import Path

from ..config import (AUTHORIZED_DIR, EMBEDDINGS_PATH, FACE_MODEL_PATH,
                      RECOGNITION_MODEL_PATH, FACE_CONFIG_PATH,
                      load_config)
from ..utils import ConnectionHealth, RequestThrottler, safe_base64_decode

logger = logging.getLogger(__name__)

# 模拟模式默认人脸库（与前端演示数据对应）
_DEFAULT_KNOWN_FACES = {
    "FACE001": "管理员",
    "FACE002": "家庭成员A",
    "FACE003": "家庭成员B",
}

# 一次录入请求最多收几张帧（浏览器端本来就只截几帧，这里只是兜住恶意/误操作）
MAX_ENROLL_FRAMES = 12
# 检出人脸的最小边长（像素）：再小的帧嵌入质量差，宁缺勿滥
MIN_FACE_SIDE = 56
# 每个身份最多参与原型计算的注册照张数（取文件名最新的 N 张）
MAX_IDENTITY_IMAGES = 20
# 单次录入的图像体积上限（MB）
ENROLL_IMAGE_MAX_MB = 4.0


def identity_name(name: str) -> str:
    """人员姓名 → 人脸库目录名，也就是识别用的 face_id。

    目录名会被拼进路径，所以要挡掉分隔符与 ``..``；姓名本身可以是中文，
    清洗后原样回显在门禁页上，用户看到的就是数据库里存的凭证标识。
    """
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", str(name or "").strip()).strip("._")
    if not cleaned:
        raise ValueError("姓名不能为空或只含标点符号")
    return cleaned[:32]



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
        self._enroll_lock = threading.Lock()
        self._warmup_done = False
        self._warmup_started = False
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

    def warmup(self) -> bool:
        """空跑一次检测 + 提特征，把「首次推理」的代价付在启动阶段。

        ultralytics/onnxruntime 都是第一次前向才做算子选择与图构建：派上实测
        模型加载后首帧检测 3.8 秒（稳态 0.25 秒），不预热的话服务刚起来时站到
        门口的第一个人要多等约 4 秒。与识别/录入共用同一把锁，不会插队。
        """
        if self.simulation_mode or self.detector is None:
            return False
        import numpy as np

        size = (int(self.config.get("camera_height") or 480),
                int(self.config.get("camera_width") or 640))
        blank = np.zeros((*size, 3), dtype=np.uint8)
        with self._enroll_lock:
            try:
                t0 = time.perf_counter()
                self.detector.detect(blank)
                if self.recognizer is not None:
                    self.recognizer.recognize(blank[:64, :64])
                logger.info("[人脸预热] 完成，耗时 %.0fms",
                            (time.perf_counter() - t0) * 1000.0)
            except Exception as e:                        # noqa: BLE001
                # 预热失败只是首帧仍然慢，不能把服务带倒
                logger.warning("[人脸预热] 失败: %s", e)
                return False
        self._warmup_done = True
        return True

    def start_warmup(self) -> bool:
        """后台预热：/api/ready 不该为了预热多等几秒。"""
        if (self._warmup_started or self._warmup_done
                or self.simulation_mode or self.detector is None):
            return False
        self._warmup_started = True
        threading.Thread(target=self.warmup, name="face-warmup",
                         daemon=True).start()
        return True

    # ==================== 识别入口 ====================

    def _throttled_result(self) -> dict:
        wait = self.throttler.time_until_next()
        return {"detected": False, "face_id": None, "confidence": 0,
                "faces": [], "mode": "throttled",
                "message": f"请求过于频繁，请等待 {wait:.1f} 秒"}

    def _decode_frame(self, blob: bytes):
        import cv2
        import numpy as np

        return cv2.imdecode(np.frombuffer(blob, dtype=np.uint8), cv2.IMREAD_COLOR)

    def _recognize_blob(self, blob: bytes, min_face_px: int = 0) -> dict:
        """解码 + 识别一段 JPEG 字节。调用方负责节流与锁。"""
        if self.simulation_mode:
            result = self._simulate_recognition()
            if result["detected"]:
                self.health.record_success()
            return result
        try:
            frame = self._decode_frame(blob)
            if frame is None:
                return self._empty_result("yolov8", error="图像解码失败")
            return self._yolov8_recognize(frame, min_face_px=min_face_px)
        except Exception as e:
            logger.error("JPEG 识别失败: %s", e)
            self.health.record_failure(str(e))
            return self._empty_result("yolov8", error=str(e))

    def recognize_from_base64(self, image_base64: str) -> dict:
        if not self.throttler.can_execute():
            return self._throttled_result()
        raw = image_base64
        # data URI 前缀只可能在第一个逗号前（base64 字母表里没有逗号），
        # partition 一遍就够，不必对整个几百 KB 的字符串做子串扫描
        _prefix, sep, payload = raw.partition(",")
        if sep:
            raw = payload
        try:
            return self._recognize_blob(base64.b64decode(raw))
        except Exception as e:
            logger.error("Base64 识别失败: %s", e)
            self.health.record_failure(str(e))
            return self._empty_result("yolov8", error=str(e))

    def recognize_from_frame(self, frame, _already_throttled: bool = False) -> dict:
        if not _already_throttled:
            if not self.throttler.can_execute():
                return self._throttled_result()
        if self.simulation_mode:
            result = self._simulate_recognition()
            if result["detected"]:
                self.health.record_success()
            return result
        return self._yolov8_recognize(frame)

    def _embed_targets(self, detections: list, min_face_px: int) -> set:
        """挑出值得提特征的脸：够近的、按面积从大到小最多 max_faces 张。

        提特征是按人脸张数线性叠加的（派上实测每张约 370ms），而「太远不参与开门」
        和「同框人数上限」这两条本来就有配置，只是过去要先算完才判定、上限没生效。
        返回选中项的 id 集合；检出框本身不受影响，前端照样能画全部脸。
        """
        cap = int(self.config.get("max_faces", 5) or 0)
        scored = []
        for det in detections:
            x1, y1, x2, y2 = det.xyxy_int()
            if min(x2 - x1, y2 - y1) < min_face_px:
                continue
            scored.append(((x2 - x1) * (y2 - y1), id(det)))
        scored.sort(key=lambda item: item[0], reverse=True)
        if cap > 0:
            scored = scored[:cap]
        return {identity for _area, identity in scored}

    def _yolov8_recognize(self, frame, min_face_px: int = 0) -> dict:
        try:
            height, width = frame.shape[:2]
            t0 = time.perf_counter()
            detections = self.detector.detect(frame)
            detect_ms = (time.perf_counter() - t0) * 1000.0

            targets = (self._embed_targets(detections, min_face_px)
                       if self.recognizer is not None else set())
            faces: list[dict] = []
            best = None  # (优先授权身份的识别分, 检测置信度, face_info)
            embed_ms = 0.0

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

                if id(det) in targets:
                    crop = frame[max(y1, 0):min(y2, height), max(x1, 0):min(x2, width)]
                    if crop.size > 0:
                        t1 = time.perf_counter()
                        rec = self.recognizer.recognize(crop)
                        embed_ms += (time.perf_counter() - t1) * 1000.0
                        info["score"] = round(rec.score, 3)
                        if rec.authorized:
                            info["face_id"] = rec.identity
                            info["person_name"] = rec.identity
                            rank = (rec.score, det.confidence)

                faces.append(info)
                if best is None or rank > best[0]:
                    best = (rank, info)

            logger.debug("[人脸耗时] 检测 %.0fms + 识别 %.0fms（%d/%d 张脸，min=%dpx）",
                         detect_ms, embed_ms, len(targets), len(detections),
                         min_face_px)

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

    def has_identity(self, name: str) -> bool:
        """人脸库里到底有没有这个身份 —— 名单查不到人时要区分「没录过」和「录过没进名单」。"""
        if not name:
            return False
        if self.recognizer is not None and any(
                str(i.get("name")) == name
                for i in (self.recognizer.identities or [])):
            return True
        try:
            return (AUTHORIZED_DIR / identity_name(name)).is_dir()
        except ValueError:
            return False

    def identity_count(self) -> int:
        return (len(self.recognizer.identities or [])
                if self.recognizer is not None else 0)

    def library_identities(self) -> list[str]:
        """人脸目录里到底有哪些身份（诊断孤儿用：认得出但名单里没有的人）。"""
        if not AUTHORIZED_DIR.is_dir():
            return []
        return sorted(p.name for p in AUTHORIZED_DIR.iterdir() if p.is_dir())

    def recognize_jpeg(self, blob: bytes, min_face_px: int = 0) -> dict:
        """识别一整帧 JPEG（门口识别哨兵用）。

        与录入共用同一把锁：两个线程同时进 ultralytics 推理没有保护，而且录脸
        本来就该独占摄像头（人站在门口摆姿势，此时不需要刷脸开门）。
        """
        with self._enroll_lock:
            if not self.throttler.can_execute():
                return self._throttled_result()
            return self._recognize_blob(blob, min_face_px=min_face_px)

    def remove_known_face(self, face_id: str) -> bool:
        known = self.config.get("known_faces", {})
        if face_id in known:
            del known[face_id]
            self.save_config(self.config)
            return True
        return False

    # ==================== 运行时录入（门禁页） ====================

    def _identity_dir(self, name: str) -> Path:
        identity = identity_name(name)
        path = AUTHORIZED_DIR / identity
        if path.parent != AUTHORIZED_DIR:           # 清洗规则之外的双保险
            raise ValueError(f"非法的人脸库目录名: {identity}")
        return path

    def _enroll_extractor(self):
        """取当前 embeddings 库用的同一个提特征器。

        换特征空间（比如把 method 从灰度余弦改成 ArcFace）会让旧原型全部失效，
        所以录入必须跟随库里已写明的 method，而不是配置文件里新写的那个。
        """
        from .recognizer import create_embedding_extractor

        if self.recognizer is not None:
            return (self.recognizer.extractor, self.recognizer.method,
                    self.recognizer.image_size)
        recog_cfg = self.config.get("recognition", {})
        method = str(recog_cfg.get("method", "simple_grayscale_cosine"))
        size = int(recog_cfg.get("image_size", 112))
        return (create_embedding_extractor(method=method,
                                           model_path=str(RECOGNITION_MODEL_PATH),
                                           image_size=size), method, size)

    @staticmethod
    def _empty_database(method: str, image_size: int) -> dict:
        return {"version": 2, "method": method,
                "model_path": str(RECOGNITION_MODEL_PATH),
                "image_size": image_size, "identities": []}

    def _apply_database(self, database: dict) -> None:
        """把新算好的库装回运行中的识别器（认人立即生效，不用重启服务）。"""
        if self.recognizer is not None:
            self.recognizer.database = database
            self.recognizer.identities = database["identities"]
            return
        self._load_model()

    def _detect_face_crops(self, frame, limit: int = 3) -> list:
        """检出画面里的人脸并裁出来，按面积从大到小排（录入取最大的那张）。"""
        try:
            detections = self.detector.detect(frame)
        except Exception as e:                        # noqa: BLE001
            logger.error("人脸检测失败: %s", e)
            self.health.record_failure(str(e))
            return []

        height, width = frame.shape[:2]
        crops = []
        for det in detections:
            x1, y1, x2, y2 = det.xyxy_int()
            pad = int(max(x2 - x1, y2 - y1) * 0.15)
            left, top = max(0, x1 - pad), max(0, y1 - pad)
            right, bottom = min(width, x2 + pad), min(height, y2 + pad)
            crop = frame[top:bottom, left:right]
            if crop.size:
                crops.append(((right - left) * (bottom - top), crop))
        crops.sort(key=lambda item: item[0], reverse=True)
        return [crop for _area, crop in crops[:limit]]

    def enroll_faces(self, name: str, images_base64: list[str]) -> dict:
        """把门禁页截来的几帧存成该人员的注册照，并重算、热加载他的身份原型。

        只重算这一个身份：全库重建（scripts/enroll_faces.py）留给离线场景。
        """
        from .recognizer import build_identity, save_embedding_database

        identity_dir = self._identity_dir(name)
        if self.simulation_mode or self.detector is None:
            self.reload_model()
        if self.detector is None or self.simulation_mode:
            return {"ok": False,
                    "error": "人脸识别模型未加载（当前为模拟模式），无法录入真实人脸"}
        if not self.config.get("recognition", {}).get("enabled", True):
            return {"ok": False, "error": "人脸配置里 recognition.enabled=false，身份识别已关闭"}

        import cv2
        import numpy as np

        blobs: list[bytes] = []
        decode_failed = 0
        for raw in list(images_base64 or [])[:MAX_ENROLL_FRAMES]:
            try:
                blobs.append(safe_base64_decode(raw, max_size_mb=ENROLL_IMAGE_MAX_MB))
            except ValueError:
                decode_failed += 1
        if not blobs:
            return {"ok": False, "error": "没有可用的图像数据（请确认页面已有摄像头画面）"}

        # 微秒级时间戳：同一秒内连点两次「录入人脸」，秒级戳会让第二批
        # 直接覆盖第一批的同名文件（注册照静默变少，原型也跟着退化）
        stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1e6) % 1_000_000:06d}"
        accepted: list[Path] = []
        rejected: list[str] = []
        with self._enroll_lock:
            identity_dir.mkdir(parents=True, exist_ok=True)
            for idx, blob in enumerate(blobs):
                frame = cv2.imdecode(np.frombuffer(blob, dtype=np.uint8),
                                     cv2.IMREAD_COLOR)
                if frame is None:
                    rejected.append("图像解码失败")
                    continue
                crops = self._detect_face_crops(frame)
                if not crops:
                    rejected.append("画面里没有人脸")
                    continue
                crop = crops[0]
                height, width = crop.shape[:2]
                if min(height, width) < MIN_FACE_SIDE:
                    rejected.append(f"人脸太小（{width}x{height}）")
                    continue
                path = identity_dir / f"enroll_{stamp}_{idx:02d}.jpg"
                if not cv2.imwrite(str(path), crop):
                    rejected.append("照片写入失败")
                    continue
                accepted.append(path)

            if not accepted:
                return {"ok": False,
                        "error": f"{len(blobs)} 帧都没有合格的正面人脸：" +
                                 "；".join(dict.fromkeys(rejected)),
                        "rejected": rejected}

            extractor, method, image_size = self._enroll_extractor()
            identity = build_identity(identity_dir, extractor,
                                      max_images=MAX_IDENTITY_IMAGES)
            if identity is None:
                return {"ok": False, "error": "注册照都读不出来，身份未建立"}

            database = dict(self.recognizer.database) if self.recognizer is not None \
                else self._empty_database(method, image_size)
            database["method"] = method
            database["image_size"] = image_size
            database["identities"] = [
                i for i in (database.get("identities") or [])
                if str(i.get("name")) != identity["name"]] + [identity]
            save_embedding_database(database, EMBEDDINGS_PATH)
            self._apply_database(database)
            self.add_known_face(identity["name"], identity["name"])
            self.health.record_success()

        logger.info("[人脸录入] %s：%d 张新照，库内共 %d 张",
                    identity["name"], len(accepted), identity["image_count"])
        return {"ok": True, "face_id": identity["name"],
                "accepted": len(accepted), "rejected": rejected,
                "decode_failed": decode_failed,
                "images": identity["image_count"],
                "images_dir": str(identity_dir)}

    def forget_identity(self, name: str) -> dict:
        """删人时用：清掉该人员的注册照片，并把身份从 embeddings 库里摘出去。"""
        from .recognizer import save_embedding_database

        identity_dir = self._identity_dir(name)
        with self._enroll_lock:
            removed_dir = identity_dir.is_dir()
            if removed_dir:
                shutil.rmtree(identity_dir, ignore_errors=True)
            self.remove_known_face(identity_dir.name)

            if self.recognizer is None:
                return {"ok": True, "photos_removed": removed_dir,
                        "identities": 0}
            database = dict(self.recognizer.database)
            kept = [i for i in database.get("identities") or []
                    if str(i.get("name")) != identity_dir.name]
            if len(kept) == len(database.get("identities") or []):
                return {"ok": True, "photos_removed": removed_dir,
                        "identities": len(kept or [])}
            database["identities"] = kept
            if not kept:
                # 空库会让 load_embedding_database 抛异常，不如直接删掉文件
                EMBEDDINGS_PATH.unlink(missing_ok=True)
                self.recognizer = None
                return {"ok": True, "photos_removed": removed_dir, "identities": 0}
            save_embedding_database(database, EMBEDDINGS_PATH)
            self.recognizer.database = database
            self.recognizer.identities = kept
            logger.info("[人脸删除] 已移除身份 %s，库内剩 %d 人",
                        identity_dir.name, len(kept))
            return {"ok": True, "photos_removed": removed_dir, "identities": len(kept)}

    def person_face_state(self, name: str) -> dict:
        """门禁页回显用：这个人当前有没有注册照、几张。"""
        identity_dir = self._identity_dir(name)
        if not identity_dir.is_dir():
            return {"face_id": identity_dir.name, "images": 0}
        from .recognizer import collect_face_images

        return {"face_id": identity_dir.name,
                "images": len(collect_face_images(identity_dir))}
