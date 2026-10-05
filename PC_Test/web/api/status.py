"""系统状态 / 温湿度历史 / 统计 / 健康检查。"""
import json
import time

from flask import Blueprint, jsonify, request, current_app

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
        "last_error": bridge.last_error if bridge else None,
        "ingest": bridge.ingest_stats if bridge else None,
    }
    status["device_mismatch"] = output_mismatch(status)
    # 串口链路健康度（A/B 是否连着、重连/复位/告警计数），由硬件桥低频刷新
    status["serial_health"] = getattr(bridge, "serial_health", None) if bridge else None
    return jsonify(status)


@bp.route("/api/hardware/self_test", methods=["GET", "POST"])
def hardware_self_test():
    """触发 B 板固件自检（只读诊断，需固件 V2.9+）。

    返回固件侧的铁证：命令成败计数、风扇两脚的方向位/电平、灯带 show() 实际调用
    次数、灯带数据脚拉高/拉低的读回值。用来把「灯不亮 / 风扇自转」二分到
    固件未执行 / 引脚被外设抢走 / 引脚物理短路。
    """
    bridge = extensions.bridge
    if bridge is None:
        return jsonify({"ok": False, "error": "硬件桥未初始化"}), 503
    ok, text = bridge.self_test()
    if not ok:
        return jsonify({"ok": False, "error": text}), 503
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {"raw": text}
    return jsonify({"ok": True, "selftest": payload})


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


@bp.route("/api/live")
def live():
    return jsonify(status="alive")


@bp.route("/api/health")
@bp.route("/api/ready")
def health_check():
    bridge = extensions.bridge
    required = {"database": False}
    try:
        row = db.get_current_status()
        required["database"] = True
    except Exception:
        row = {}
    serial_enabled = current_app.config["SMART_HOME_CFG"].get("serial", {}).get("enabled", True)
    if serial_enabled:
        required.update(mcp_hardware=bool(bridge and bridge.online),
                        sensor_fresh=bool(row.get("sensor_online")),
                        output_fresh=bool(row.get("output_online")))
    ready = all(required.values())
    return jsonify(status="ok" if ready else "degraded", timestamp=time.time(),
                   services=required,
                   optional_services={"ha": ha_client.connected,
                                      "face_recognition": bool(face_engine.recognizer)}), (200 if ready else 503)
