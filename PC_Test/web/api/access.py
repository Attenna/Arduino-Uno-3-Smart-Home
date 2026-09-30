"""门禁：授权人员、通行日志、人脸/RFID 凭证校验。"""
from flask import Blueprint, jsonify, request

from .. import extensions
from ..extensions import db, face_engine

bp = Blueprint("access", __name__)


@bp.route("/api/access/logs")
def get_access_logs():
    return jsonify(db.get_access_logs())


@bp.route("/api/access/verify", methods=["POST"])
def verify_access():
    data = request.json or {}
    credential = data.get("face_id", data.get("rfid_tag", ""))
    verify_type = data.get("verify_type", "face")

    person = None
    if verify_type == "rfid":
        person = db.find_authorized(credential, "rfid")
    if person is None:
        # face_id 精确匹配，或退回全表比对（兼容旧前端）
        person = db.find_authorized(credential, "face")
        if person is None:
            for candidate in db.get_authorized_persons():
                if candidate.get("rfid_tag") == credential:
                    person = candidate
                    break

    if person:
        db.add_access_log(person["name"], verify_type, "granted",
                          credential=credential)
        # 需求2/3：门禁通过 → 交由全屋模式执行「开锁 + 10 秒后自动关门 + 判定进门」
        if extensions.automation is not None:
            extensions.automation.on_event(
                {"event": "face", "status": "granted", "person": person["name"],
                 "face_id": credential})
        return jsonify({
            "granted": True, "person": person["name"],
            "message": f"验证通过，欢迎 {person['name']}!",
            "message_en": f"Verified, Welcome {person['name']}!",
        })

    db.add_access_log("未知人员", verify_type, "denied", credential=credential)
    return jsonify({
        "granted": False, "person": None,
        "message": "身份未识别，访问被拒绝",
        "message_en": "Not recognized, access denied",
    })


@bp.route("/api/access/persons", methods=["GET"])
def get_persons():
    return jsonify(db.get_authorized_persons())


@bp.route("/api/access/persons", methods=["POST"])
def add_person():
    data = request.json or {}
    name = data.get("name", "")
    rfid_tag = data.get("rfid_tag", "") or None
    face_id = data.get("face_id", "") or None
    try:
        success = db.add_authorized_person(name, rfid_tag=rfid_tag, face_id=face_id)
    except ValueError as e:
        return jsonify({"error": str(e), "error_en": "Invalid person data"}), 400
    if success:
        if face_id:
            face_engine.add_known_face(face_id, name)
        return jsonify({
            "message": f"已添加授权人员: {name}",
            "message_en": f"Authorized person added: {name}",
        })
    return jsonify({"error": f"人员 {name} 已存在或凭证冲突",
                    "error_en": f"Person {name} already exists"}), 400
