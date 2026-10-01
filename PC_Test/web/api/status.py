"""系统状态 / 温湿度历史 / 统计 / 健康检查。"""
import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from .. import extensions
from ..extensions import db, face_engine, ha_client

bp = Blueprint("status", __name__)

# 命令下发值 ←→ B 板硬件回读值的对照表（P1 真值可读）
_READBACK_PAIRS = (
    ("fan", "fan_speed", "rb_fan_speed", "风扇"),
    ("door", "door_status", "rb_door_status", "门"),
    ("window", "window_status", "rb_window_status", "窗"),
    ("light", "light_brightness", "rb_light_brightness", "灯光"),
)


def _parse_utc(text):
    try:
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _device_mismatch(status: dict) -> list:
    """列出「命令下发值 ≠ B 板硬件回读值」的设备。

    这是 P1 的核心价值：以前 B 板不上报，指令没落到硬件上（"面板 0% 但风扇在转"）
    完全看不出来。两类情况不判定，避免误报：
      * 回读过期（>30s，心跳停了）；
      * 刚下发过（<15s）——回读是 10s 级心跳，本来就可能还没跟上。
        注意必须看 ``output_last_seen``（执行器指令被 ACK 的时刻），**不能用
        last_updated**：后者会被传感器轮询每 2 秒刷新，用它做闸门会导致永远不判定。
    """
    now = datetime.now(timezone.utc)
    seen = _parse_utc(status.get("rb_seen_at"))
    if seen is None or not 0 <= (now - seen).total_seconds() < 30:
        return []
    cmd_at = _parse_utc(status.get("output_last_seen"))
    if cmd_at is not None and (now - cmd_at).total_seconds() < 15:
        return []

    out = []
    for device, cmd_key, rb_key, label in _READBACK_PAIRS:
        cmd, rb = status.get(cmd_key), status.get(rb_key)
        if cmd is None or rb is None:
            continue
        if device in ("door", "window"):
            same = str(cmd) == str(rb)
        else:
            try:
                same = int(cmd) == int(rb)
            except (TypeError, ValueError):
                continue
        if not same:
            out.append({"device": device, "label": label,
                        "commanded": cmd, "readback": rb})
    return out


@bp.route("/api/status")
def get_status():
    status = db.get_current_status()
    status["statistics"] = db.get_statistics()
    bridge = extensions.bridge
    status["hardware_bridge"] = {
        "enabled": bridge is not None and bridge.enabled,
        "online": bridge.online if bridge else False,
        "relay": bridge.relay_url if bridge else None,
        "last_error": bridge.last_error if bridge else None,
    }
    status["device_mismatch"] = _device_mismatch(status)
    return jsonify(status)


@bp.route("/api/temperature")
def get_temperature():
    hours = request.args.get("hours", 24, type=int)
    return jsonify(db.get_temperature_history(hours))


@bp.route("/api/temperature/stats")
def get_temperature_stats():
    return jsonify(db.get_statistics().get("temperature_24h", {}))


@bp.route("/api/statistics")
def get_statistics():
    return jsonify(db.get_statistics())


@bp.route("/api/health")
def health_check():
    status = {
        "status": "ok",
        "timestamp": time.time(),
        "services": {
            "database": True,
            "ha": ha_client.connected,
            "face_recognition": face_engine.simulation_mode is False,
            "mcp_hardware": (extensions.bridge.online
                             if extensions.bridge else False),
        },
    }
    try:
        db.get_current_status()
    except Exception:
        status["services"]["database"] = False
        status["status"] = "degraded"
    return jsonify(status)
