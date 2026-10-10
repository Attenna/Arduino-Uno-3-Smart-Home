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
# 同一凭证在这段窗口内的重复读数只算一次通行。实测一张卡放在 RC522 上会连着
# 上报两次（间隔 51ms），不去抖就是「一次放卡开两次门」。
# 去抖只抑制「重复的开门/记账动作」，不抑制 face_events 历史行：每轮识别各自成行
# （见 handle_face_result），否则同一人站 30 秒会被合并成一条、不同陌生人共用空
# face_id 也会互相顶掉。可通过 face.watcher.repeat_window 配置，见 docs/configuration.md。
REPEAT_WINDOW_S = 8.0
# 环境类观测（没人/没摄像头/没录身份）会按取帧间隔反复出现：只在「种类变化」时留痕，
# 否则每 2 秒一行会把门禁页刷满。
AMBIENT_OBSERVATION_KINDS = frozenset({"idle", "no_camera", "no_identity"})

GRANTED_EVENT = {"event": "access", "status": "granted"}
DENIED_EVENT = {"event": "access", "status": "denied"}

# 被拒原因的双语说法：通行日志与门禁页直接用它，不再统一写成「未知人员」
DENY_REASONS = {
    "no_such_identity": ("凭证未登记", "Credential not enrolled"),
    "disabled": ("人员已停用", "Person disabled"),
    "ambiguous": ("多个人员共用该凭证", "Credential shared by several persons"),
    "bad_credential": ("凭证无效", "Invalid credential"),
    "identity_not_in_list": ("人脸库有此身份，名单里没有对应人员",
                             "Face identity exists but no matching person"),
    "unmatched_face": ("有人脸，但没匹配到任何已录身份",
                       "Face detected but matched no enrolled identity"),
}


def deny_texts(reason: str | None) -> tuple[str, str]:
    """被拒原因的中英文案；未知代码原样返回，免得页面显示空白。"""
    if not reason:
        return ("", "")
    return DENY_REASONS.get(reason, (reason, reason))


class AccessGuard:
    def __init__(self, db):
        self.db = db
        # 事件出口（extensions 接线时指向 automation.on_event）；
        # 纯看板模式没有串口时是 None —— 照样记账，只是没有规则可触发。
        self.event_sink = None
        # 「人脸库里有没有这个身份」的探针（extensions 接线成 face_engine.has_identity）：
        # 用来把「这张脸没录过」和「录过但名单里查不到人」分开说。
        self.identity_check = None
        # 重复识别去抖窗口（秒）：只挡重复开门动作，不挡历史事件，见 configure()。
        self.repeat_window = REPEAT_WINDOW_S
        # 上一条观测轮次的种类：环境类观测据此做「变化才留痕」的去抖。
        self._observation_kind: str | None = None
        self._sessions: dict[str, dict] = {}
        # (method, credential) → {"ts":..., "repeats":n}：短窗口内重复读数的合并账
        self._recent: dict[tuple[str, str], dict] = {}
        self._lock = threading.Lock()

    def configure(self, cfg: dict | None) -> None:
        """读取门禁相关配置：``face.watcher.repeat_window`` 决定重复识别去抖窗口。

        窗口只影响「同一凭证重复读数算一次通行动作」，不影响 face_events 历史留痕。
        """
        opts = ((cfg or {}).get("face") or {}).get("watcher") or {}
        try:
            self.repeat_window = max(0.0, float(
                opts.get("repeat_window", REPEAT_WINDOW_S)))
        except (TypeError, ValueError):
            self.repeat_window = REPEAT_WINDOW_S

    # ==================== 事件出口 ====================

    def broadcast(self, base: dict, **fields) -> None:
        sink = self.event_sink
        if sink is None:
            return
        event = dict(base)
        event.update({k: v for k, v in fields.items() if v not in (None, "")})
        # R15：补一个毫秒级时间戳，让自动化引擎的事件去重（按 `event@ts`）对门禁事件
        # 也生效——此前门禁事件不带 ts，只能靠 access_guard 自己的 8s 去抖兜底。
        event.setdefault("ts", time.time())
        try:
            sink(event)
        except Exception as e:                        # noqa: BLE001
            logger.warning("[门禁] 事件广播失败: %s", e)

    # ==================== 重复读数合并 ====================

    def merge_repeat(self, method: str, credential: str) -> int:
        """返回本次之前同一凭证已合并掉的次数；0 表示这是窗口内的第一次。"""
        key = (method, credential or "")
        now = time.time()
        with self._lock:
            for stale in [k for k, v in self._recent.items()
                          if now - v["ts"] > self.repeat_window]:
                self._recent.pop(stale, None)
            entry = self._recent.get(key)
            if entry is None:
                self._recent[key] = {"ts": now, "repeats": 0}
                return 0
            entry["repeats"] += 1
            return entry["repeats"]

    def recent_repeats(self) -> list[dict]:
        """当前还在去抖窗口里的凭证（门禁页用来解释「为什么没再开一次门」）。"""
        now = time.time()
        with self._lock:
            return [{"method": m, "credential": c, "repeats": v["repeats"],
                     "age_s": round(now - v["ts"], 1)}
                    for (m, c), v in self._recent.items()
                    if now - v["ts"] <= self.repeat_window]

    # ==================== 鉴权 ====================

    def verify(self, method: str, credential: str, debounce: bool = True):
        """按白名单鉴权一个凭证，写通行日志并广播结果；返回命中的人员或 None。"""
        reason, person = self.db.diagnose(credential, method)
        matched = reason == "matched"
        if debounce and self.merge_repeat(method, credential):
            return person if matched else None
        if matched:
            self.grant(method, credential, person)
            return person
        self.deny(method, credential, reason=reason, person=person)
        return None

    def grant(self, method: str, credential: str, person: dict) -> None:
        self.db.add_access_log(person["name"], method, "granted",
                               credential=credential)
        self.broadcast(GRANTED_EVENT, method=method, person=person["name"],
                       credential=credential)
        logger.info("[门禁] %s 通过：%s（%s）", method, person["name"], credential)

    def deny(self, method: str, credential: str, reason: str | None = None,
             person: dict | None = None) -> None:
        """被拒也要说清为什么：只写「未知人员」时用户没法判断该录脸还是该启用人员。"""
        label = (person or {}).get("name") or "未知人员"
        self.db.add_access_log(label, method, "denied", credential=credential,
                               deny_reason=reason)
        self.broadcast(DENIED_EVENT, method=method, credential=credential)
        logger.info("[门禁] %s 被拒：%s（%s）", method, credential,
                    reason or "unspecified")

    def handle_face_result(self, face_id: str, confidence=None, image_path: str = "",
                           device_source: str = "web", debounce: bool = True,
                           score=None, detection_confidence=None,
                           record_only: bool = False) -> dict:
        """识别结果统一入口：记一次识别事件 → 鉴权 → 广播。

        调用方是 ``POST /api/face/notify``（边缘设备推送）、``web/face_watcher.py``
        的门口识别哨兵，以及 ``POST /api/face/recognize`` 的下游使用者；网页端不猜身份。

        ``face_id`` 为空表示「画面里有人脸但没匹配到任何已录身份」（陌生人）。
        ``score`` 是 ArcFace 身份相似度；``detection_confidence`` 是 YOLO 人脸检出
        置信度。旧调用方的 ``confidence`` 仅兼容存档，不再作为页面的识别分数。

        每一轮识别都无条件落一条终态事件（``granted`` / ``denied``），不再因去抖或
        冷却被静默丢弃；``debounce`` 与 ``record_only`` 只抑制「重复开门 + 重复通行
        日志」这个动作，抑制时返回 ``duplicate=True`` 但仍带 ``event_id``。
        """
        face_id = face_id or ""
        if face_id:
            reason, person = self.db.diagnose(face_id, "face")
            if (reason == "no_such_identity" and self.identity_check
                    and self.identity_check(face_id)):
                reason = "identity_not_in_list"
        else:
            reason, person = "unmatched_face", None
        matched = reason == "matched"
        # 一次识别收尾后，下一条环境观测（idle/no_camera 等）重新算「种类变化」，
        # 保证「有人来→又没人」在历史里表现为两段，而不是被上一段 idle 顶掉。
        with self._lock:
            self._observation_kind = None
        # 判定结果一次落终态：过去先插 pending 再用第二条事务更新，放行瞬间前端会把
        # pending 当成「已拒绝」，且进程中途退出时行会永久停在 pending。
        event_id = self.db.add_face_event(
            face_id=face_id, person_name=(person or {}).get("name"),
            confidence=confidence, image_path=image_path,
            device_source=device_source, score=score,
            detection_confidence=detection_confidence,
            status="granted" if matched else "denied", verified=matched,
            deny_reason=None if matched else reason)
        # 去抖/冷却只挡动作（开门广播 + access_logs），不挡上面那条历史事件
        suppressed = record_only or bool(
            debounce and self.merge_repeat("face", face_id))
        if not suppressed:
            if matched:
                self.grant("face", face_id, person)
            else:
                self.deny("face", face_id, reason=reason, person=person)
        return {"granted": matched, "duplicate": suppressed,
                "person": person["name"] if matched else None,
                "face_id": face_id, "event_id": event_id, "reason": reason}

    def record_observation(self, kind: str, face_id: str = "",
                           image_path: str = "", device_source: str = "face_watcher",
                           score=None, detection_confidence=None) -> int | None:
        """记一轮「没有可鉴权身份」的观测：太远/节流/无脸/未唤醒/摄像头失败等。

        这些轮次没有凭证可鉴定，过去在 ``face_watcher.inspect_once`` 里直接 return、
        完全不落库，导致门禁页与实际识别对不上。现在写一条 ``status='observed'``、
        ``deny_reason=kind`` 的事件留痕（不写通行日志、不广播门禁事件），页面据此说明
        「这一轮为什么没有结果」。命中环境去抖（同一环境状态重复出现）时返回 ``None``。

        环境类观测（``AMBIENT_OBSERVATION_KINDS``）会按取帧间隔反复出现，逐轮落库等于
        每 2 秒刷一行；只在「本轮种类与上一条观测不同」时记一条，其余轮次跳过。
        """
        with self._lock:
            if kind in AMBIENT_OBSERVATION_KINDS and kind == self._observation_kind:
                return None
            self._observation_kind = kind
        return self.db.add_face_event(
            face_id=face_id or "", person_name=None, image_path=image_path,
            device_source=device_source, score=score,
            detection_confidence=detection_confidence,
            status="observed", verified=False, deny_reason=kind)

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
                self.fail_pending_card("读卡器返回了无效卡号，请移开卡片后重试")
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
            if not session:
                return None
            out = dict(session)
            now = time.time()
            out["age_seconds"] = max(0.0, now - session["started"])
            out["remaining_seconds"] = max(0.0, session["expires_at"] - now)
            return out

    def fail_pending_card(self, error: str) -> bool:
        """让最早的等待会话立即失败，避免坏串口事件最终只表现成超时。"""
        with self._lock:
            self._prune_locked()
            waiting = sorted((s for s in self._sessions.values()
                              if s["state"] == "pending"),
                             key=lambda s: s["started"])
            if not waiting:
                return False
            waiting[0]["state"] = "error"
            waiting[0]["error"] = error
            logger.warning("[门禁] 房卡录入失败：%s", error)
            return True

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
                session["error"] = "等待刷卡超时，未收到有效 RFID 事件"
            if now >= session["expires_at"] + CARD_RESULT_KEEP_S:
                self._sessions.pop(sid, None)
