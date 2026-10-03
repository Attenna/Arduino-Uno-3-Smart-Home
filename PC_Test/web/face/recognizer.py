"""人脸身份识别：嵌入特征比对（合并自 yolo_face_detection/src/recognizer.py）。

两种嵌入提取方式：
- arcface_onnx          ：InsightFace 风格 ArcFace/FaceNet ONNX（高精度，需模型文件）
- simple_grayscale_cosine：归一化灰度直方图余弦相似度（零依赖，开箱即用，精度一般）

先用 scripts/enroll_faces.py 扫描 data/face/authorized/<姓名>/*.jpg 生成
data/face/embeddings.pkl，识别时取余弦相似度最高且超过阈值的身份。
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class RecognitionResult:
    identity: str
    score: float
    authorized: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "score": round(self.score, 4),
            "authorized": self.authorized,
        }


class FaceRecognizer:
    def __init__(
        self,
        embeddings_path: str | Path,
        model_path: str | Path | None = None,
        method: str = "arcface_onnx",
        similarity_threshold: float = 0.5,
        image_size: int = 112,
    ) -> None:
        self.embeddings_path = Path(embeddings_path)
        self.method = method
        self.similarity_threshold = similarity_threshold
        self.image_size = image_size
        self.database = load_embedding_database(self.embeddings_path)
        self.method = str(self.database.get("method", self.method))
        self.image_size = int(self.database.get("image_size", self.image_size))
        self.identities = self.database["identities"]
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

        for identity in self.identities:
            prototype = np.asarray(identity["prototype"], dtype=np.float32)
            score = cosine_similarity(query, prototype)
            if score > best_score:
                best_score = score
                best_identity = str(identity["name"])

        authorized = best_score >= self.similarity_threshold
        if not authorized:
            best_identity = "unknown"

        return RecognitionResult(
            identity=best_identity,
            score=best_score,
            authorized=authorized,
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
        embeddings.append(extractor.extract(image))
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


def build_embedding_database(
    authorized_dir: str | Path,
    model_path: str | Path | None = None,
    method: str = "arcface_onnx",
    image_size: int = 112,
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
        identity = build_identity(person_dir, extractor)
        if identity is not None:
            identities.append(identity)

    if not identities:
        raise ValueError(f"No valid authorized face images found under: {authorized_path}")

    return {
        "version": 2,
        "method": method,
        "model_path": str(model_path) if model_path else None,
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
