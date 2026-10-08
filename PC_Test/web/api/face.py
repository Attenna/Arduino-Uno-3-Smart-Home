"""人脸识别 API：帧识别、引擎配置、已知人脸、识别结果推送（联动门禁）。"""
import base64

from flask import Blueprint, jsonify, request

from ..access_guard import deny_texts
from ..extensions import access_guard, db, face_engine
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
    result = face_engine.recognize_from_base64(image_b64)
    # 单帧接口也要留痕，兑现 docs/api.md 对 device_source='web'（网页自测/单帧识别）
    # 的说明。一律 record_only：只把这一轮判定写进 face_events，不广播门禁事件、不开门，
    # 否则这个无鉴权接口就成了远程开门通道。
    if not result.get("error"):
        if result.get("mode") == "throttled":
            access_guard.record_observation("throttled", device_source="web")
        elif not result.get("detected"):
            access_guard.record_observation("no_face", device_source="web")
        else:
            access_guard.handle_face_result(
                result.get("face_id") or "", device_source="web",
                score=result.get("score"),
                detection_confidence=result.get("confidence"), record_only=True)
    return jsonify(result)


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


# ==================== 识别结果推送（联动门禁）====================

@bp.route("/api/face/notify", methods=["POST"])
def face_notify():
    """香橙派/边缘设备推送人脸识别结果：记事件 → 白名单鉴权 → 广播门禁事件。

    开门不在这里。通过后广播 ``access_granted``（method=face），由积木规则
    （内置 ``access_open_door`` / ``access_auto_close``）决定开不开门、几点关门 ——
    想「只鉴权不开门」，在 /automation 页停用那两条规则即可。
    """
    data = request.json or {}
    face_id = data.get("face_id", "")
    if not face_id:
        return jsonify({"error": "缺少 face_id",
                        "error_en": "Missing face_id"}), 400

    result = access_guard.handle_face_result(
        face_id, confidence=data.get("confidence"),
        image_path=data.get("image_path", ""),
        device_source=data.get("device_source", "orange_pi"),
        # 新调用方明确传 score；旧边缘端曾把 ArcFace 相似度放在 confidence，
        # 这里兼容读取，但落到独立 score 列后页面才会展示。
        score=data.get("score", data.get("confidence")),
        detection_confidence=data.get("detection_confidence"))
    granted, person = result["granted"], result["person"]
    reason_zh, reason_en = (("", "") if granted
                            else deny_texts(result.get("reason")))
    result.update({
        "message": f"欢迎 {person}!" if granted else f"刷脸未通过：{reason_zh}",
        "message_en": f"Welcome {person}!" if granted
                      else f"Face not authorized: {reason_en}"})
    return jsonify(result)


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
