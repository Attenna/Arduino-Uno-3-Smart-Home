import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from web.automation.engine import AutomationEngine
from web.automation.oled_carousel import DEFAULT_PAGES, OLED_MIN_INTERVAL


class OledStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def engine(self):
        return AutomationEngine(Mock(online=False), Mock(), self.root / "rules.json")

    def test_start_restores_enabled_carousel_before_threads_run(self):
        pages = [{"title": "Door", "lines": ["Distance:{distance_cm}"]}]
        (self.root / "oled_carousel.json").write_text(json.dumps({
            "enabled": True,
            "interval": 5,
            "pages_version": 999,
            "pages": pages,
        }), encoding="utf-8")
        engine = self.engine()
        self.addCleanup(engine.stop)

        engine.start()

        self.assertTrue(engine.oled_enabled)
        self.assertEqual(engine.oled_interval, OLED_MIN_INTERVAL)
        self.assertEqual(engine.oled_pages, pages)
        self.assertEqual(engine._oled_carousel.interval, OLED_MIN_INTERVAL)
        self.assertEqual(engine._oled_carousel.pages, pages)

    def test_malformed_config_keeps_safe_defaults(self):
        (self.root / "oled_carousel.json").write_text("{broken", encoding="utf-8")
        engine = self.engine()

        config = engine.oled_config()

        self.assertFalse(config["enabled"])
        self.assertEqual(config["interval"], OLED_MIN_INTERVAL)
        self.assertEqual(config["pages"], DEFAULT_PAGES)

    def test_enabled_config_no_longer_pushes_lines(self):
        """V2.12：屏上内容改由 B 固件拉取渲染，香橙派不再逐行推送 oled 命令。"""
        (self.root / "oled_carousel.json").write_text(json.dumps({
            "enabled": True,
            "interval": 15,
            "pages_version": 999,
            "pages": [{"title": "Environment",
                       "lines": ["= ENVIRONMENT =", "Temp: {temperature}C"]}],
        }), encoding="utf-8")
        bridge = Mock(online=True)
        engine = AutomationEngine(bridge, Mock(), self.root / "rules.json")
        self.addCleanup(engine.stop)

        engine.start()
        time.sleep(0.6)   # 旧实现每 0.5s 一轮，足以触发一次切页下发

        oled_calls = [c for c in bridge.call_tool.call_args_list
                      if c.args and c.args[0] == "oled"]
        self.assertEqual(oled_calls, [])
        self.assertNotIn("automation-oled",
                         {t.name for t in threading.enumerate()})


if __name__ == "__main__":
    unittest.main()
