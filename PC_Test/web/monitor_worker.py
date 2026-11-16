"""One leased inference loop per web process. Always fetch a fresh camera frame."""
import threading
import time


class MonitorWorker:
    LEASE_SECONDS = 15
    RESULT_SECONDS = 5

    def __init__(self, infer):
        self.infer = infer
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.owner = None
        self.options = {}
        self.deadline = 0
        self.revision = 0
        self.result = None
        self.result_started = 0
        self.error = None
        self.thread = None

    def configure(self, owner, active, options):
        with self.lock:
            if self.owner != owner and time.monotonic() < self.deadline:
                raise RuntimeError('另一监测窗口正在使用检测服务，请先停止该窗口')
            if not active:
                self.deadline = 0
                self.result = None
                self.revision += 1
            else:
                if self.owner != owner or self.options != options or time.monotonic() >= self.deadline:
                    self.revision += 1
                    self.result = None
                self.owner = owner
                self.options = dict(options)
                self.deadline = time.monotonic() + self.LEASE_SECONDS
                if self.thread is None:
                    self.thread = threading.Thread(target=self._loop, daemon=True, name='video-monitor')
                    self.thread.start()
        self.wake.set()

    def current(self, revision):
        with self.lock:
            return revision == self.revision and time.monotonic() < self.deadline

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            age = now - self.result_started
            active = now < self.deadline
            fresh = active and self.result is not None and age < self.RESULT_SECONDS
            return {'active': active, 'result': self.result if fresh else None,
                    'age_ms': round(age * 1000) if self.result else None,
                    'ttl_ms': self.RESULT_SECONDS * 1000, 'error': self.error if active else None}

    def _loop(self):
        while True:
            with self.lock:
                active = time.monotonic() < self.deadline
                revision, options = self.revision, dict(self.options)
            if not active:
                self.wake.wait(1)
                self.wake.clear()
                continue
            started = time.monotonic()
            try:
                result = self.infer(options, lambda: self.current(revision))
                with self.lock:
                    if revision == self.revision and time.monotonic() < self.deadline:
                        self.result, self.result_started, self.error = result, started, None
            except Exception as exc:
                with self.lock:
                    if revision == self.revision:
                        self.result, self.error = None, str(exc)
            self.wake.wait(max(0, 1 - (time.monotonic() - started)))
            self.wake.clear()
