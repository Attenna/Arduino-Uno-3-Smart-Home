"""HC-SR04 gateway tests with an in-memory serial peer; never opens a device."""
import asyncio
import json
import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import mcp_home_server as server


class DistanceTests(unittest.TestCase):
    def setUp(self):
        self.home = server.HomeController()  # No serial handles or reader threads.

    def peer(self, frames):
        home = self.home

        class Peer:
            def write(self, raw):
                request = json.loads(raw)
                self.request = request
                for frame in frames(request):
                    home._dispatch_b_frame(frame, json.dumps(frame))

        self.home.ser_b = Peer()

    def test_fresh_distance_preserved_and_stale_id_ignored(self):
        self.peer(lambda req: [
            {"type": "distance", "id": req["id"] + 10, "distance_cm": 999},
            {"type": "distance", "distance_cm": 888},
            {"type": "distance", "id": req["id"], "valid": True,
             "status": "ok", "distance_cm": 25.0, "echo_us": 1450},
        ])
        for _ in range(2):
            result = json.loads(self.home.handle_get_distance())
            self.assertEqual(result["distance_cm"], 25.0)
            self.assertTrue(result["valid"])
        self.assertEqual(self.home.ser_b.request,
                         {"cmd": "ultrasonic", "action": "read", "id": 1})
        self.assertEqual(self.home._b_last_cmd, {})
        self.assertEqual(self.home._b_last_state, {})

    def test_invalid_readings_remain_null(self):
        for status in ("timeout", "out_of_range"):
            with self.subTest(status=status):
                self.peer(lambda req: [{"type": "distance", "id": req["id"],
                          "valid": False, "status": status, "distance_cm": None}])
                result = json.loads(self.home.handle_get_distance())
                self.assertFalse(result["valid"])
                self.assertIsNone(result["distance_cm"])
                self.assertEqual(result["status"], status)

    def test_old_firmware_returns_error_without_waiting_or_reopening(self):
        self.peer(lambda req: [{"type": "response", "id": req["id"],
                               "result": "error", "error": "unknown_command"}])
        with patch.object(self.home, "_reopen_b") as reopen:
            self.assertIn("unknown_command", self.home.handle_get_distance())
            reopen.assert_not_called()

    def test_disconnected_is_error(self):
        self.assertTrue(self.home.handle_get_distance().startswith("error:"))

    def test_ack_without_measurement_is_not_success(self):
        self.peer(lambda req: [{"type": "response", "id": req["id"], "result": "ok"}])
        self.assertTrue(self.home.handle_get_distance().startswith("error:"))

    def test_read_timeout_does_not_reset_actuators(self):
        self.peer(lambda req: [])
        with patch.object(self.home._b_resp_event, "wait", return_value=False), \
             patch.object(self.home, "_reopen_b") as reopen:
            for _ in range(4):
                self.assertIn("响应超时", self.home.handle_get_distance())
            reopen.assert_not_called()

    def test_distance_cannot_complete_an_actuator_waiter(self):
        self.home._b_waiter = True
        self.home._b_waiter_id = 7
        self.home._b_expect = ("response",)
        self.home._dispatch_b_frame({"type": "distance", "id": 7}, "")
        self.assertFalse(self.home._b_resp_event.is_set())

    def test_tool_discovery_and_call(self):
        async def check():
            tools = await server.mcp.list_tools()
            tool = next(t for t in tools if t.name == "get_distance")
            self.assertFalse(tool.inputSchema.get("required"))
            with patch.object(server, "HOME", self.home):
                with patch.object(self.home, "handle_get_distance", return_value='{"valid":false}'):
                    self.assertEqual(await server.get_distance(), '{"valid":false}')
        asyncio.run(check())


class BFrameReassemblyTests(unittest.TestCase):
    """B 板收发：断流拆帧的重组，以及"补发只读命令顶开断流"（nudge）。

    真机实测：B 板一帧只吐约 146 字节就停住，余下字节要等固件再解析到一整行命令
    才发完（空行不算）。距离帧/state 帧/带 state 快照的 response 帧都超过该长度，
    所以这里两条都要覆盖：跨 read() 的重组，以及等不到响应时的补发。
    """

    def setUp(self):
        self.home = server.HomeController()   # 无串口句柄、不启线程

    def test_split_frame_is_reassembled_across_reads(self):
        head = b'\r\n{"module":"output","type":"distance","id":7,'
        self.assertEqual(self.home._take_b_frames(head), [])
        tail = b'"valid":true,"distance_cm":25.0,"echo_us":1450}\r\n'
        self.assertEqual(
            self.home._take_b_frames(tail),
            ['{"module":"output","type":"distance","id":7,'
             '"valid":true,"distance_cm":25.0,"echo_us":1450}'])

    def test_multiple_frames_and_noise_share_one_chunk(self):
        self.assertEqual(
            self.home._take_b_frames(b'noise\r\n{"a":1}\r\n{"b":{"c":2}}'),
            ['{"a":1}', '{"b":{"c":2}}'])

    def test_brace_inside_string_is_not_a_delimiter(self):
        self.assertEqual(self.home._take_b_frames(b'{"a":"}{","b":"\\\\"}'),
                         ['{"a":"}{","b":"\\\\"}'])

    def test_unparseable_garbage_is_dropped_and_resynced(self):
        self.home._take_b_frames(b'{"a":' + b'x' * (server._B_RX_MAX_BYTES + 16))
        self.assertEqual(len(self.home._b_rxbuf), 0)
        self.assertEqual(self.home._take_b_frames(b'{"ok":1}'), ['{"ok":1}'])


class _StallingSerial:
    """B 板串口替身：复现"一帧吐不满就停，收到下一整行命令才续发"。

    ``write`` 先把上一帧没吐完的尾巴送到"线路"上，再按本次命令生成紧凑 JSON 帧
    并吐出它的前 ``STALL_BYTES`` 字节，余下留作待发尾巴。真机捕获的断流点在一个
    区间内浮动（约 96~146 字节），不变的是：帧尾只有等固件再解析到一整行命令才发。
    """

    STALL_BYTES = 96

    def __init__(self, frame_for):
        self._frame_for = frame_for
        self._lock = threading.Lock()
        self._pending = b""
        self._line = b""
        self.requests = []

    def write(self, raw):
        request = json.loads(raw.decode("utf-8"))
        frame = (json.dumps(self._frame_for(request), separators=(",", ":"))
                 + "\r\n").encode("utf-8")
        with self._lock:
            self.requests.append(request)
            self._line += self._pending + frame[:self.STALL_BYTES]
            self._pending = frame[self.STALL_BYTES:]

    @property
    def in_waiting(self):
        with self._lock:
            return len(self._line)

    def read(self, size=1):
        with self._lock:
            if not self._line:
                chunk = b""
            else:
                chunk, self._line = self._line[:size], self._line[size:]
        if not chunk:
            time.sleep(0.01)          # 模拟带超时的阻塞读
        return chunk

    def close(self):
        pass


class BStallNudgeTests(unittest.TestCase):
    """断流场景下端到端：读线程重组 + 等不到就补发只读命令。"""

    def setUp(self):
        self.ser = _StallingSerial(self._frame_for)
        self.home = server.HomeController(ser_b=self.ser, port_b="fake-b")
        time.sleep(0.05)              # 让读线程进入 read 循环

    def tearDown(self):
        self.home._b_stop.set()

    @staticmethod
    def _frame_for(request):
        if request["cmd"] == "ultrasonic":
            return {"module": "output", "type": "distance", "id": request["id"],
                    "valid": True, "status": "ok", "distance_cm": 12.2, "echo_us": 708}
        return {"module": "output", "type": "state", "door": "closed",
                "window": "normal", "fan": 0, "light": 0, "buzzer": "off"}

    def test_distance_survives_stall_and_nudge_is_read_only(self):
        result = json.loads(self.home.handle_get_distance())
        self.assertTrue(result["valid"])
        self.assertEqual(result["distance_cm"], 12.2)
        self.assertEqual(self.ser.requests[0],
                         {"cmd": "ultrasonic", "action": "read", "id": 0})
        # 补发必须是不动执行器的只读命令，且带自己的 id
        self.assertEqual(self.ser.requests[1],
                         {"cmd": "system", "action": "status", "id": 1})

    def test_state_frame_over_stall_threshold_is_parsed(self):
        self.home._send_b({"cmd": "system", "action": "status"},
                          allow_reopen=False, expect=("state",))
        self.assertEqual(self.home._b_last_state.get("door"), "closed")


class DistanceGatewayTests(unittest.TestCase):
    def test_authenticated_http_tool_and_anonymous_rejection(self):
        from web.app import create_app
        from web.api import devices
        from werkzeug.security import generate_password_hash

        with patch.dict(os.environ, {
            "SMART_HOME_ADMIN_USER": "test-admin",
            "SMART_HOME_ADMIN_PASSWORD_HASH": generate_password_hash("test-password"),
            "SMART_HOME_SESSION_SECRET": "s" * 48,
            "SMART_HOME_SERVICE_TOKEN": "u" * 48,
        }):
            app = create_app({"serial": {"enabled": True}}, start_hardware=False)
        client = app.test_client()
        body = {"name": "get_distance", "arguments": {}}
        sample = json.dumps({"valid": True, "distance_cm": 25.0, "status": "ok"})
        bridge = SimpleNamespace(call_tool=Mock(return_value=(True, sample)))
        with patch.object(devices.extensions, "bridge", bridge):
            self.assertEqual(client.post("/api/hardware/tool", json=body).status_code, 401)
            bridge.call_tool.assert_not_called()
            response = client.post("/api/hardware/tool", json=body,
                                   headers={"Authorization": "Bearer " + "u" * 48})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.json["result"])["distance_cm"], 25.0)
            bridge.call_tool.assert_called_once_with("get_distance", {}, timeout=10.0)


if __name__ == "__main__":
    unittest.main()
