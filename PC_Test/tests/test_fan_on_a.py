"""Fan moved to Module A (A1/INA): framing, routing and readback, no serial opened."""
import json
import threading
import time
import unittest
from unittest.mock import Mock

import mcp_home_server as server


class FanTransportTests(unittest.TestCase):
    def test_compact_fan_frames_fit_uno_rx_buffer(self):
        actions = [
            {"action": "on"},
            {"action": "off"},
            {"action": "full"},
            {"action": "set_speed", "value": 0},
            {"action": "set_speed", "value": 255},
            {"action": "stop"},
        ]
        for command in actions:
            packet = server.encode_a_fan_command(command, 2147483647)
            self.assertLess(len(packet), 64)
            self.assertTrue(packet.startswith(b"F,"))
            self.assertTrue(packet.endswith(b"\n"))

    def test_speed_maps_to_single_wire_on_off(self):
        self.assertEqual(server.encode_a_fan_command({"action": "set_speed", "value": 0}, 7),
                         b"F,0,7\n")
        self.assertEqual(server.encode_a_fan_command({"action": "set_speed", "value": 1}, 8),
                         b"F,1,8\n")

    def test_unknown_action_is_rejected(self):
        with self.assertRaises(ValueError):
            server.encode_a_fan_command({"action": "turbo"}, 1)

    def test_gateway_routes_fan_to_a_board(self):
        home = server.HomeController()
        home._send_a = Mock(return_value="ok")
        self.assertEqual(home.handle_fan("on"), "ok")
        home._send_a.assert_called_once_with({"cmd": "fan", "action": "on"})

    def test_gateway_requires_speed_value(self):
        home = server.HomeController()
        home._send_a = Mock()
        self.assertTrue(home.handle_fan("set_speed").startswith("error"))
        home._send_a.assert_not_called()


class FanReadbackTests(unittest.TestCase):
    def _controller(self, a_fan):
        home = server.HomeController.__new__(server.HomeController)
        home._snapshot_lock = threading.Lock()
        home._snapshot = {"fan": a_fan, "timestamp": 1}
        home._snapshot_ts = time.time()
        home._b_last_state = {"door": "closed", "window": "normal",
                              "fan": 0, "light": 0, "buzzer": "off"}
        home._b_last_state_ts = time.time()
        home._b_last_cmd = {}
        return home

    def test_a_board_fan_overrides_stale_b_board_value(self):
        state = json.loads(self._controller(1).output_state())["state"]
        self.assertEqual(state["fan"], 255)
        self.assertEqual(state["door"], "closed")

    def test_old_a_firmware_keeps_b_board_value(self):
        home = self._controller(None)
        home._snapshot = {"timestamp": 1}
        state = json.loads(home.output_state())["state"]
        self.assertEqual(state["fan"], 0)

    def test_stale_a_snapshot_is_not_used(self):
        home = self._controller(1)
        home._snapshot_ts = time.time() - 60
        self.assertEqual(json.loads(home.output_state())["state"]["fan"], 0)


if __name__ == "__main__":
    unittest.main()
