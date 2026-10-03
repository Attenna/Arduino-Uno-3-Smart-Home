"""语音助手联动接口：把「唤醒 / 追问 / 文本指令 / 对话实况」做成面板可点的能力。

语音助手自带 HTTP 服务（默认 :8101），本模块只做同源代理，避免前端跨端口访问：
    GET  /api/voice/status  → 语音助手在线状态 + 当前状态机状态
    POST /api/voice/wake    → 免唤醒词直接进入指令模式（等价按遥控器/按钮）
    POST /api/voice/say     → 直接下发文本指令（{"text": "..."}）
    GET  /api/voice/events  → SSE 对话实况流（原样透传语音助手 /events）
"""
from __future__ import annotations

import json

from flask import Blueprint, Response, current_app, jsonify, request

from .. import voice_client

bp = Blueprint("voice", __name__)

# 语音助手状态机 → 中文标签（面板只读展示）
STATE_LABELS = {
    "IDLE": "待唤醒",
    "ACK": "提示音中",
    "COMMAND": "聆听指令中",
    "THINKING": "思考中",
    "FOLLOWUP": "追问窗口",
}


def _base_url() -> str:
    cfg = current_app.config.get("SMART_HOME_CFG") or {}
    return voice_client.resolve_voice_url(cfg)


@bp.route("/api/voice/status")
def voice_status():
    base = _base_url()
    ok, text = voice_client.voice_request(base, "/state")
    if not ok:
        return jsonify({"online": False, "state": None, "state_label": "离线",
                        "error": text}), 503
    try:
        payload = json.loads(text)
        state = payload.get("state")
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    except Exception:                            # noqa: BLE001
        state = None
        info = {}
    return jsonify({"online": True, "base_url": base, "state": state,
                    "state_label": STATE_LABELS.get(state, state or "未知"),
                    "info": info})


@bp.route("/api/voice/wake", methods=["POST"])
def voice_wake():
    ok, text = voice_client.voice_request(_base_url(), "/trigger")
    if not ok:
        return jsonify({"ok": False, "error": text}), 502
    try:
        state = json.loads(text).get("state") or "ACK"
    except Exception:                            # noqa: BLE001
        state = "ACK"
    return jsonify({"ok": True, "message": "已唤醒，提示结束后开始监听",
                    "state": state,
                    "state_label": STATE_LABELS.get(state, state)})


@bp.route("/api/voice/say", methods=["POST"])
def voice_say():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "text 不能为空"}), 400
    ok, msg = voice_client.voice_request(_base_url(), "/say", {"text": text})
    if not ok:
        return jsonify({"ok": False, "error": msg}), 502
    return jsonify({"ok": True, "text": text})


@bp.route("/api/voice/events")
def voice_events():
    """同源 SSE 代理：把语音助手的 /events 对话实况流转发给浏览器。"""
    base = _base_url()

    def passthrough():
        try:
            resp = voice_client.open_event_stream(base)
        except Exception as e:                     # noqa: BLE001
            payload = json.dumps({"type": "system",
                                  "text": f"语音助手不可达（{base}）: {e}"},
                                 ensure_ascii=False)
            yield f"data: {payload}\n\n"
            return
        try:
            for raw in resp:
                yield raw.decode("utf-8", "replace")
        except Exception:                          # noqa: BLE001
            pass                                   # 上游断开：前端 EventSource 自动重连
        finally:
            resp.close()

    return Response(passthrough(),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no",
                             "Connection": "keep-alive"})
