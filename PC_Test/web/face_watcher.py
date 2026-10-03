"""门口人脸识别哨兵：把「摄像头 → 识别 → 鉴权」这一段真正接起来。

摄像头服务只出 MJPEG 流，识别模型只装在 web 进程里，两边过去都没有人取帧，
所以「录进人脸也不会自动开门」。本模块补上这个缺失的生产者：

    PIR(motion) 有人 → 取摄像头最新一帧 → FaceEngine.recognize_jpeg
        → 认出身份 → AccessGuard.handle_face_result() → access_granted / access_denied
        → 积木规则（access_open_door / access_auto_close / access_denied_buzzer）决定开不开门

默认只在 PIR 报「有人」之后的保持窗口里抓帧：派上只有一个 CPU 核，常驻跑 YOLO
会把语音和传感器轮询一起拖死；没收到过 motion（纯看板 / 没接 A 板）时退化为常转，
免得那种场景下永远不动作。识别结果一律交给 access_guard，这里不鉴权、不开门。
"""
from __future__ import annotations

import logging
import os
import threading
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# 距上次收到 motion 超过这么久就当「A 板不报这个传感器了」，退化成不门控
MOTION_STALE_S = 120.0
GRAB_TIMEOUT_S = 3.0
DEFAULTS = {"enabled": True, "interval": 2.0, "motion_gate": True,
            "motion_hold": 20.0, "cooldown": 60.0, "min_face_px": 60}


def resolve_snapshot_url(cfg: dict) -> str:
    """从摄像头流地址推出单帧快照地址：.../video_feed → .../snapshot。

    优先级与 web/api/camera.py 一致（环境变量 SMART_HOME_CAMERA_URL 覆盖配置），
    两处必须同源，否则代理给页面的是一个摄像头、识别用的是另一个。
    """
    url = (os.environ.get("SMART_HOME_CAMERA_URL") or "").strip() or \
        str(((cfg or {}).get("camera") or {}).get("stream_url") or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc,
                       parts.path.rsplit("/", 1)[0] + "/snapshot", "", ""))


def _face_area(face: dict) -> int:
    box = face.get("bbox") or {}
    return max(0, box.get("x2", 0) - box.get("x1", 0)) * \
        max(0, box.get("y2", 0) - box.get("y1", 0))


class FaceWatcher:
    def __init__(self, engine, guard, cfg: dict | None = None):
        self.engine = engine
        self.guard = guard
        self.configure(cfg)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._motion: bool | None = None
        self._motion_ts = 0.0
        self._active_until = 0.0
        self._cooldowns: dict[str, float] = {}
        self._counts = {"idle": 0, "attempts": 0, "faces": 0, "granted": 0,
                        "denied": 0, "strangers": 0, "errors": 0}
        self._last: dict | None = None
        self._camera_error: str | None = None

    def configure(self, cfg: dict | None) -> None:
        """读取 face.watcher 配置；摄像头地址与 /api/camera/stream 同源解析。"""
        opts = {**DEFAULTS, **(((cfg or {}).get("face") or {}).get("watcher") or {})}
        self.enabled = bool(opts["enabled"])
        self.interval = max(0.5, float(opts["interval"]))
        self.motion_gate = bool(opts["motion_gate"])
        self.motion_hold = max(0.0, float(opts["motion_hold"]))
        self.cooldown = max(0.0, float(opts["cooldown"]))
        self.min_face_px = max(0, int(opts["min_face_px"]))
        self.snapshot_url = resolve_snapshot_url(cfg or {})

    # ==================== 启停 ====================

    def start(self, cfg: dict | None = None) -> bool:
        if cfg is not None:
            self.configure(cfg)
        if not self.enabled:
            logger.info("[识别哨兵] 配置里已关闭（face.watcher.enabled=false）")
            return False
        if self._thread is not None:
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="face-watcher",
                                        daemon=True)
        self._thread.start()
        logger.info("[识别哨兵] 已启动：每 %.1f 秒取一帧，%s，快照 %s",
                    self.interval,
                    f"PIR 门控（保持 {self.motion_hold:.0f} 秒）" if self.motion_gate
                    else "不门控",
                    self.snapshot_url or "未配置")
        return True

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.interval + GRAB_TIMEOUT_S + 1.0)

    def attach_bridge(self, bridge) -> None:
        """订阅 A 板快照拿 PIR；不顶掉自动化引擎这个主订阅者。"""
        bridge.add_listener("snapshot", self.on_snapshot)

    def on_snapshot(self, data) -> None:
        if not isinstance(data, dict) or "motion" not in data:
            return
        motion = bool(data.get("motion"))
        now = time.time()
        with self._lock:
            self._motion = motion
            self._motion_ts = now
            if motion:
                self._active_until = now + self.motion_hold

    # ==================== 主循环 ====================

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.inspect_once()
            except Exception as e:                        # noqa: BLE001
                # 一次失败不能杀死线程：摄像头拔了、模型抛异常都得继续等下一帧
                logger.warning("[识别哨兵] 本轮异常: %s", e)
                self._note("error", detail=str(e))
                self._bump("errors")

    def inspect_once(self) -> dict:
        """跑一轮判定，返回这一轮的说明（测试与状态面板都吃它）。"""
        gate_open, gate_mode = self.gate_state()
        if not gate_open:
            self._bump("idle")
            return self._note("idle", gate=gate_mode)
        if not self.snapshot_url:
            return self._note("no_camera", detail="未配置摄像头流地址")
        if self.engine.identity_count() == 0:
            # 一个身份都没录就常驻抓帧，只会把日志刷满「陌生人」
            return self._note("no_identity")
        blob = self.grab_frame()
        if blob is None:
            return self._note("no_camera")
        self._bump("attempts")
        result = self.engine.recognize_jpeg(blob)
        if result.get("error"):
            self._bump("errors")
            return self._note("error", detail=str(result["error"]))
        if result.get("mode") == "throttled":
            return self._note("throttled")
        if not result.get("detected"):
            return self._note("no_face")
        self._bump("faces")
        faces = result.get("faces") or []
        face_id = result.get("face_id") or ""
        target = next((f for f in faces if f.get("face_id") == face_id), None) \
            or max(faces, key=_face_area, default={})
        box = target.get("bbox") or {}
        side = min(box.get("x2", 9999) - box.get("x1", 0),
                   box.get("y2", 9999) - box.get("y1", 0))
        if side and side < self.min_face_px:
            return self._note("too_far", face_px=int(side))
        until = self._cooldowns.get(face_id, 0.0)
        if face_id and time.time() < until:
            # 开门后人还在门口站着：不重复放行，否则一次停留开好几次门
            return self._note("cooldown", face_id=face_id,
                              until=round(until - time.time(), 1))
        outcome = self.guard.handle_face_result(
            face_id, confidence=result.get("confidence"),
            device_source="face_watcher")
        if outcome.get("duplicate"):
            return self._note("duplicate", face_id=face_id)
        if outcome.get("granted"):
            self._bump("granted")
            self._cooldowns[face_id] = time.time() + self.cooldown
            return self._note("granted", face_id=face_id,
                              person=outcome.get("person"),
                              confidence=result.get("confidence"))
        if not face_id:
            self._bump("strangers")
        self._bump("denied")
        return self._note("denied", face_id=face_id,
                          reason=outcome.get("reason"),
                          person_name=(outcome.get("person")))

    def grab_frame(self) -> bytes | None:
        try:
            with urllib.request.urlopen(self.snapshot_url,
                                        timeout=GRAB_TIMEOUT_S) as resp:
                blob = resp.read()
        except Exception as e:                            # noqa: BLE001
            detail = f"取帧失败: {e}"
            if detail != (self._camera_error or ""):
                logger.warning("[识别哨兵] %s（%s）", detail, self.snapshot_url)
            self._camera_error = detail
            self._note("no_camera", detail=str(e))
            return None
        if self._camera_error:
            logger.info("[识别哨兵] 摄像头恢复：%s", self.snapshot_url)
        self._camera_error = None
        return blob or None

    # ==================== 状态（给前端的提示用） ====================

    def gate_state(self) -> tuple[bool, str]:
        """(是否该抓帧, 门控说明) —— mode 供页面解释「为什么现在没在识别」。"""
        now = time.time()
        with self._lock:
            seen = self._motion is not None and now - self._motion_ts <= MOTION_STALE_S
            motion = self._motion
            active = now < self._active_until
        if not (self.motion_gate and seen):
            return True, "always"
        return (active, "motion_active" if motion else "motion_idle")

    def state(self) -> dict:
        now = time.time()
        gate_open, gate_mode = self.gate_state()
        with self._lock:
            motion_age = (round(now - self._motion_ts, 1)
                          if self._motion is not None else None)
        last = dict(self._last or {})
        if last.get("ts"):
            last["age_s"] = round(now - last.pop("ts"), 1)
        return {
            "enabled": self.enabled,
            "running": bool(self._thread and self._thread.is_alive()),
            "interval": self.interval,
            "cooldown": self.cooldown,
            "min_face_px": self.min_face_px,
            "snapshot_url": self.snapshot_url,
            "gate": {"open": gate_open, "mode": gate_mode,
                     "motion": self._motion, "motion_age_s": motion_age,
                     "gated": self.motion_gate},
            "camera_error": self._camera_error,
            "model_ready": bool(getattr(self.engine, "recognizer", None)),
            "identities": self.engine.identity_count(),
            "last": last or None,
            "counts": dict(self._counts),
        }

    def _bump(self, key: str) -> None:
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1

    def _note(self, kind: str, **fields) -> dict:
        entry = {"kind": kind, "ts": time.time(), **fields}
        with self._lock:
            self._last = entry
        if kind == "granted":
            logger.info("[识别哨兵] 认出 %s → 已交鉴权", entry.get("person"))
        elif kind == "denied":
            logger.info("[识别哨兵] 拒绝（%s）：%s",
                        entry.get("reason"), entry.get("face_id") or "陌生人")
        return entry
