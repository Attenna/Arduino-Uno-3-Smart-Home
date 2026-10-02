"""门禁 API：人员与凭证管理（网页端录入人脸 / 房卡）、通行日志、链路自测。

这里只负责「谁有什么凭证」和「把凭证录进来」。开门、延时关门、迎客、被拒报警
都不在本模块：鉴权结果统一广播成 ``access_granted`` / ``access_denied`` 事件，
由 /automation 页的积木规则决定动作（内置预设 access_open_door / access_auto_close /
access_denied_buzzer，用户可改可停用）。

录入两条链路：
    人脸 —— 前端从摄像头实时画面截几帧 base64 传上来，web 侧检脸、存注册照、
            重算该身份原型并热加载识别器（``face_engine.enroll_faces``）；
    房卡 —— 点「录入房卡」开一个等待会话，用户把卡贴到 A 板 RC522 上，
            web 从串口事件里取到卡号绑到人（``access_guard``）。
"""
from flask import Blueprint, jsonify, request

from ..access_guard import CARD_ENROLL_TTL_S
from ..extensions import access_guard, db, face_engine

bp = Blueprint("access", __name__)

# 凭证类型：人脸识别 / RFID 刷卡，测试口也只允许这两种
VERIFY_METHODS = ("face", "rfid")


def _fail(error: str, error_en: str, code: int = 400):
    return jsonify({"error": error, "error_en": error_en}), code


def _person_json(person: dict) -> dict:
    """人员行 → 页面数据：face_id 就是人脸库目录名，照片张数一并给出。"""
    face_images = 0
    if person.get("face_id"):
        try:
            face_images = face_engine.person_face_state(
                person["face_id"])["images"]
        except ValueError:
            face_images = 0
    return {
        "id": person["id"],
        "name": person["name"],
        "face_id": person.get("face_id"),
        "rfid_uid": person.get("rfid_uid"),
        "enabled": bool(person.get("enabled")),
        "face_images": face_images,
    }


@bp.route("/api/access/persons", methods=["GET"])
def list_persons():
    return jsonify([_person_json(p) for p in db.list_persons()])


@bp.route("/api/access/persons", methods=["POST"])
def create_person():
    """建人只要姓名；人脸与房卡之后分别点「录入」按钮采集。"""
    name = str((request.json or {}).get("name", "")).strip()
    try:
        person = db.create_person(name)
    except ValueError as e:
        return _fail(str(e), f"Invalid person: {e}")
    return jsonify({"message": f"已添加授权人员: {person['name']}",
                    "message_en": f"Authorized person added: {person['name']}",
                    "person": _person_json(person)})


@bp.route("/api/access/persons/<int:person_id>", methods=["DELETE"])
def delete_person(person_id: int):
    person = db.delete_person(person_id)
    if not person:
        return _fail(f"未找到人员 {person_id}", "Person not found", 404)
    face_id = person.get("face_id")
    # 照片库以 face_id（=清洗后的姓名）为目录名：还有别人（含停用的）共用这个
    # 身份时不能清目录，否则把对方的识别能力一起删了
    if face_id:
        still_used = any(p.get("face_id") == face_id for p in db.list_persons())
        if not still_used:
            try:
                face_engine.forget_identity(face_id)
            except ValueError as e:
                return _fail(f"人员已删除，但照片清理失败：{e}",
                             "Person deleted, but face photos remain")
    return jsonify({"message": f"已删除人员: {person['name']}",
                    "message_en": f"Person deleted: {person['name']}"})


@bp.route("/api/access/persons/<int:person_id>/enabled", methods=["POST"])
def set_person_enabled(person_id: int):
    """停用=凭证保留但不认；启用后原来的人脸/房卡照常能用。"""
    enabled = bool((request.json or {}).get("enabled", True))
    person = db.set_person_enabled(person_id, enabled)
    if not person:
        return _fail(f"未找到人员 {person_id}", "Person not found", 404)
    label = "启用" if enabled else "停用"
    label_en = "enabled" if enabled else "disabled"
    return jsonify({"message": f"已{label}人员: {person['name']}",
                    "message_en": f"Person {label_en}: {person['name']}",
                    "person": _person_json(person)})


# ==================== 录入人脸（摄像头截帧） ====================

@bp.route("/api/access/persons/<int:person_id>/enroll/face", methods=["POST"])
def enroll_face(person_id: int):
    data = request.json or {}
    person = db.get_person(person_id)
    if not person:
        return _fail(f"未找到人员 {person_id}", "Person not found", 404)
    images = data.get("images") or []
    if not isinstance(images, list) or not images:
        return _fail("没有收到图像帧", "No image frames received")

    result = face_engine.enroll_faces(person["name"], images)
    if not result.get("ok"):
        reason = result.get("error") or "录入失败"
        return _fail(reason, f"Face enrollment failed: {reason}")

    try:
        updated = db.set_person_face(person_id, result["face_id"])
    except ValueError as e:
        # 照片已经落库，但身份标识被别人占用：把情况原样告诉用户，别静默改别人的凭证
        return _fail(f"{e}（注册照已保存，但未绑定到本人）",
                     f"Face ID conflict: {e}", 409)
    if updated is None:
        return _fail("人员已不存在，录入结果未保存", "Person no longer exists", 404)
    return jsonify({
        "message": f"已录入 {result['accepted']} 张人脸照片（{result['face_id']}）",
        "message_en": f"Enrolled {result['accepted']} face image(s): {result['face_id']}",
        "detail": {"rejected": result.get("rejected") or [],
                   "images": result.get("images"),
                   "dir": result.get("images_dir")},
        "person": _person_json(updated)})


# ==================== 录入房卡（等待刷卡） ====================

@bp.route("/api/access/persons/<int:person_id>/enroll/rfid", methods=["POST"])
def enroll_rfid(person_id: int):
    person = db.get_person(person_id)
    if not person:
        return _fail(f"未找到人员 {person_id}", "Person not found", 404)
    session = access_guard.start_card_session(person_id, person["name"])
    return jsonify({"message": f"请把卡片贴到读卡器上（{int(CARD_ENROLL_TTL_S)} 秒内）",
                    "message_en": "Tap the card on the reader",
                    "session": session,
                    "timeout_seconds": int(CARD_ENROLL_TTL_S)})


@bp.route("/api/access/enroll/rfid/<sid>", methods=["GET"])
def enroll_rfid_status(sid: str):
    session = access_guard.card_session(sid)
    if not session:
        return _fail("录入会话不存在或已过期", "Enrollment session expired", 404)
    out = {"state": session["state"], "uid": session.get("uid"),
           "error": session.get("error")}
    if session["state"] == "matched" and session.get("person"):
        out["person"] = _person_json(session["person"])
    return jsonify(out)


@bp.route("/api/access/enroll/rfid/<sid>", methods=["DELETE"])
def enroll_rfid_cancel(sid: str):
    return jsonify({"cancelled": access_guard.cancel_card_session(sid)})


# ==================== 通行日志 / 链路自测 ====================

@bp.route("/api/access/logs")
def get_access_logs():
    return jsonify(db.get_access_logs())


@bp.route("/api/access/test", methods=["POST"])
def access_test():
    """自测口：拿名单里的真实人员走一遍完整鉴权链（不碰硬件、不录凭证）。

    替代旧页面上写死的 FACE001/002/003 三个演示按钮 —— 身份来自数据库，
    鉴权、日志、事件广播与真实刷卡/推送完全同一条路径。
    """
    data = request.json or {}
    method = data.get("method") if data.get("method") in VERIFY_METHODS else "face"
    person = db.get_person(data.get("person_id"))
    if not person:
        return _fail("请选择名单里的真实人员", "Pick a real person from the list")
    credential = person.get("face_id") if method == "face" else person.get("rfid_uid")
    if not credential:
        label = "人脸" if method == "face" else "房卡"
        return _fail(f"该人员还没有录入{label}", f"Person has no {method} credential",
                     400)
    matched = access_guard.verify(method, credential)
    granted = matched is not None
    return jsonify({
        "granted": granted,
        "person": matched["name"] if granted else None,
        "method": method, "credential": credential,
        "message": (f"验证通过，欢迎 {matched['name']}!" if granted
                    else "身份未识别，访问被拒绝"),
        "message_en": (f"Verified, Welcome {matched['name']}!" if granted
                       else "Not recognized, access denied"),
    })
