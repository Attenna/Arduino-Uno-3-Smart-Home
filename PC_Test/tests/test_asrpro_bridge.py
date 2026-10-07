"""ASRPRO regression tests; fake gateway only, no real serial devices."""
from datetime import datetime
import unittest
from unittest.mock import Mock

from asrpro_bridge import Bridge, Gateway, Lines


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.gateway = Mock()
        self.bridge = Bridge(self.gateway, lambda: datetime(2026, 10, 7, 0, 5))

    def test_all_actions_use_gateway_and_confirm_ack(self):
        self.gateway.request.return_value = {"ok": True}
        expected = [("light", "white"), ("light", "off"), ("door", "open"),
                    ("window", "open"), ("fan", "on"), ("fan", "off")]
        for cmd, (name, action) in enumerate(expected, 1):
            self.assertEqual(self.bridge.handle(f"SH1 32 {cmd}\n".encode()),
                             f"SH1 32 {cmd} OK 0 0\n".encode())
            path, payload = self.gateway.request.call_args.args
            self.assertEqual(path, "/api/hardware/tool")
            self.assertEqual(payload["name"], name)
            self.assertEqual(payload["arguments"]["action"], action)
            self.assertEqual(payload["source"], "voice")

    def test_failure_and_timeout_never_retry_or_report_success(self):
        for result in ({"ok": False}, {"ok": "true"}, {}):
            self.gateway.request.return_value = result
            self.assertIn(b"ERR", self.bridge.handle(b"SH1 1 3\n"))
        self.gateway.reset_mock()
        self.gateway.request.side_effect = TimeoutError()
        self.assertIn(b"ERR", self.bridge.handle(b"SH1 2 3\n"))
        self.gateway.request.assert_called_once()

    def test_temperature_humidity_and_midnight(self):
        self.gateway.request.return_value = {
            "sensor_online": True, "temperature": -3.25, "humidity": 0}
        self.assertEqual(self.bridge.handle(b"SH1 5 7\r\n"), b"SH1 5 7 TEMP -325 0\n")
        self.assertEqual(self.bridge.handle(b"SH1 6 8\n"), b"SH1 6 8 HUM 0 0\n")
        self.assertEqual(self.bridge.handle(b"SH1 7 9\n"), b"SH1 7 9 TIME 0 5\n")

    def test_stale_missing_nan_boolean_and_out_of_range_values(self):
        for cmd, key, bad in [(7, "temperature", [-41, 81]), (8, "humidity", [-1, 101])]:
            for value in bad + [None, float("nan"), float("inf"), True, "25"]:
                self.gateway.request.return_value = {"sensor_online": True, key: value}
                self.assertIn(b"ERR", self.bridge.handle(f"SH1 1 {cmd}\n".encode()))
            self.gateway.request.return_value = {"sensor_online": False, key: 25}
            self.assertIn(b"ERR", self.bridge.handle(f"SH1 1 {cmd}\n".encode()))

    def test_malformed_input_cannot_call_gateway(self):
        for line in [b"noise\n", b"SH1 0 1\n", b"SH1 1 10\n", b"SH1 1 1 extra\n",
                     b"SH1 1 1", b"SH1 1000000000 1\n", b"\xff\n"]:
            self.assertIsNone(self.bridge.handle(line))
        self.gateway.request.assert_not_called()

    def test_partial_frames_and_oversize_discard(self):
        lines = Lines()
        self.assertEqual(lines.feed(b"SH1 1"), [])
        self.assertEqual(lines.feed(b" 7\n"), [b"SH1 1 7\n"])
        self.assertEqual(lines.feed(b"x" * 64 + b"SH1 2 3\nSH1 3 9\n"), [b"SH1 3 9\n"])

    def test_missing_credentials_fail_closed(self):
        for token in ["", "short"]:
            with self.assertRaises(ValueError):
                Gateway("http://127.0.0.1:5000", token)


if __name__ == "__main__":
    unittest.main()
