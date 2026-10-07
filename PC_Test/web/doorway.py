"""Independent, fresh distance channel for the B-board doorway sensor."""
import math
import threading
import time


class DoorwayDistance:
    MAX_AGE = 3.0

    def __init__(self):
        self.lock = threading.Lock()
        self.received = None
        self.value = None
        self.status = "waiting"

    def update(self, payload):
        with self.lock:
            now = time.monotonic()
            interrupted = self.received is None or now - self.received > self.MAX_AGE
            payload = payload if isinstance(payload, dict) else {}
            value = payload.get("distance_cm")
            valid = (payload.get("valid") is True and payload.get("status") == "ok"
                     and type(value) in (int, float) and math.isfinite(value)
                     and 2 <= value <= 400)
            self.value = float(value) if valid else None
            self.status = "ok" if valid else "unavailable"
            self.received = now
            return interrupted

    def snapshot(self):
        with self.lock:
            fresh = self.received is not None and time.monotonic() - self.received <= self.MAX_AGE
            value = self.value if fresh else None
            return {"distance_cm": value, "valid": value is not None,
                    "status": self.status if fresh else "stale"}
