"""系统状态 / 温湿度历史 / 统计 / 健康检查。"""
import time

from flask import Blueprint, jsonify, request

from .. import extensions
from ..extensions import db, face_engine, ha_client
from ..readback import output_mismatch

bp = Blueprint("status", __name__)


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
    status["device_mismatch"] = output_mismatch(status)
    # 串口链路健康度（A/B 是否连着、重连/复位/告警计数），由硬件桥低频刷新
    status["serial_health"] = getattr(bridge, "serial_health", None) if bridge else None
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
