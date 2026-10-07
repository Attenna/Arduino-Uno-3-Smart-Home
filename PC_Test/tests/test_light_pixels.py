"""Eight-pixel commands use mocked transports; no serial device is opened."""
import unittest
from unittest.mock import Mock
import mcp_home_server as server
from web.hardware import McpHardwareBridge


class PixelTransportTests(unittest.TestCase):
    def test_gateway_sends_one_atomic_command(self):
        home = server.HomeController()
        home._send_a = Mock(return_value="ok")
        self.assertEqual(home.handle_light("pixels", 128, 255, 80, 10, count=4), "ok")
        home._send_a.assert_called_once_with({"cmd": "light", "action": "pixels",
            "count": 4, "r": 255, "g": 80, "b": 10, "value": 128})

    def test_gateway_rejects_invalid_count_and_missing_rgb(self):
        home = server.HomeController()
        home._send_a = Mock()
        for count in (None, 0, 9, True, 2.5, "4"):
            self.assertTrue(home.handle_light("pixels", 128, 1, 2, 3, count=count).startswith("error"))
        self.assertTrue(home.handle_light("pixels", count=4).startswith("error"))
        home._send_a.assert_not_called()

    def test_bridge_scales_brightness_without_changing_color_or_count(self):
        bridge = McpHardwareBridge.__new__(McpHardwareBridge)
        bridge.call_tool = Mock(return_value=(True, "ok"))
        bridge.control_light_pixels(50, (255, 80, 10), 6)
        bridge.call_tool.assert_called_once_with("light", {"action": "pixels",
            "count": 6, "r": 255, "g": 80, "b": 10, "value": 128})
