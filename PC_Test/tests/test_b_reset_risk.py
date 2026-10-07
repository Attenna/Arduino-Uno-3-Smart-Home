import unittest

from web.automation.oled_carousel import OLED_MIN_INTERVAL, OledCarousel


class BResetRiskTests(unittest.TestCase):
    def test_oled_carousel_clamps_unsafe_fast_interval(self):
        carousel = OledCarousel(
            pages=[{"title": "one", "lines": ["hello"]}],
            emitter=lambda _line, _text: None,
            interval=1,
        )
        self.assertEqual(carousel.interval, OLED_MIN_INTERVAL)

    def test_unchanged_oled_rows_are_not_resent(self):
        writes = []
        carousel = OledCarousel(
            pages=[{"title": "one", "lines": ["hello", "world"]}],
            emitter=lambda line, text: writes.append((line, text)),
            interval=15,
            line_delay=0,
        )
        carousel._render_current()
        first = list(writes)
        carousel._render_current()
        self.assertEqual(first, [(0, "hello"), (1, "world")])
        self.assertEqual(writes, first)

if __name__ == "__main__":
    unittest.main()
