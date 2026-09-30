"""运行期单例：数据库、人脸引擎、HA 客户端、MCP 硬件桥、自动化引擎。"""
from __future__ import annotations

import threading

from .automation.engine import AutomationEngine
from .config import DB_PATH
from .config import DATA_DIR
from .database import SmartHomeDB
from .database import utcnow
from .face.engine import FaceEngine
from .ha_client import HomeAssistantClient
from .hardware import McpHardwareBridge

# 数据库与人脸引擎在 import 时即可用（不依赖串口）
db = SmartHomeDB(str(DB_PATH))
face_engine = FaceEngine()
ha_client = HomeAssistantClient()

# 硬件桥/自动化引擎由 create_app() 按配置启动
bridge: McpHardwareBridge | None = None
automation: AutomationEngine | None = None
_bridge_lock = threading.Lock()


def init_bridge(cfg: dict) -> McpHardwareBridge:
    global bridge, automation
    with _bridge_lock:
        if bridge is None:
            bridge = McpHardwareBridge(cfg, db)
            bridge.start()
            # 自动化引擎挂在硬件桥的快照/事件钩子上；动作经 bridge 下发
            rules_path = DATA_DIR / "automation_rules.json"
            automation = AutomationEngine(bridge, db, rules_path)
            bridge.snapshot_listener = automation.on_snapshot
            bridge.event_listener = automation.on_event

            # B 板不主动上报 state：执行器指令收到 ACK 即刷新 output_last_seen，
            # 使 output_online 反映"最近能否成功应答"
            def _mark_output_ack(_tool, _args):
                db.update_status(output_last_seen=utcnow())

            bridge.command_ack_listener = _mark_output_ack
            automation.start()
        return bridge


def shutdown_bridge() -> None:
    global bridge, automation
    with _bridge_lock:
        if automation is not None:
            automation.stop()
            automation = None
        if bridge is not None:
            bridge.stop()
            bridge = None
