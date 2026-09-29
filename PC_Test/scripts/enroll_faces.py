"""人脸注册：扫描 data/face/authorized/<姓名>/*.jpg 生成 embeddings.pkl。

用法（在 PC_Test 目录下）：
    py -3.13 scripts/enroll_faces.py
    py -3.13 scripts/enroll_faces.py --method arcface_onnx \
        --model models/face/recognition.onnx

目录约定：
    data/face/authorized/
    └── 张三/
        ├── 001.jpg      # 同一个人 5~10 张不同角度/光线的正脸
        └── 002.jpg
生成后把 web_config.yaml 的 face.simulation_mode 改为 false 并重启 web 服务，
引擎即按 <姓名> 输出 face_id；在「门禁管理」页用同名 face_id 添加授权人员。

默认 method=simple_grayscale_cosine（零依赖，开箱即用，精度一般）；
放入 ArcFace/FaceNet ONNX 后用 --method arcface_onnx 获得高精度识别。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PC_TEST_DIR = Path(__file__).resolve().parents[1]
if str(PC_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(PC_TEST_DIR))

from web.config import (AUTHORIZED_DIR, EMBEDDINGS_PATH,  # noqa: E402
                        RECOGNITION_MODEL_PATH, load_config)
from web.face.recognizer import (build_embedding_database,  # noqa: E402
                                 save_embedding_database)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enroll authorized people and build data/face/embeddings.pkl")
    parser.add_argument("--authorized-dir", type=Path, default=None,
                        help="注册照片根目录（默认 data/face/authorized）")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="embeddings 输出路径")
    parser.add_argument("--model", type=Path, default=None,
                        help="ArcFace/FaceNet ONNX 模型路径")
    parser.add_argument("--method", default=None,
                        choices=["arcface_onnx", "simple_grayscale_cosine"])
    parser.add_argument("--image-size", type=int, default=None)
    args = parser.parse_args()

    cfg = load_config()
    recog = cfg.get("face", {}).get("recognition", {})
    authorized_dir = args.authorized_dir or AUTHORIZED_DIR
    output_path = args.output or EMBEDDINGS_PATH
    method = args.method or recog.get("method", "simple_grayscale_cosine")
    model_path = args.model or (
        Path(recog["model_path"]) if recog.get("model_path")
        else RECOGNITION_MODEL_PATH)
    image_size = args.image_size or int(recog.get("image_size", 112))

    if method == "arcface_onnx" and not Path(model_path).exists():
        print(f"[错误] 找不到 ArcFace 模型: {model_path}")
        print("       放入 ONNX 模型，或改用 --method simple_grayscale_cosine")
        return 1

    database = build_embedding_database(
        authorized_dir=authorized_dir,
        model_path=model_path if method == "arcface_onnx" else None,
        method=method,
        image_size=image_size,
    )
    save_embedding_database(database, output_path)

    print(f"[ok] enrolled {len(database['identities'])} identities "
          f"with method={method}")
    for identity in database["identities"]:
        print(f"  - {identity['name']}: {identity['image_count']} image(s)")
    print(f"[ok] saved embeddings to {output_path}")
    print("[next] 将 web_config.yaml 的 face.simulation_mode 改为 false，重启 run_web.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
