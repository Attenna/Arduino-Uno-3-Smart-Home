"""OLED 数据拉取（V2.12）：B 板每 15s 主动 oled_req，Pi 回一帧紧凑 @D... 数据。

只用内存替身，绝不打开真实串口、不启动读取线程。
"""
import json
import threading
import time
import unittest

import mcp_home_server as server


class _FakeSer:
    """只记录写入内容的最小串口替身。"""

    def __init__(self):
        self.writes = []

    def write(self, raw):
        self.writes.append(raw)


class OledFrameComposeTests(unittest.TestCase):
    def setUp(self):
        self.home = server.HomeController()   # 无串口句柄、不启线程

    def test_normal_snapshot_composes_expected_frame(self):
        self.home._snapshot = {
            "temperature": 25.3, "humidity": 61.2, "light": 479,
            "smoke": False, "rain": True, "touch": False, "motion": True,
        }
        self.assertEqual(self.home._compose_oled_frame(12),
                         b"@D12,253,612,479,0,1,0,1\n")

    def test_empty_snapshot_uses_null_sentinels(self):
        self.home._snapshot = {}
        self.assertEqual(self.home._compose_oled_frame(0),
                         b"@D0,-32768,-32768,0,0,0,0,0\n")

    def test_missing_dht_uses_sentinel_but_keeps_light(self):
        self.home._snapshot = {"temperature": None, "humidity": None, "light": 300}
        self.assertEqual(self.home._compose_oled_frame(7),
                         b"@D7,-32768,-32768,300,0,0,0,0\n")

    def test_light_is_clamped_to_0_1023(self):
        self.home._snapshot = {"light": 99999}
        self.assertTrue(self.home._compose_oled_frame(1).startswith(b"@D1,-32768,-32768,1023,"))
        self.home._snapshot = {"light": -5}
        self.assertTrue(self.home._compose_oled_frame(1).startswith(b"@D1,-32768,-32768,0,"))

    def test_frame_fits_uno_rx_buffer(self):
        # 极端值（负温度、大湿度、满量程光照、全 1 标志）也不能超过 64B
        self.home._snapshot = {
            "temperature": -12.3, "humidity": 99.9, "light": 1023,
            "smoke": True, "rain": True, "touch": True, "motion": True,
        }
        frame = self.home._compose_oled_frame(65535)
        self.assertLess(len(frame), 64)


class OledRequestDispatchTests(unittest.TestCase):
    def setUp(self):
        self.home = server.HomeController()   # 无串口句柄、不启线程
        self.ser = _FakeSer()
        self.home.ser_b = self.ser
        self.home._snapshot = {
            "temperature": 25.3, "humidity": 61.2, "light": 479,
            "smoke": False, "rain": True, "touch": False, "motion": True,
        }

    def test_oled_req_writes_expected_frame(self):
        self.home._dispatch_b_frame({"type": "oled_req", "id": 9}, "")
        self.assertEqual(self.ser.writes, [b"@D9,253,612,479,0,1,0,1\n"])
        # 写完必须释放 _b_lock（否则后续命令永远拿不到锁）
        self.assertTrue(self.home._b_lock.acquire(blocking=False))
        self.home._b_lock.release()

    def test_oled_req_drops_frame_when_lock_busy_without_blocking(self):
        # 模拟正有命令持锁等响应：oled 回帧必须直接丢弃且立刻返回
        self.home._b_lock.acquire()
        try:
            t0 = time.monotonic()
            self.home._dispatch_b_frame({"type": "oled_req", "id": 3}, "")
            elapsed = time.monotonic() - t0
        finally:
            self.home._b_lock.release()
        self.assertEqual(self.ser.writes, [])
        self.assertLess(elapsed, 0.2)

    def test_oled_req_does_not_wake_command_waiter(self):
        self.home._b_waiter = True
        self.home._b_waiter_id = 9
        self.home._b_expect = ("response",)
        self.home._dispatch_b_frame({"type": "oled_req", "id": 9}, "")
        self.assertFalse(self.home._b_resp_event.is_set())
        self.assertIsNone(self.home._b_resp)

    def test_oled_req_ignored_without_serial(self):
        self.home.ser_b = None
        self.home._dispatch_b_frame({"type": "oled_req", "id": 1}, "")  # 不抛异常
        self.assertEqual(self.ser.writes, [])


class OledResetCooldownTests(unittest.TestCase):
    """B 板复位后的 OLED 冷却：复位抖动期间不回轮播数据帧（issue #58）。"""

    def setUp(self):
        self.home = server.HomeController()   # 无串口句柄、不启线程
        self.ser = _FakeSer()
        self.home.ser_b = self.ser
        self.home._snapshot = {"temperature": 25.3, "light": 479}

    def test_no_reset_seen_is_not_held(self):
        self.assertFalse(self.home._oled_hold_active())
        self.home._dispatch_b_frame({"type": "oled_req", "id": 1}, "")
        self.assertEqual(len(self.ser.writes), 1)

    def test_recent_reset_suspends_the_frame(self):
        self.home._b_last_reset_ts = time.time()
        self.home._dispatch_b_frame({"type": "oled_req", "id": 2}, "")
        self.assertEqual(self.ser.writes, [])

    def test_frame_resumes_after_the_cooldown(self):
        self.home._b_last_reset_ts = time.time() - (server._OLED_RESET_COOLDOWN_S + 1)
        self.home._dispatch_b_frame({"type": "oled_req", "id": 3}, "")
        self.assertEqual(len(self.ser.writes), 1)

    def test_another_reset_restarts_the_cooldown(self):
        self.home._b_last_reset_ts = time.time() - (server._OLED_RESET_COOLDOWN_S + 1)
        self.home._dispatch_b_frame({"type": "ready"}, "")   # 又复位了一次
        self.home._dispatch_b_frame({"type": "oled_req", "id": 4}, "")
        self.assertEqual(self.ser.writes, [])


if __name__ == "__main__":
    unittest.main()