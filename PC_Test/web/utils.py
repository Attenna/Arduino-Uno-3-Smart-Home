"""通用工具：重试装饰器、请求节流、安全 Base64 解码、连接健康追踪。

合并自别组 smart_home/utils.py，供 face 引擎与 HA 客户端复用。
"""
import base64
import functools
import logging
import threading
import time

logger = logging.getLogger(__name__)


# ==================== 重试装饰器（指数退避） ====================

def retry_with_backoff(max_retries=3, base_delay=0.5, max_delay=8.0,
                       exceptions=(Exception,), on_retry=None):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt >= max_retries:
                        raise
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    if on_retry:
                        on_retry(attempt + 1, delay, e)
                    logger.warning("Retry %s/%s for %s after %.1fs: %s",
                                   attempt + 1, max_retries, func.__name__, delay, e)
                    time.sleep(delay)
        return wrapper
    return decorator


# ==================== 请求节流器 ====================

class RequestThrottler:
    """防止人脸识别等高频请求短时间内堆积。"""

    def __init__(self, min_interval=2.0):
        self.min_interval = min_interval
        self._last_request_time = 0
        self._lock = threading.Lock()

    def can_execute(self):
        with self._lock:
            now = time.time()
            if now - self._last_request_time >= self.min_interval:
                self._last_request_time = now
                return True
            return False

    def time_until_next(self):
        with self._lock:
            return max(0, self.min_interval - (time.time() - self._last_request_time))


# ==================== 安全 Base64 解码 ====================

def safe_base64_decode(image_base64, max_size_mb=5):
    """安全解码 Base64 图片（限制大小，防止内存攻击）。"""
    if ',' in image_base64:
        image_base64 = image_base64.split(',', 1)[1]
    max_encoded_len = int(max_size_mb * 1024 * 1024 * 4 / 3)
    if len(image_base64) > max_encoded_len:
        raise ValueError("Image too large: exceeds limit")
    try:
        return base64.b64decode(image_base64)
    except Exception as e:
        raise ValueError(f"Invalid base64 data: {e}")


# ==================== 连接状态管理 ====================

class ConnectionHealth:
    """跟踪外部服务（MCP/HA/人脸引擎）的连接健康状态。"""

    def __init__(self, name="service"):
        self.name = name
        self.connected = False
        self.last_success = None
        self.last_failure = None
        self.failure_count = 0
        self.consecutive_failures = 0
        # 可重入锁：get_status() 持锁期间会调用 is_healthy()
        self._lock = threading.RLock()

    def record_success(self):
        with self._lock:
            self.connected = True
            self.last_success = time.time()
            self.consecutive_failures = 0
            self.failure_count = 0

    def record_failure(self, error=None):
        with self._lock:
            self.connected = False
            self.last_failure = time.time()
            self.consecutive_failures += 1
            self.failure_count += 1
            if self.consecutive_failures <= 3 or self.consecutive_failures % 10 == 0:
                logger.warning("%s connection failed (%sx): %s",
                               self.name, self.consecutive_failures, error)

    def is_healthy(self, max_failures=5):
        with self._lock:
            return self.connected or self.consecutive_failures < max_failures

    def get_status(self):
        with self._lock:
            return {
                'connected': self.connected,
                'consecutive_failures': self.consecutive_failures,
                'total_failures': self.failure_count,
                'last_success': self.last_success,
                'last_failure': self.last_failure,
                'is_healthy': self.is_healthy(),
            }
