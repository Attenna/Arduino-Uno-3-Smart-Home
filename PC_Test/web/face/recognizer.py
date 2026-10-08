"""人脸身份识别：嵌入特征比对（合并自 yolo_face_detection/src/recognizer.py）。

两种嵌入提取方式：
- arcface_onnx          ：InsightFace 风格 ArcFace/FaceNet ONNX（高精度，需模型文件）
- simple_grayscale_cosine：归一化灰度直方图余弦相似度（零依赖，开箱即用，精度一般）

先用 scripts/enroll_faces.py 扫描 data/face/authorized/<姓名>/*.jpg 生成
data/face/embeddings.pkl，识别时取余弦相似度最高且超过阈值的身份。
"""
from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

# 算模型指纹时读取的文件头长度：够区分不同 ONNX，又不用整读上百 MB
FINGERPRINT_PREFIX_BYTES = 256 * 1024
# ArcFace 官方 112x112 五点模板。预处理版本写入 embeddings.pkl，避免对齐前后的
# 向量混在同一个库里；调整模板或变换算法时必须升级这个字符串并重建人脸库。
FACE_PREPROCESSING_VERSION = "arcface_5point_v1"
LEGACY_PREPROCESSING_VERSION = "bbox_resize_v0"
ARCFACE_TEMPLATE_112 = np.asarray([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041],
], dtype=np.float32)


def estimate_face_alignment(
    landmarks: Any,
    image_size: int = 112,
) -> np.ndarray | None:
    """估计五点到 ArcFace 标准模板的相似变换矩阵。"""
    try:
        source = np.asarray(landmarks, dtype=np.float32).reshape(5, 2).copy()
    except (TypeError, ValueError):
        return None
    if not np.isfinite(source).all() or np.allclose(source, 0.0):
        return None
    # 不依赖模型采用“人物左右”还是“画面左右”命名：按 x 坐标规范眼睛/嘴角。
    if source[0, 0] > source[1, 0]:
        source[[0, 1]] = source[[1, 0]]
    if source[3, 0] > source[4, 0]:
        source[[3, 4]] = source[[4, 3]]
    target = ARCFACE_TEMPLATE_112 * (float(image_size) / 112.0)
    matrix, _inliers = cv2.estimateAffinePartial2D(
        source, target, method=cv2.LMEDS)
    if matrix is None or not np.isfinite(matrix).all():
        return None
    return np.asarray(matrix, dtype=np.float32)


def align_face_5point(
    image: np.ndarray,
    landmarks: Any,
    image_size: int = 112,
) -> np.ndarray | None:
    """把原图中的人脸按五点仿射到 ArcFace 标准姿态。"""
    if image is None or image.size == 0:
        return None
    matrix = estimate_face_alignment(landmarks, image_size=image_size)
    if matrix is None:
        return None
    return cv2.warpAffine(
        image,
        matrix,
        (image_size, image_size),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def prepare_detected_face(
    image: np.ndarray,
    detection: Any,
    image_size: int = 112,
    pad_ratio: float = 0.0,
) -> tuple[np.ndarray | None, bool]:
    """优先五点对齐；权重无关键点或关键点无效时兼容普通裁剪。"""
    landmarks = getattr(detection, "landmarks", None)
    if landmarks is not None:
        aligned = align_face_5point(image, landmarks, image_size=image_size)
        if aligned is not None:
            return aligned, True

    if image is None or image.size == 0:
        return None, False
    height, width = image.shape[:2]
    x1, y1, x2, y2 = detection.xyxy_int()
    pad = int(max(x2 - x1, y2 - y1) * max(0.0, float(pad_ratio)))
    left, top = max(0, x1 - pad), max(0, y1 - pad)
    right, bottom = min(width, x2 + pad), min(height, y2 + pad)
    crop = image[top:bottom, left:right]
    return (crop if crop.size else None), False


@dataclass(frozen=True)
class RecognitionResult:
    identity: str
    score: float
    authorized: bool
    second_score: float = -1.0
    margin: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "score": round(self.score, 4),
            "authorized": self.authorized,
            "second_score": round(self.second_score, 4),
            "margin": round(self.margin, 4),
        }


class FaceRecognizer:
    def __init__(
        self,
        embeddings_path: str | Path,
        model_path: str | Path | None = None,
        method: str = "arcface_onnx",
        similarity_threshold: float = 0.5,
        ambiguity_margin: float = 0.08,
        image_size: int = 112,
    ) -> None:
        self.embeddings_path = Path(embeddings_path)
        self.method = method
        self.similarity_threshold = similarity_threshold
        self.ambiguity_margin = max(0.0, float(ambiguity_margin))
        self.image_size = image_size
        self.database = load_embedding_database(self.embeddings_path)
        self.method = str(self.database.get("method", self.method))
        self.image_size = int(self.database.get("image_size", self.image_size))
        self.identities = self.database["identities"]
        # 当前模型文件的指纹：库里写的不等于它，说明原型是别的模型算的
        self.model_fingerprint = model_fingerprint(self.method, model_path)
        self.library_fingerprint = str(self.database.get("model_fingerprint") or "")
        self.library_preprocessing = str(
            self.database.get("preprocessing") or LEGACY_PREPROCESSING_VERSION)
        self.extractor = create_embedding_extractor(
            method=self.method,
            model_path=model_path,
            image_size=self.image_size,
        )

    def extract_embedding(self, face_image: np.ndarray) -> np.ndarray:
        return self.extractor.extract(face_image)

    def recognize(self, face_image: np.ndarray) -> RecognitionResult:
        query = self.extractor.extract(face_image)
        best_identity = "unknown"
        best_score = -1.0
        second_score = -1.0

        for identity in self.identities:
            prototype = np.asarray(identity["prototype"], dtype=np.float32)
            score = cosine_similarity(query, prototype)
            if score > best_score:
                second_score = best_score
                best_score = score
                best_identity = str(identity["name"])
            elif score > second_score:
                second_score = score

        margin = best_score - second_score
        authorized = (best_score >= self.similarity_threshold
                      and margin >= self.ambiguity_margin)
        if not authorized:
            best_identity = "unknown"

        return RecognitionResult(
            identity=best_identity,
            score=best_score,
            authorized=authorized,
            second_score=second_score,
            margin=margin,
        )


class SimpleEmbeddingExtractor:
    def __init__(self, image_size: int = 112) -> None:
        self.image_size = image_size

    def extract(self, face_image: np.ndarray) -> np.ndarray:
        return extract_simple_embedding(face_image, self.image_size)


class ArcFaceONNXEmbeddingExtractor:
    """ArcFace/InsightFace 风格 ONNX 特征提取器（RGB 112x112，(x-127.5)/127.5）。"""

    def __init__(self, model_path: str | Path | None, image_size: int = 112) -> None:
        if model_path is None:
            raise ValueError("recognition.model_path is required for arcface_onnx")

        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Recognition model not found: {self.model_path}. "
                "Place an ArcFace/FaceNet ONNX model there, or use "
                "method=simple_grayscale_cosine."
            )

        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is required for ArcFace/FaceNet recognition. "
                "Run: pip install onnxruntime"
            ) from exc

        self.session = ort.InferenceSession(
            str(self.model_path),
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.image_size = infer_onnx_image_size(
            self.session.get_inputs()[0].shape,
            fallback=image_size,
        )

    def extract(self, face_image: np.ndarray) -> np.ndarray:
        if face_image is None or face_image.size == 0:
            raise ValueError("Cannot extract an embedding from an empty face image")

        if face_image.ndim == 2:
            face_image = cv2.cvtColor(face_image, cv2.COLOR_GRAY2BGR)

        resized = cv2.resize(
            face_image,
            (self.image_size, self.image_size),
            interpolation=cv2.INTER_AREA,
        )
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        blob = (rgb.astype(np.float32) - 127.5) / 127.5
        blob = np.transpose(blob, (2, 0, 1))[None, ...]
        output = self.session.run([self.output_name], {self.input_name: blob})[0]
        embedding = np.asarray(output, dtype=np.float32).reshape(-1)
        return normalize_embedding(embedding)


def create_embedding_extractor(
    method: str,
    model_path: str | Path | None = None,
    image_size: int = 112,
):
    if method == "arcface_onnx":
        return ArcFaceONNXEmbeddingExtractor(model_path=model_path, image_size=image_size)
    if method == "simple_grayscale_cosine":
        return SimpleEmbeddingExtractor(image_size=image_size)
    raise ValueError(f"Unsupported recognition method: {method}")


def infer_onnx_image_size(shape: list[Any], fallback: int = 112) -> int:
    numeric_dims = [dim for dim in shape if isinstance(dim, int) and dim > 0]
    spatial_dims = [dim for dim in numeric_dims if dim not in {1, 3}]
    if spatial_dims:
        return int(spatial_dims[-1])
    return fallback


def extract_simple_embedding(face_image: np.ndarray, image_size: int = 112) -> np.ndarray:
    if face_image is None or face_image.size == 0:
        raise ValueError("Cannot extract an embedding from an empty face image")

    if face_image.ndim == 3:
        gray = cv2.cvtColor(face_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = face_image

    resized = cv2.resize(gray, (image_size, image_size), interpolation=cv2.INTER_AREA)
    equalized = cv2.equalizeHist(resized)
    embedding = equalized.astype(np.float32).reshape(-1) / 255.0
    embedding = embedding - float(embedding.mean())
    return normalize_embedding(embedding)


def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    embedding = np.asarray(embedding, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(embedding))
    if norm == 0:
        return embedding
    return embedding / norm


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))


FACE_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".pgm"}


def collect_face_images(person_dir: str | Path) -> list[Path]:
    return sorted(
        path
        for path in Path(person_dir).rglob("*")
        if path.is_file() and path.suffix.lower() in FACE_IMAGE_SUFFIXES
    )


def build_identity(
    person_dir: str | Path,
    extractor,
    max_images: int | None = None,
    detector=None,
) -> dict[str, Any] | None:
    """算出一个人的均值原型；目录里没有可读图片时返回 None。

    max_images 只取文件名排序后的最后 N 张（运行时录入的文件名带时间戳，
    即「最新的 N 张」）：注册照越攒越多会让每次热加载的提特征成本线性上涨。
    """
    image_paths = collect_face_images(person_dir)
    if max_images:
        image_paths = image_paths[-max_images:]
    embeddings = []
    used_images = []
    for image_path in image_paths:
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            print(f"[skip] Cannot read authorized face image: {image_path}")
            continue
        prepared = image
        if detector is not None:
            detections = detector.detect(image)
            if not detections:
                print(f"[skip] No face found in authorized image: {image_path}")
                continue
            detection = max(
                detections,
                key=lambda item: (
                    item.xyxy_int()[2] - item.xyxy_int()[0]
                ) * (
                    item.xyxy_int()[3] - item.xyxy_int()[1]
                ),
            )
            prepared, _aligned = prepare_detected_face(
                image, detection, image_size=extractor.image_size, pad_ratio=0.15)
            if prepared is None:
                print(f"[skip] Cannot crop authorized face image: {image_path}")
                continue
        embeddings.append(extractor.extract(prepared))
        used_images.append(str(image_path))

    if not embeddings:
        return None

    stacked = np.vstack(embeddings).astype(np.float32)
    return {
        "name": Path(person_dir).name,
        "image_count": len(used_images),
        "images": used_images,
        "prototype": normalize_embedding(stacked.mean(axis=0)),
    }


def model_fingerprint(method: str, model_path: str | Path | None) -> str:
    """标识「这批原型是用哪个模型算出来的」，用来拦住跨模型比对。

    不同模型的 512 维向量之间余弦相似度接近噪声，但库里只记 method 的话，
    换了 ONNX 文件后旧原型照样能加载 —— 表现是「谁都不开权限」，日志里
    一句错误都没有。所以 method + 文件大小 + 文件头哈希拼成指纹。

    只哈希前 FINGERPRINT_PREFIX_BYTES：整读 174MB 在派上要花秒级，而换模型
    必然换文件，头部片段加总长度足以区分。
    """
    if method != "arcface_onnx" or not model_path:
        return str(method)
    path = Path(model_path)
    if not path.exists():
        return f"{method}:missing"
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            digest.update(file.read(FINGERPRINT_PREFIX_BYTES))
    except OSError as exc:
        return f"{method}:unreadable:{exc.__class__.__name__}"
    return f"{method}:{path.stat().st_size}:{digest.hexdigest()[:16]}"


def probe_library_similarity(
    recognizer: "FaceRecognizer",
    authorized_dir: str | Path,
    max_identities: int = 3,
    images_per_identity: int = 2,
) -> float | None:
    """拿磁盘上的注册照重算原型，与库里存的向量比余弦；返回各身份里最高的那个分。

    没写 model_fingerprint 的老库光看文件猜不出是谁建的，而跨模型的余弦实测只有
    0.07 上下（同人也一样）、同模型同人 ≥0.75，所以「重算一遍比一下」足够判定。
    只取每个身份最新的几张、最多几个身份：派上单脸约 93ms，别把启动拖成长任务。
    库里没有任何身份、或照片一张都读不出来时返回 None（判不了，不是不匹配）。
    """
    best: float | None = None
    for identity in list(recognizer.identities or [])[:max_identities]:
        stored = identity.get("prototype")
        if stored is None:
            continue
        rebuilt = build_identity(Path(authorized_dir) / str(identity.get("name")),
                                 recognizer.extractor,
                                 max_images=images_per_identity)
        if rebuilt is None:
            continue
        score = cosine_similarity(rebuilt["prototype"],
                                  np.asarray(stored, dtype=np.float32))
        best = score if best is None else max(best, score)
    return best


def build_embedding_database(
    authorized_dir: str | Path,
    model_path: str | Path | None = None,
    method: str = "arcface_onnx",
    image_size: int = 112,
    detector=None,
) -> dict[str, Any]:
    authorized_path = Path(authorized_dir)
    if not authorized_path.exists():
        raise FileNotFoundError(f"Authorized faces directory not found: {authorized_path}")

    extractor = create_embedding_extractor(
        method=method,
        model_path=model_path,
        image_size=image_size,
    )

    identities: list[dict[str, Any]] = []
    for person_dir in sorted(p for p in authorized_path.iterdir() if p.is_dir()):
        identity = build_identity(person_dir, extractor, detector=detector)
        if identity is not None:
            identities.append(identity)

    if not identities:
        raise ValueError(f"No valid authorized face images found under: {authorized_path}")

    return {
        "version": 2,
        "method": method,
        "model_path": str(model_path) if model_path else None,
        "model_fingerprint": model_fingerprint(method, model_path),
        "preprocessing": (FACE_PREPROCESSING_VERSION if detector is not None
                          else LEGACY_PREPROCESSING_VERSION),
        "image_size": image_size,
        "identities": identities,
    }


def save_embedding_database(database: dict[str, Any], output_path: str | Path) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as file:
        pickle.dump(database, file)


def load_embedding_database(path: str | Path) -> dict[str, Any]:
    database_path = Path(path)
    if not database_path.exists():
        raise FileNotFoundError(
            f"Embedding database not found: {database_path}. "
            "Run scripts/enroll_faces.py first."
        )
    with database_path.open("rb") as file:
        database = pickle.load(file)
    if not database.get("identities"):
        raise ValueError(f"Embedding database has no identities: {database_path}")
    return database
