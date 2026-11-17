"""Keep the lamp's own illumination out of ambient-light decisions."""
import math
import threading


class LightFeedbackGuard:
    def __init__(self):
        self._lock = threading.Lock()
        self._output = None
        self._sample = None
        self._transition_sample = None
        self._ambient = None
        self._reference = None
        self._offset = None

    def update(self, raw, status, sample):
        with self._lock:
            return self._update(raw, status, sample)

    def _update(self, raw, status, sample):
        if (isinstance(raw, bool) or not isinstance(raw, (int, float))
                or not math.isfinite(raw) or not 0 <= raw <= 1023):
            return None
        on = status.get("light_status") == "on" and status.get("light_brightness", 0) > 0
        output = (tuple(status.get(k) for k in (
            "light_brightness", "light_mode", "light_temp", "light_rgb", "light_count"))
            if on else None)
        if output is None:
            self._output = None
            self._offset = None
            self._ambient = raw
            self._sample = sample
            return raw
        if output != self._output:
            self._reference = self._ambient
            self._offset = None
            self._transition_sample = self._sample
            self._output = output
        self._sample = sample
        # Repeated rule evaluations of the pre-command snapshot cannot calibrate
        # the lamp. At startup with an already-lit lamp there is no off baseline;
        # preserve it until it is switched off instead of inventing ambient light.
        if self._reference is None:
            return None
        if self._offset is None:
            if sample == self._transition_sample:
                return None
            self._offset = max(0, self._reference - raw)
        self._ambient = min(1023, raw + self._offset)
        return self._ambient
