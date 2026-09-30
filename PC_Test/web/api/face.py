"""人脸识别 API：帧识别、引擎配置、已知人脸、香橙派结果推送。"""
import base64

from flask import Blueprint, jsonify, request

from .. import extensions
from ..extensions import db, face_engine
from ..utils import safe_base64_decode

bp = Blueprint("face", __name__)


# ==================== 帧识别 / 状态 / 配置 ====================

@bp.route("/api/face/recognize", methods=["POST"])
def face_recognize():
    image_data = (request.json or {}).get("image", "")
    if not image_data:
        return jsonify({"error": "无图像数据", "error_en": "No image data"}), 400
    try:
        image_bytes = safe_base64_decode(image_data, max_size_mb=5)
    except ValueError as e:
        return jsonify({"error": f"图像数据错误: {e}",
                        "error_en": f"Image data error: {e}"}), 400
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    return jsonify(face_engine.recognize_from_base64(image_b64))


@bp.route("/api/face/status")
def face_status():
    return jsonify(face_engine.get_status())


@bp.route("/api/face/config")
def face_get_config():
    return jsonify({"config": face_engine.config, "status": face_engine.get_status()})


@bp.route("/api/face/config", methods=["POST"])
def face_save_config():
    face_engine.save_config(request.json or {})
    if not (request.json or {}).get("simulation_mode", True):
        face_engine.reload_model()
    else:
        face_engine.reload_model()
    return jsonify({"message": "人脸识别配置已保存",
                    "message_en": "Face recognition config saved",
                    "status": face_engine.get_status()})


@bp.route("/api/face/reload", methods=["POST"])
def face_reload():
    success = face_engine.reload_model()
    status = face_engine.get_status()
    if success:
        return jsonify({"message": "模型已重新加载",
                        "message_en": "Model reloaded", "status": status})
    return jsonify({"message": "模型未加载，仍使用模拟模式",
                    "message_en": "Model not loaded, using simulation mode",
                    "status": status})


# ==================== 已知人脸 ====================

@bp.route("/api/face/known")
def face_get_known():
    return jsonify(face_engine.config.get("known_faces", {}))


@bp.route("/api/face/known", methods=["POST"])
def face_add_known():
    data = request.json or {}
    face_id, name = data.get("face_id", ""), data.get("name", "")
    if not face_id or not name:
        return jsonify({"error": "缺少参数", "error_en": "Missing parameters"}), 400
    face_engine.add_known_face(face_id, name)
    return jsonify({"message": f"已添加已知人脸: {name} ({face_id})",
                    "message_en": f"Known face added: {name} ({face_id})"})


@bp.route("/api/face/known/<face_id>", methods=["DELETE"])
def face_remove_known(face_id):
    if face_engine.remove_known_face(face_id):
        return jsonify({"message": f"已删除人脸: {face_id}",
                        "message_en": f"Face removed: {face_id}"})
    return jsonify({"error": f"未找到人脸: {face_id}",
                    "error_en": f"Face not found: {face_id}"}), 404


# ==================== 香橙派识别结果推送（联动门禁）====================

@bp.route("/api/face/notify", methods=["POST"])
def face_notify():
    """香橙派/边缘设备推送人脸识别结果：入库 -> 鉴权 -> 授权后自动开门。"""
    data = request.json or {}
    face_id = data.get("face_id", "")
    confidence = data.get("confidence")
    image_path = data.get("image_path", "")
    device_source = data.get("device_source", "orange_pi")

    if not face_id:
        return jsonify({"error": "缺少 face_id",
                        "error_en": "Missing face_id"}), 400

    matched = db.find_authorized(face_id, "face")
    if matched is None:
        for person in db.get_authorized_persons():
            if person.get("face_id") == face_id:
                matched = person
                break

    person_name = matched["name"] if matched else None
    event_id = db.add_face_event(
        face_id=face_id, person_name=person_name, confidence=confidence,
        image_path=image_path, device_source=device_source)

    if matched:
        # 开门动作已下沉为默认积木规则 face_open_door（face_granted 事件驱动，
        # 用户可停用/编辑）。此处只校验身份（安全边界）与记录，不再直接下发硬件。
        # door 直连开着时若有人想纯鉴权不开门，去掉那条积木规则即可。
        db.add_access_log(matched["name"], "face", "granted",
                          credential=face_id, command_status=None)
        if event_id:
            db.update_face_event_status(event_id, "granted", verified=True)
        # 通知自动化引擎：触发 face_granted 事件 → 默认积木规则开门/迎客等
        if extensions.automation is not None:
            extensions.automation.on_event(
                {"event": "face", "status": "granted",
                 "person": matched["name"], "face_id": face_id})
        return jsonify({
            "granted": True, "person": matched["name"], "face_id": face_id,
            "event_id": event_id,
            "message": f"欢迎 {matched['name']}!",
            "message_en": f"Welcome {matched['name']}!",
        })

    db.add_access_log("未知人员", "face", "denied", credential=face_id)
    if event_id:
        db.update_face_event_status(event_id, "denied", verified=False)
    return jsonify({
        "granted": False, "person": None, "face_id": face_id,
        "event_id": event_id,
        "message": "人脸未识别，访问被拒绝",
        "message_en": "Face not recognized, access denied",
    })


@bp.route("/api/face/events")
def face_get_events():
    limit = request.args.get("limit", 20, type=int)
    return jsonify(db.get_face_events(limit=limit))


@bp.route("/api/face/events/latest")
def face_get_latest_event():
    event = db.get_latest_face_event()
    if event:
        return jsonify(event)
    return jsonify({"message": "暂无识别事件",
                    "message_en": "No face events yet"}), 200
