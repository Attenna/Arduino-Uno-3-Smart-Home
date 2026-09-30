"""语音助手联动接口：把「唤醒 / 追问 / 文本指令」做成面板可点的能力。

语音助手自带 TriggerHTTPServer（默认 :8101），本模块只做同源代理，
避免前端跨端口访问：
    GET  /api/voice/status  → 语音助手在线状态 + 当前状态机状态
    POST /api/voice/wake    → 免唤醒词直接进入指令模式（等价按遥控器/按钮）
    POST /api/voice/say     → 直接下发文本指令（{"text": "..."}）
"""
from __future__ import annotations

import json

from flask import Blueprint
from flask import jsonify
from flask import request

from .. import extensions
from ..hardware import McpHardwareBridge

bp = Blueprint("voice", __name__)

# 语音助手状态机 → 中文标签（面板只读展示）
STATE_LABELS = {
    "IDLE": "待唤醒",
    "COMMAND": "聆听指令中",
    "THINKING": "思考中",
    "FOLLOWUP": "追问窗口",
}


def _bridge() -> McpHardwareBridge | None:
    return extensions.bridge


@bp.route("/api/voice/status")
def voice_status():
    b = _bridge()
    if b is None or not b.relay_url:
        return jsonify({"online": False, "state": None, "state_label": "未连接",
                        "error": "语音助手未配置（SMART_HOME_HW_RELAY）"}), 503
    ok, text = b.voice_request("/state")
    if not ok:
        return jsonify({"online": False, "state": None, "state_label": "离线",
                        "error": text}), 503
    try:
        state = json.loads(text).get("state")
    except Exception:                            # noqa: BLE001
        state = None
    return jsonify({"online": True, "state": state,
                    "state_label": STATE_LABELS.get(state, state or "未知")})


@bp.route("/api/voice/wake", methods=["POST"])
def voice_wake():
    b = _bridge()
    if b is None or not b.relay_url:
        return jsonify({"ok": False, "error": "语音助手未配置（SMART_HOME_HW_RELAY）"}), 503
    ok, text = b.voice_request("/trigger")
    if not ok:
        return jsonify({"ok": False, "error": text}), 502
    return jsonify({"ok": True, "message": "已唤醒，请说指令", "state": "COMMAND"})


@bp.route("/api/voice/say", methods=["POST"])
def voice_say():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "text 不能为空"}), 400
    b = _bridge()
    if b is None or not b.relay_url:
        return jsonify({"ok": False, "error": "语音助手未配置（SMART_HOME_HW_RELAY）"}), 503
    ok, msg = b.voice_request("/say", {"text": text})
    if not ok:
        return jsonify({"ok": False, "error": msg}), 502
    return jsonify({"ok": True, "text": text})