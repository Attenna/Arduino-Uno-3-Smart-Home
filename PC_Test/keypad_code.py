"""Fixed-length keypad attempts; no entered digits are exposed in events."""
import time


class KeypadCode:
    def __init__(self, code, window=10):
        self.code = str(code)
        self.window = window
        self.buffer = ""
        self.last = None
        self.failures = 0

    def feed(self, key, now=None):
        now = time.monotonic() if now is None else now
        if self.last is not None and now - self.last > self.window:
            self.buffer = ""
        self.last = now
        if key == "*":
            self.buffer = ""
            return None
        if key == "#":
            if not self.buffer:
                return None
        elif key in "0123456789" and len(key) == 1:
            self.buffer += key
            if len(self.buffer) < len(self.code):
                return None
        else:
            return None
        granted = self.buffer == self.code
        self.buffer = ""
        self.failures = 0 if granted else self.failures + 1
        return {"event": "password_result", "status": "granted" if granted else "denied",
                "method": "keypad", "failures": self.failures}
