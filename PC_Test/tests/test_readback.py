# -*- coding: utf-8 -*-
"""B 板硬件回读 vs 命令下发值的比对（issue #30）。

重点：灯光的回读是**缩放后的峰值电平百分比**，不是命令亮度本身。暗色
（峰值 < 255）此前会被长期误报「命令未生效」。这里既锁住「暗色不误报」，
也锁住「真失效仍报得出来」，避免只验一半。
"""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web import light_state as ls
from web.readback import CMD_SETTLE_S, RB_FRESH_S, output_mismatch


def _iso(seconds_ago=0):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def status(**over):
    """一条「回读新鲜、已过稳定期」的 status 行，可按需覆盖。"""
    row = {
        "rb_seen_at": _iso(0),
        "output_last_seen": _iso(CMD_SETTLE_S + 5),
        # 门/窗/风扇默认一致
        "door_status": "closed", "rb_door_status": "closed",
        "window_status": "closed", "rb_window_status": "closed",
        "fan_speed": 50, "rb_fan_speed": 50,
        # 灯光默认：白光 100%
        "light_brightness": 100, "light_mode": "white",
        "light_temp": None, "light_rgb": None, "rb_light_brightness": 100,
    }
    row.update(over)
    return row


def light_mismatch(row):
    return [m for m in output_mismatch(row) if m["device"] == "light"]


# 五种亮法：mode, temp, rgb
STYLES = [
    ("white", None, None),
    ("night", None, None),
    ("temp", 4000, None),
    ("rgb", None, (255, 0, 128)),   # 峰值 = 255
    ("rgb", None, (100, 50, 20)),   # 峰值 < 255（暗色，issue #30 的复现色）
]


class ExpectedReadbackTests(unittest.TestCase):
    """期望回读值要和固件上报口径一致。"""

    def test_dark_rgb_matches_the_issue_example(self):
        # 复现色 #643214 → RGB(100,50,20)、亮度 100%：固件会上报 level≈39%
        self.assertEqual(ls.expected_readback_pct(100, ("rgb", None, (100, 50, 20))), 39)

    def test_peak_255_styles_follow_the_command_brightness(self):
        for style in [("white", None, None), ("night", None, None),
                      ("temp", 4000, None), ("rgb", None, (255, 0, 128))]:
            for pct in (0, 33, 50, 100):
                with self.subTest(style=style, pct=pct):
                    self.assertEqual(ls.expected_readback_pct(pct, style), pct)

    def test_invalid_brightness_is_uncomparable(self):
        self.assertIsNone(ls.expected_readback_pct("abc", ("white", None, None)))


class DarkColorRegressionTests(unittest.TestCase):
    """暗色自定义颜色在任意亮度下都不再误报（验收 1）。"""

    def test_dark_rgb_full_brightness_not_flagged(self):
        row = status(light_brightness=100, light_mode="rgb", light_rgb="100,50,20",
                     rb_light_brightness=39)
        self.assertEqual(light_mismatch(row), [])

    def test_dark_rgb_half_brightness_not_flagged(self):
        # 亮度 50% → 固件上报 20%
        row = status(light_brightness=50, light_mode="rgb", light_rgb="100,50,20",
                     rb_light_brightness=20)
        self.assertEqual(light_mismatch(row), [])


class RealFailureStillDetectedTests(unittest.TestCase):
    """真失效仍要报得出来（验收 2/3）。"""

    def test_every_style_and_brightness_flags_a_zero_readback(self):
        for style in STYLES:
            mode, temp, rgb = style
            for pct in (50, 100):
                with self.subTest(style=style, pct=pct):
                    row = status(light_brightness=pct, light_mode=mode, light_temp=temp,
                                 light_rgb=None if rgb is None else ",".join(map(str, rgb)),
                                 rb_light_brightness=0)   # 命令亮着、回读 0
                    self.assertEqual(len(light_mismatch(row)), 1)

    def test_wrong_nonzero_readback_is_flagged(self):
        expected = ls.expected_readback_pct(100, ("rgb", None, (100, 50, 20)))
        row = status(light_brightness=100, light_mode="rgb", light_rgb="100,50,20",
                     rb_light_brightness=min(100, expected + 7))
        self.assertEqual(len(light_mismatch(row)), 1)

    def test_commanded_off_but_hardware_on_is_flagged(self):
        row = status(light_brightness=0, light_mode="white", rb_light_brightness=40)
        self.assertEqual(len(light_mismatch(row)), 1)

    def test_commanded_off_and_hardware_off_is_clean(self):
        row = status(light_brightness=0, light_mode="white", rb_light_brightness=0)
        self.assertEqual(light_mismatch(row), [])


class NonLightPairsUnchangedTests(unittest.TestCase):
    """门/窗/风扇三条判定行为不变（验收 4）。"""

    def test_consistent_row_is_clean(self):
        self.assertEqual(output_mismatch(status()), [])

    def test_fan_and_door_and_window_mismatch(self):
        row = status(fan_speed=50, rb_fan_speed=0,
                     door_status="closed", rb_door_status="open",
                     window_status="open", rb_window_status="closed")
        devices = {m["device"] for m in output_mismatch(row)}
        self.assertEqual(devices, {"fan", "door", "window"})


class FreshnessWindowTests(unittest.TestCase):
    """回读过期 / 稳定期内不判定（验收 3 的两个「不判定」分支）。"""

    def test_stale_readback_is_not_judged(self):
        row = status(rb_seen_at=_iso(RB_FRESH_S + 5),
                     light_brightness=100, rb_light_brightness=0)
        self.assertEqual(output_mismatch(row), [])

    def test_settle_window_is_not_judged(self):
        row = status(output_last_seen=_iso(CMD_SETTLE_S - 5),
                     light_brightness=100, rb_light_brightness=0)
        self.assertEqual(output_mismatch(row), [])


if __name__ == "__main__":
    unittest.main()
