"""Home Assistant 代理路由（可选通道，硬件管理页使用）。

设备主控制链路是 MCP 直连 Arduino；这组路由保留别组的 HA 配置/探测/代理能力，
便于在部署了 Home Assistant 的环境中映射实体、取摄像头画面。
"""
from datetime import datetime, timedelta

from flask import Blueprint, Response, jsonify, request

from ..extensions import ha_client

bp = Blueprint("ha", __name__)


@bp.route("/api/ha/connection")
def ha_test_connection():
    return jsonify(ha_client.test_connection())


@bp.route("/api/ha/config")
def ha_get_config():
    return jsonify({
        "ha_config": ha_client.get_config(),
        "device_mapping": ha_client.get_device_mapping(),
        "ha_url": ha_client.base_url,
        "ha_token": ha_client.token,
    })


@bp.route("/api/ha/config", methods=["POST"])
def ha_save_config():
    data = request.json or {}
    ha_client.save_config(data.get("ha_url", ""), data.get("ha_token", ""),
                          data.get("device_mapping"))
    return jsonify({"message": "配置已保存", "message_en": "Configuration saved"})


@bp.route("/api/ha/devices")
def ha_get_devices():
    try:
        devices = ha_client.get_discovered_devices()
        if not devices:
            return jsonify({"devices": [],
                            "message": "未发现设备或HA未连接",
                            "message_en": "No devices found or HA not connected"})
        return jsonify(devices)
    except Exception as e:
        return jsonify({"devices": [], "error": str(e),
                        "message": "获取设备失败",
                        "message_en": "Failed to get devices"}), 200


@bp.route("/api/ha/mapping", methods=["POST"])
def ha_update_mapping():
    data = request.json or {}
    ha_client.update_device_mapping(data.get("device_type", ""),
                                    data.get("entity_id", ""))
    return jsonify({"message": "设备映射已更新",
                    "message_en": "Device mapping updated"})


@bp.route("/api/ha/temperature")
def ha_get_temperature():
    return jsonify({"temperature": ha_client.get_temperature()})


@bp.route("/api/ha/humidity")
def ha_get_humidity():
    return jsonify({"humidity": ha_client.get_humidity()})


@bp.route("/api/ha/light", methods=["POST"])
def ha_control_light():
    data = request.json or {}
    return jsonify(ha_client.control_light(
        action=data.get("action", "toggle"),
        brightness=data.get("brightness")))


@bp.route("/api/ha/fan", methods=["POST"])
def ha_control_fan():
    data = request.json or {}
    return jsonify(ha_client.control_fan(speed_pct=data.get("speed")))


@bp.route("/api/ha/ac", methods=["POST"])
def ha_control_ac():
    data = request.json or {}
    return jsonify(ha_client.control_ac(
        mode=data.get("mode", "off"), temperature=data.get("temperature")))


@bp.route("/api/ha/door", methods=["POST"])
def ha_control_door():
    data = request.json or {}
    return jsonify(ha_client.control_door(action=data.get("action", "unlock")))


@bp.route("/api/ha/door/status")
def ha_get_door_status():
    return jsonify({"status": ha_client.get_door_status()})


@bp.route("/api/ha/window/status")
def ha_get_window_status():
    return jsonify({"status": ha_client.get_window_status()})


@bp.route("/api/ha/camera")
def ha_camera_snapshot():
    try:
        image = ha_client.get_camera_image()
        if image:
            return Response(image, mimetype="image/jpeg")
        return jsonify({"error": "无法获取图像，HA未连接或摄像头未配置",
                        "error_en": "Cannot get image, HA not connected or "
                                    "camera not configured"}), 200
    except Exception as e:
        return jsonify({"error": f"获取摄像头图像失败: {e}",
                        "error_en": f"Camera error: {e}"}), 200


@bp.route("/api/ha/history")
def ha_get_history():
    entity_id = request.args.get("entity_id", "")
    hours = request.args.get("hours", 24, type=int)
    if not entity_id:
        return jsonify({"error": "缺少 entity_id 参数",
                        "error_en": "Missing entity_id parameter"}), 400
    try:
        start_time = (datetime.now() - timedelta(hours=hours)).isoformat()
        history = ha_client.get_history([entity_id], start_time)
        return jsonify({"history": history, "entity_id": entity_id})
    except Exception as e:
        return jsonify({"error": str(e), "history": []}), 200
