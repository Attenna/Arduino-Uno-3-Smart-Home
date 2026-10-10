"""web 服务的路径与配置中心。

所有运行时数据（SQLite、人脸配置、HA 配置、注册照片、embeddings）统一放在
PC_Test/data/ 下（已 gitignore）；模型权重放在 PC_Test/models/ 下（同样不入库）。
可在 PC_Test/web_config.yaml 覆盖默认值。
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

# ── 路径常量 ─────────────────────────────────────────────────────────────
WEB_DIR = Path(__file__).resolve().parent          # PC_Test/web
PC_TEST_DIR = WEB_DIR.parent                        # PC_Test
DATA_DIR = PC_TEST_DIR / "data"                     # 运行时数据
FACE_DATA_DIR = DATA_DIR / "face"
AUTHORIZED_DIR = FACE_DATA_DIR / "authorized"
UNAUTHORIZED_DIR = FACE_DATA_DIR / "unauthorized"

DB_PATH = DATA_DIR / "smart_home.db"
HA_CONFIG_PATH = DATA_DIR / "ha_config.json"
FACE_CONFIG_PATH = FACE_DATA_DIR / "face_config.json"
EMBEDDINGS_PATH = FACE_DATA_DIR / "embeddings.pkl"

MODELS_DIR = PC_TEST_DIR / "models"
FACE_MODEL_PATH = MODELS_DIR / "face" / "yolov8n-face.pt"
RECOGNITION_MODEL_PATH = MODELS_DIR / "face" / "recognition.onnx"

WEB_CONFIG_PATH = PC_TEST_DIR / "web_config.yaml"
MCP_SERVER_PATH = PC_TEST_DIR / "mcp_home_server.py"

# ── 默认配置（可被 web_config.yaml 覆盖）────────────────────────────────
DEFAULTS: dict = {
    "server": {
        "host": "0.0.0.0",
        "port": 5000,
    },
    "serial": {
        "enabled": True,   # False 时不拉 MCP 串口子进程（纯看板/演示模式）
        "port_a": "auto",
        "port_b": "auto",
    },
    # web 是全系统唯一硬件网关：语音助手经 /api/hardware/tool 调用硬件，
    # 串口只能被 web 拉起的 mcp_home_server 独占。
    # MCP 传感器快照轮询间隔（秒），拿到新数据即写入 SQLite
    "sensor_poll_interval": 1.0,
    # 语音助手 HTTP 服务（唤醒/文本指令/对话实况代理的目标地址）。
    # 环境变量 SMART_HOME_VOICE_URL 优先。
    "voice": {
        "url": "http://127.0.0.1:8101",
    },
    # 自动化引擎（HTTP 出站动作的主机放行策略）
    # 规则里的 URL 任何局域网客户端都能经 GET /api/automation/rules 读到，
    # 因此出站动作不携带凭据，且默认只允许回环/内网目标。
    "automation": {
        "http_enabled": True,
        "http_allow_public": False,
        "http_allowed_hosts": [],
        "http_timeout": 2.0,
    },
    "face": {
        "model_path": str(FACE_MODEL_PATH),
        "confidence_threshold": 0.4,
        "iou_threshold": 0.45,
        # YOLOv8-face 检测输入尺寸（imgsz）：需为 stride 32 的倍数，160~1280。
        # 只认本 yaml（data/face/face_config.json 是运行期产物，不作配置来源）。
        "image_size": 640,
        "max_faces": 5,
        # 无模型/未装 ultralytics 时自动回退模拟模式，保证前端可演示
        "simulation_mode": True,
        "recognition": {
            # 注册 embeddings 存在即启用人脸身份识别
            "enabled": True,
            # simple_grayscale_cosine 无需 ONNX 模型；放入 recognition.onnx
            # 并改成 arcface_onnx 可升级为 ArcFace 高精度识别
            "method": "simple_grayscale_cosine",
            "model_path": str(RECOGNITION_MODEL_PATH),
            "similarity_threshold": 0.5,
            # 第一名只比第二名略高时宁可拒绝，避免相似人员之间误放行。
            "ambiguity_margin": 0.08,
            "image_size": 112,
        },
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: Path | None = None) -> dict:
    """读取 web_config.yaml 并与默认值合并，最后应用 SMART_HOME_* 环境变量。"""
    cfg = copy.deepcopy(DEFAULTS)
    cfg_path = Path(path) if path else WEB_CONFIG_PATH
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as f:
            _deep_merge(cfg, yaml.safe_load(f) or {})
    # 容器里串口由 compose 从宿主机 .env 注入 SMART_HOME_PORT_A/B，优先于 yaml：
    # yaml 留 auto 时 MCP 只能靠 WHO 探测认板子，板子不回探测就当没插（重构前由
    # voice 侧读这两个变量，串口归 web 后必须在这里接着读）。
    for key, var in (("port_a", "SMART_HOME_PORT_A"), ("port_b", "SMART_HOME_PORT_B")):
        env = os.environ.get(var)
        if env:
            cfg["serial"][key] = env
    return cfg


def ensure_dirs() -> None:
    """确保运行时目录存在（启动时调用一次）。"""
    for path in (DATA_DIR, FACE_DATA_DIR, AUTHORIZED_DIR, UNAUTHORIZED_DIR,
                 MODELS_DIR / "face"):
        path.mkdir(parents=True, exist_ok=True)
