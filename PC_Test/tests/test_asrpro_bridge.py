"""ASRPRO regression tests; fake gateway only, no real serial devices."""
from datetime import datetime
import json
import os
import tempfile
import unittest
from unittest.mock import Mock

from asrpro_bridge import Bridge, DEFAULT_INTENTS, Gateway, Intent, Lines, load_intents


class BridgeTests(unittest.TestCase):
    """SH1 legacy numeric commands."""

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

    def test_missing_credentials_fail_closed(self):
        for token in ["", "short"]:
            with self.assertRaises(ValueError):
                Gateway("http://127.0.0.1:5000", token)


class Sh2BridgeTests(unittest.TestCase):
    """SH2 allow-listed intents."""

    def setUp(self):
        self.gateway = Mock()
        self.bridge = Bridge(self.gateway)

    def test_action_intent_calls_gateway_and_confirms(self):
        self.gateway.request.return_value = {"ok": True}
        self.assertEqual(self.bridge.handle(b"SH2 42 light action=white value=128\n"),
                         b"SH2 42 light OK\n")
        path, payload = self.gateway.request.call_args.args
        self.assertEqual(path, "/api/hardware/tool")
        self.assertEqual(payload, {"name": "light",
                                   "arguments": {"action": "white", "value": 128},
                                   "source": "voice", "timeout": 5})

    def test_gateway_failure_and_timeout_are_reported_not_retried(self):
        for result in ({"ok": False}, {"ok": "true"}, {}):
            self.gateway.request.return_value = result
            self.assertIn(b"FAILED", self.bridge.handle(b"SH2 1 door action=open\n"))
        self.gateway.reset_mock()
        self.gateway.request.side_effect = TimeoutError()
        self.assertEqual(self.bridge.handle(b"SH2 2 door action=open\n"),
                         b"SH2 2 door TIMEOUT\n")
        self.gateway.request.assert_called_once()

    def test_unknown_intent_missing_and_bad_arguments_rejected(self):
        lines = [b"SH2 3 garage_open\n",                  # not allow-listed
                 b"SH2 4 door\n",                         # missing required argument
                 b"SH2 5 door action=fly\n",              # enum outside choices
                 b"SH2 6 door action=open extra=1\n",     # unknown parameter
                 b"SH2 7 door action=open action=close\n",  # duplicate parameter
                 b"SH2 8 ac temperature=99\n",            # out of range
                 b"SH2 9 ac fan=turbo\n"]                 # enum outside choices
        for line in lines:
            self.assertIn(b"REJECTED", self.bridge.handle(line))
        self.gateway.request.assert_not_called()

    def test_repeated_request_replays_without_second_action(self):
        self.gateway.request.return_value = {"ok": True}
        first = self.bridge.handle(b"SH2 9 window action=open\n")
        second = self.bridge.handle(b"SH2 9 window action=open\n")
        self.assertEqual(first, second)
        self.gateway.request.assert_called_once()

    def test_reused_request_id_with_other_intent_rejected(self):
        self.gateway.request.return_value = {"ok": True}
        self.bridge.handle(b"SH2 10 window action=open\n")
        self.assertIn(b"REJECTED", self.bridge.handle(b"SH2 10 fan action=on\n"))
        self.gateway.request.assert_called_once()

    def test_status_read_only_snapshot(self):
        self.gateway.request.return_value = {
            "sensor_online": True, "temperature": 25.3, "humidity": 60}
        self.assertEqual(
            self.bridge.handle(b"SH2 11 status\n"),
            b"SH2 11 status OK humidity=6000 sensor_online=1 temperature=2530\n")
        self.assertEqual(self.gateway.request.call_args.args[0], "/api/status")

    def test_status_omits_offline_and_invalid_samples(self):
        self.gateway.request.return_value = {"sensor_online": False, "temperature": 25}
        self.assertEqual(self.bridge.handle(b"SH2 12 status\n"),
                         b"SH2 12 status OK sensor_online=0\n")

    def test_long_frame_above_legacy_limit_is_accepted(self):
        self.gateway.request.return_value = {"ok": True}
        line = (b"SH2 13 ac power=1 mode=cool temperature=26 fan=high "
                b"swing_ud=1 swing_lr=1\n")
        self.assertTrue(len(line) > 63)
        self.assertEqual(self.bridge.handle(line), b"SH2 13 ac OK\n")
        self.assertEqual(self.gateway.request.call_args.args[1]["arguments"], {
            "power": True, "mode": "cool", "temperature": 26, "fan": "high",
            "swing_ud": True, "swing_lr": True})

    def test_malformed_sh2_cannot_call_gateway(self):
        for line in [b"SH2 0 light action=off\n", b"SH2 1 Light action=off\n",
                     b"SH2 1 light action=off=1\n", b"SH2 1000000000 light\n",
                     b"SH2 1 light action=off", b"SH2\n", b"\xff\n"]:
            self.assertIsNone(self.bridge.handle(line))
        self.gateway.request.assert_not_called()


class IntentConfigTests(unittest.TestCase):
    """Dynamic intent registry: config-loaded at startup, discoverable but not serial-writable."""

    def setUp(self):
        self.gateway = Mock()
        self.gateway.request.return_value = {"ok": True}

    def _write(self, document):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write(document if isinstance(document, str) else json.dumps(document))
            path = handle.name
        self.addCleanup(os.unlink, path)
        return path

    def test_absent_config_falls_back_to_builtin_registry(self):
        self.assertIsNone(os.environ.get("ASRPRO_INTENTS_CONFIG"))
        self.assertEqual(load_intents("/no/such/file.json"), DEFAULT_INTENTS)

    def test_corrupt_or_invalid_config_falls_back(self):
        documents = ["{not json", "{}", {"intents": {}},
                     {"intents": {"x": {"tool": "y", "reader": "status"}}},
                     {"intents": {"x": {"tool": "y", "arguments": {"a": {"kind": "enum"}}}}},
                     {"intents": {"Bad": {"tool": "y"}}}]
        for document in documents:
            self.assertEqual(load_intents(self._write(document)), DEFAULT_INTENTS)

    def test_config_adds_intent_without_code_change(self):
        path = self._write({"intents": {"curtain": {
            "tool": "window",
            "arguments": {"action": {"kind": "enum", "required": True,
                                     "choices": ["open", "close"]}},
        }}})
        bridge = Bridge(self.gateway, intents=load_intents(path))
        self.assertEqual(bridge.handle(b"SH2 1 curtain action=open\n"),
                         b"SH2 1 curtain OK\n")
        self.assertEqual(self.gateway.request.call_args.args[1]["name"], "window")

    def test_list_intents_reports_registry(self):
        reply = Bridge(self.gateway).handle(b"SH2 7 list_intents\n")
        self.assertEqual(
            reply,
            b"SH2 7 list_intents OK count=8 "
            b"intents=ac,buzzer,door,fan,light,list_intents,status,window\n")

    def test_list_intents_omits_names_when_frame_would_overflow(self):
        intents = {f"intent_{index:02d}": Intent("light", {}) for index in range(40)}
        intents["list_intents"] = Intent(None, {}, "list_intents")
        reply = Bridge(self.gateway, intents=intents).handle(b"SH2 8 list_intents\n")
        self.assertLessEqual(len(reply), 127)
        self.assertIn(b"count=41", reply)
        self.assertNotIn(b"intents=", reply)

    def test_config_cannot_escape_the_allow_list(self):
        path = self._write({"intents": {"door": {
            "tool": "door", "arguments": {"action": {"kind": "enum",
            "required": True, "choices": ["open"]}}}}})
        bridge = Bridge(self.gateway, intents=load_intents(path))
        self.assertIn(b"REJECTED", bridge.handle(b"SH2 2 window action=open\n"))
        self.gateway.request.assert_not_called()


class LinesTests(unittest.TestCase):
    def test_partial_frames_are_rejoined(self):
        lines = Lines()
        self.assertEqual(lines.feed(b"SH1 1"), [])
        self.assertEqual(lines.feed(b" 7\n"), [b"SH1 1 7\n"])

    def test_oversized_frame_is_discarded_whole(self):
        lines = Lines()
        self.assertEqual(lines.feed(b"x" * 128 + b"SH2 1 status\n"), [])
        self.assertEqual(lines.feed(b"SH2 2 status\n"), [b"SH2 2 status\n"])


if __name__ == "__main__":
    unittest.main()
