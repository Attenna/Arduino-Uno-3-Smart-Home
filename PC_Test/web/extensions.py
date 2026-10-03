"""运行期单例：数据库、人脸引擎、门禁、HA 客户端、MCP 硬件桥、自动化引擎。"""
from __future__ import annotations

import threading

from .access_guard import AccessGuard
from .automation.engine import AutomationEngine
from .config import DB_PATH
from .config import DATA_DIR
from .database import SmartHomeDB
from .database import utcnow
from .face.engine import FaceEngine
from .face_watcher import FaceWatcher
from .ha_client import HomeAssistantClient
from .hardware import McpHardwareBridge
from .security_monitor import SecurityMonitor

# 数据库与人脸引擎在 import 时即可用（不依赖串口）
db = SmartHomeDB(str(DB_PATH))
face_engine = FaceEngine()
ha_client = HomeAssistantClient()
# 门禁鉴权 + 房卡录入会话；事件出口与桥订阅由 init_bridge() 接上
access_guard = AccessGuard(db)
# 门口识别哨兵：摄像头帧 → 识别 → access_guard（不碰串口，纯看板模式也要跑）
face_watcher = FaceWatcher(face_engine, access_guard)

# 硬件桥/自动化引擎由 create_app() 按配置启动
bridge: McpHardwareBridge | None = None
automation: AutomationEngine | None = None
security_monitor: SecurityMonitor | None = None
_bridge_lock = threading.Lock()


def bind_automation(engine: AutomationEngine | None) -> None:
    """门禁鉴权结果 → 积木引擎：开门、延时关门、被拒报警全由规则决定。

    单独拆出来是因为「有没有串口」不该改变门禁行为：纯看板模式下门开不了，
    但 /api/face/notify 仍然要能触发规则（语音播报、日志、灯光迎客都不吃串口）。
    """
    access_guard.event_sink = engine.on_event if engine is not None else None


def init_bridge(cfg: dict) -> McpHardwareBridge:
    global bridge, automation, security_monitor
    with _bridge_lock:
        if bridge is None:
            security_monitor = SecurityMonitor(DATA_DIR / "security", cfg)
            security_monitor.start()
            bridge = McpHardwareBridge(cfg, db)
            # 自动化引擎挂在硬件桥的快照/事件钩子上；动作经 bridge 下发
            rules_path = DATA_DIR / "automation_rules.json"
            automation = AutomationEngine(bridge, db, rules_path, cfg)
            bridge.snapshot_listener = automation.on_snapshot
            bridge.event_listener = automation.on_event
            # 门禁：刷卡/键盘密码事件进鉴权，鉴权结果走积木（开门不再有硬编码）
            bind_automation(automation)
            access_guard.attach_bridge(bridge)
            bridge.add_listener("event", security_monitor.on_event)
            bridge.add_listener("snapshot", security_monitor.on_snapshot)
            # PIR 是识别哨兵的门控：没人时一帧都不抓
            face_watcher.attach_bridge(bridge)

            # B 板不主动上报 state：执行器指令收到 ACK 即刷新 output_last_seen，
            # 使 output_online 反映"最近能否成功应答"
            def _mark_output_ack(_tool, _args):
                db.update_status(output_last_seen=utcnow())

            bridge.command_ack_listener = _mark_output_ack
            automation.start()
            bridge.start()
        return bridge


def start_watchers(cfg: dict) -> bool:
    """起门口识别哨兵。

    与串口无关的两条接线放在这里：identity_check 让被拒原因能区分「这张脸没录过」
    和「录过但名单里没这个人」；摄像头地址从 cfg 解析，Docker 里指向 camera 容器。
    """
    access_guard.identity_check = face_engine.has_identity
    return face_watcher.start(cfg)


def shutdown_watchers() -> None:
    face_watcher.stop()


def shutdown_bridge() -> None:
    global bridge, automation, security_monitor
    with _bridge_lock:
        face_watcher.stop()
        bind_automation(None)
        if security_monitor is not None:
            if bridge is not None:
                bridge.remove_listener("event", security_monitor.on_event)
                bridge.remove_listener("snapshot", security_monitor.on_snapshot)
            security_monitor.stop()
            security_monitor = None
        if automation is not None:
            automation.stop()
            automation = None
        if bridge is not None:
            bridge.remove_listener("event", access_guard.on_hardware_event)
            bridge.remove_listener("snapshot", face_watcher.on_snapshot)
            bridge.stop()
            bridge = None
