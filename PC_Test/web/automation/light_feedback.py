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
        self._calibration_samples = 0
        self._calibration_sample = None

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
            self._calibration_samples = 0
            self._calibration_sample = None
        self._sample = sample
        # Repeated evaluations of the pre-command snapshot cannot calibrate.
        # Without an off baseline, use the real sensor reading; never freeze
        # light_dark and disable photocell control just because the lamp is on.
        if self._reference is None:
            return raw
        if sample == self._transition_sample:
            return None
        if self._calibration_samples < 2:
            if sample != self._calibration_sample:
                self._offset = max(self._offset or 0, self._reference - raw, 0)
                self._calibration_samples += 1
                self._calibration_sample = sample
            # The first new sample can still contain the previous illumination
            # level. Observe two distinct frames before publishing the correction.
            self._ambient = self._reference
            return self._ambient
        self._ambient = min(1023, raw + self._offset)
        return self._ambient
