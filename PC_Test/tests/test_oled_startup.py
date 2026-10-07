import json
import tempfile
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


if __name__ == "__main__":
    unittest.main()
