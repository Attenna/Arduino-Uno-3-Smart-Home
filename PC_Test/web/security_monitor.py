"""Suspicious activity evidence, independent of indoor occupancy and face recognition."""
from __future__ import annotations

import json
import math
import logging
import queue
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .face_watcher import resolve_snapshot_url

logger = logging.getLogger(__name__)


class DoorwayDwell:
    """Future doorway sensor: distinct field, valid fresh samples, one event per visit."""
    def __init__(self, enabled=False, distance_cm=100, hold_sec=30, max_gap_sec=5):
        if not isinstance(enabled, bool):
            raise ValueError("doorway.enabled must be boolean")
        for value in (distance_cm, hold_sec, max_gap_sec):
            if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError("doorway thresholds must be finite positive numbers")
        self.enabled = enabled
        self.distance_cm = float(distance_cm)
        self.hold_sec = float(hold_sec)
        self.max_gap_sec = float(max_gap_sec)
        self.since = self.last = None
        self.fired = False

    def feed(self, value, now=None):
        now = time.monotonic() if now is None else now
        valid = (self.enabled and isinstance(value, (float, int))
                 and not isinstance(value, bool) and math.isfinite(value)
                 and 0 < value <= self.distance_cm)
        if not valid or (self.last is not None and now - self.last > self.max_gap_sec):
            self.since = None
            self.fired = False
        self.last = now
        if not valid:
            return False
        if self.since is None:
            self.since = now
        if not self.fired and now - self.since >= self.hold_sec:
            self.fired = True
            return True
        return False


class SecurityMonitor:
    def __init__(self, directory, cfg=None):
        self.directory = Path(directory)
        self.snapshot_url = resolve_snapshot_url(cfg or {})
        opts = ((cfg or {}).get("security") or {}).get("doorway") or {}
        self.dwell = DoorwayDwell(**opts)
        self.pending = queue.Queue(maxsize=16)
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread is None:
            for event in self.events(limit=None):
                if event.get("capture") == "pending":
                    event.update(capture="failed", error="服务重启中断拍照")
                    self._save(event)
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._loop, daemon=True, name="security-photo")
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None

    def on_event(self, event):
        if (event.get("event") == "password_result" and event.get("status") == "denied"
                and isinstance(event.get("failures"), int) and event["failures"] >= 3):
            self.record("keypad_failures", {"failures": event["failures"]})

    def on_snapshot(self, data):
        # Never substitute indoor motion or a legacy distance for the doorway sensor.
        if self.dwell.feed(data.get("doorway_distance_cm")):
            self.record("doorway_dwell", {"distance_cm": data["doorway_distance_cm"],
                                         "hold_sec": self.dwell.hold_sec})

    def _save(self, event):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (event["id"] + ".json")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def record(self, reason, details):
        event = {"id": uuid.uuid4().hex, "timestamp": datetime.now(timezone.utc).isoformat(),
                 "status": "suspicious", "reason": reason, "details": details,
                 "capture": "pending", "image": None}
        self._save(event)
        try:
            self.pending.put_nowait(event)
        except queue.Full:
            event["capture"] = "failed"
            event["error"] = "拍照队列已满"
            self._save(event)
        return event

    def capture(self, event):
        try:
            if not self.snapshot_url:
                raise ValueError("未配置摄像头")
            with urllib.request.urlopen(self.snapshot_url, timeout=3) as response:
                blob = response.read(5 * 1024 * 1024 + 1)
            if len(blob) > 5 * 1024 * 1024 or not blob.startswith(b"\xff\xd8"):
                raise ValueError("摄像头未返回有效 JPEG")
            filename = event["id"] + ".jpg"
            (self.directory / filename).write_bytes(blob)
            event.update(capture="saved", image=filename,
                         captured_at=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            event.update(capture="failed", error=str(exc))
        self._save(event)

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                event = self.pending.get(timeout=.5)
            except queue.Empty:
                continue
            try:
                self.capture(event)
            except Exception:
                logger.exception("无法保存可疑行为照片记录")
            finally:
                self.pending.task_done()

    def events(self, limit=100):
        paths = sorted(self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        events = []
        for path in paths[:limit]:
            try:
                events.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                logger.warning("无法读取事件记录 %s", path.name)
        return events
