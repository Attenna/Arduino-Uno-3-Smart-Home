"""门禁鉴权与凭证录入：只回答「这张脸/这张卡是谁」，开门全交给积木。

分工（对应「抛弃门禁管理的硬编码开门逻辑」）：

    本模块   —— 凭证 → 人员 的白名单判定、通行日志、广播通用门禁事件
                ``access_granted`` / ``access_denied``；
    积木规则 —— 通过后开不开门、延时关门、要不要迎客，被拒时响不响蜂鸣器
                （内置预设 access_open_door / access_auto_close / access_denied_buzzer，
                在 /automation 页可改可停用）。

A 板的 ``rfid`` 事件在本模块被两处消费：页面上按过「录入房卡」的会话优先把这张卡
取走并绑到人（不做鉴权，否则新卡必然记一条「拒绝」）；没有等待会话时才走白名单。
"""
from __future__ import annotations

import logging
import threading
import time
import uuid

from .database import normalize_uid

logger = logging.getLogger(__name__)

# 按一次「录入房卡」后等待刷卡的时长：把卡放到读卡器上这段时间足够，
# 再长就该让用户重新点（避免页面开着时永远有个隐形会话在吃刷卡事件）
CARD_ENROLL_TTL_S = 45.0
# 录入结果（成功/冲突/超时）在内存里留多久供前端轮询取走
CARD_RESULT_KEEP_S = 300.0

GRANTED_EVENT = {"event": "access", "status": "granted"}
DENIED_EVENT = {"event": "access", "status": "denied"}


class AccessGuard:
    def __init__(self, db):
        self.db = db
        # 事件出口（extensions 接线时指向 automation.on_event）；
        # 纯看板模式没有串口时是 None —— 照样记账，只是没有规则可触发。
        self.event_sink = None
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ==================== 事件出口 ====================

    def broadcast(self, base: dict, **fields) -> None:
        sink = self.event_sink
        if sink is None:
            return
        event = dict(base)
        event.update({k: v for k, v in fields.items() if v not in (None, "")})
        try:
            sink(event)
        except Exception as e:                        # noqa: BLE001
            logger.warning("[门禁] 事件广播失败: %s", e)

    # ==================== 鉴权 ====================

    def verify(self, method: str, credential: str):
        """按白名单鉴权一个凭证，写通行日志并广播结果；返回命中的人员或 None。"""
        person = self.db.find_authorized(credential, method)
        if person:
            self.grant(method, credential, person)
            return person
        self.deny(method, credential)
        return None

    def grant(self, method: str, credential: str, person: dict) -> None:
        self.db.add_access_log(person["name"], method, "granted",
                               credential=credential)
        self.broadcast(GRANTED_EVENT, method=method, person=person["name"],
                       credential=credential)
        logger.info("[门禁] %s 通过：%s（%s）", method, person["name"], credential)

    def deny(self, method: str, credential: str, person_name: str | None = None) -> None:
        self.db.add_access_log(person_name or "未知人员", method, "denied",
                               credential=credential)
        self.broadcast(DENIED_EVENT, method=method, credential=credential)
        logger.info("[门禁] %s 被拒：%s", method, credential)

    def handle_face_result(self, face_id: str, confidence=None, image_path: str = "",
                           device_source: str = "web") -> dict:
        """识别结果统一入口：记一次识别事件 → 鉴权 → 广播。

        调用方是 ``POST /api/face/notify``（边缘设备推送）与 ``POST /api/face/recognize``
        的下游使用者；网页端不再猜身份。
        """
        person = self.db.find_authorized(face_id, "face")
        event_id = self.db.add_face_event(
            face_id=face_id, person_name=person["name"] if person else None,
            confidence=confidence, image_path=image_path,
            device_source=device_source)
        if person:
            self.grant("face", face_id, person)
            self.db.update_face_event_status(event_id, "granted", verified=True)
        else:
            self.deny("face", face_id)
            self.db.update_face_event_status(event_id, "denied", verified=False)
        return {"granted": bool(person),
                "person": person["name"] if person else None,
                "face_id": face_id, "event_id": event_id}

    # ==================== A 板事件（刷卡 / 键盘密码） ====================

    def attach_bridge(self, bridge) -> None:
        """并挂到硬件桥的事件通道上（不顶掉自动化引擎这个主订阅者）。"""
        bridge.add_listener("event", self.on_hardware_event)

    def on_hardware_event(self, event) -> None:
        if not isinstance(event, dict):
            return
        name = event.get("event")
        if name == "rfid":
            try:
                uid = normalize_uid(event.get("uid"))
            except ValueError:
                return
            if self.capture_card(uid):
                return
            self.verify("rfid", uid)
        elif name == "face" and event.get("status") == "granted":
            # 键盘密码这类在 MCP 子进程内就完成鉴权的路径：它上报的是旧
            # {"event":"face","status":"granted"} 形状，归一成统一门禁事件，
            # 「进门判定 + 延时关门」这些积木规则照旧吃得到。
            self.broadcast(GRANTED_EVENT, method=event.get("method") or "keypad",
                           person=event.get("person"),
                           credential=event.get("face_id") or event.get("uid"))

    # ==================== 房卡录入会话 ====================

    def start_card_session(self, person_id: int, name: str) -> dict:
        """开一个等待刷卡的会话；同一个人重复点复用同一个会话。"""
        with self._lock:
            self._prune_locked()
            for session in self._sessions.values():
                if session["person_id"] == person_id and session["state"] == "pending":
                    return dict(session)
            sid = uuid.uuid4().hex[:8]
            now = time.time()
            session = {"id": sid, "person_id": person_id, "name": name,
                       "state": "pending", "uid": None, "error": None,
                       "started": now, "expires_at": now + CARD_ENROLL_TTL_S}
            self._sessions[sid] = session
            logger.info("[门禁] 等待刷卡录入：%s（%.0f 秒内）", name, CARD_ENROLL_TTL_S)
            return dict(session)

    def card_session(self, sid: str) -> dict | None:
        with self._lock:
            self._prune_locked()
            session = self._sessions.get(sid)
            return dict(session) if session else None

    def cancel_card_session(self, sid: str) -> bool:
        with self._lock:
            return self._sessions.pop(sid, None) is not None

    def capture_card(self, uid: str) -> bool:
        """把这张卡交给等待最久的录入会话；没有会话在等返回 False（走鉴权）。"""
        with self._lock:
            self._prune_locked()
            waiting = sorted((s for s in self._sessions.values()
                              if s["state"] == "pending"),
                             key=lambda s: s["started"])
            if not waiting:
                return False
            session = waiting[0]
        try:
            person = self.db.set_person_rfid(session["person_id"], uid)
            state, error = ("matched" if person else "error"), \
                (None if person else "人员已不存在")
        except ValueError as e:
            person, state, error = None, "conflict", str(e)
        with self._lock:
            session["state"] = state
            session["uid"] = uid
            session["error"] = error
            session["person"] = person
        logger.info("[门禁] 房卡 %s → %s（%s）", uid, session["name"], state)
        return True

    def _prune_locked(self) -> None:
        """超时把还在等的会话判过期；结果放够时间在前面轮询取走后再回收内存。"""
        now = time.time()
        for sid, session in list(self._sessions.items()):
            if session["state"] == "pending" and now >= session["expires_at"]:
                session["state"] = "expired"
            if now >= session["expires_at"] + CARD_RESULT_KEEP_S:
                self._sessions.pop(sid, None)
