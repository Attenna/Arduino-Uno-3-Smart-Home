"""运行期单例：数据库、人脸引擎、HA 客户端、MCP 硬件桥。"""
from __future__ import annotations

import threading

from .config import DB_PATH
from .database import SmartHomeDB
from .face.engine import FaceEngine
from .ha_client import HomeAssistantClient
from .hardware import McpHardwareBridge

# 数据库与人脸引擎在 import 时即可用（不依赖串口）
db = SmartHomeDB(str(DB_PATH))
face_engine = FaceEngine()
ha_client = HomeAssistantClient()

# 硬件桥由 create_app() 按配置启动
bridge: McpHardwareBridge | None = None
_bridge_lock = threading.Lock()


def init_bridge(cfg: dict) -> McpHardwareBridge:
    global bridge
    with _bridge_lock:
        if bridge is None:
            bridge = McpHardwareBridge(cfg, db)
            bridge.start()
        return bridge


def shutdown_bridge() -> None:
    global bridge
    with _bridge_lock:
        if bridge is not None:
            bridge.stop()
            bridge = None
