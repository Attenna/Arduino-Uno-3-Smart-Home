import asyncio
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from werkzeug.security import generate_password_hash

os.environ.update(SMART_HOME_ADMIN_USER="test-admin",
                  SMART_HOME_ADMIN_PASSWORD_HASH=generate_password_hash("test-password"),
                  SMART_HOME_SESSION_SECRET="s" * 48,
                  SMART_HOME_SERVICE_TOKEN="t" * 48)

from web.app import create_app
from web.api import access, automation, devices, status, voice
from web.automation.default_rules import GATING_PRESETS
from web.automation.engine import AutomationEngine
from web.hardware import McpHardwareBridge
import camera_stream
import midea_ac


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"serial": {"enabled": True}}, start_hardware=False)
        self.app.testing = True
        self.client = self.app.test_client()

    def login(self, client=None):
        client = client or self.client
        with client.session_transaction() as session:
            session["user"] = "test-admin"

    def test_anonymous_cannot_access_hardware(self):
        self.assertEqual(self.client.get("/api/hardware/tools").status_code, 401)
        with patch.object(devices, "_hw_call") as hardware:
            self.assertEqual(self.client.post("/api/door", json={"status": "open"}).status_code, 401)
            hardware.assert_not_called()

    def test_login_and_csrf(self):
        page = self.client.get("/login").get_data(as_text=True)
        csrf = re.search(r'name="csrf" value="([^"]+)"', page)[1]
        self.assertEqual(self.client.post("/login", data={"username": "test-admin",
                         "password": "test-password", "csrf": csrf}).status_code, 302)
        self.assertEqual(self.client.post("/api/door", json={"status": "open"},
                         headers={"Origin": "http://evil.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/door", json={"status": "open"}).status_code, 403)

    def test_service_scope_and_face_assertions(self):
        headers = {"Authorization": "Bearer " + "t" * 48}
        with patch.object(devices.extensions, "bridge", SimpleNamespace(tool_schemas=[{"name": "test"}])):
            self.assertEqual(self.client.get("/api/hardware/tools", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/access/persons", headers=headers).status_code, 403)
        self.assertEqual(self.client.post("/api/face/notify", headers=headers,
                         json={"face_id": "person"}).status_code, 403)
        self.login()
        self.assertEqual(self.client.post("/api/face/notify", json={"face_id": "person"},
                         headers={"Origin": "http://localhost"}).status_code, 403)

    def test_access_dry_run_has_no_events(self):
        self.login()
        person = {"id": 1, "name": "test", "face_id": "test-face"}
        with patch.object(access.db, "get_person", return_value=person), \
             patch.object(access.db, "find_authorized", return_value=person), \
             patch.object(access.access_guard, "verify") as verify, \
             patch.object(access.access_guard, "broadcast") as broadcast:
            response = self.client.post("/api/access/test", json={"person_id": 1},
                                        headers={"Origin": "http://localhost"})
            self.assertTrue(response.json["granted"])
            verify.assert_not_called()
            broadcast.assert_not_called()

    def test_readiness_and_liveness(self):
        self.assertEqual(self.client.get("/api/live").status_code, 200)
        with patch.object(status.db, "get_current_status", side_effect=RuntimeError("db")):
            self.assertEqual(self.client.get("/api/ready").status_code, 503)
        with patch.object(status.db, "get_current_status", return_value={"sensor_online": False, "output_online": True}), \
             patch.object(status.extensions, "bridge", SimpleNamespace(online=True)):
            self.assertEqual(self.client.get("/api/ready").status_code, 503)
        with patch.object(status.db, "get_current_status", return_value={"sensor_online": True, "output_online": True}), \
             patch.object(status.extensions, "bridge", SimpleNamespace(online=True)):
            self.assertEqual(self.client.get("/api/ready").status_code, 200)

    def test_voice_status_and_wake_expose_ack_and_runtime_info(self):
        self.login()
        upstream = '{"state":"ACK","info":{"audio_output":"UI only"}}'
        with patch.object(voice.voice_client, "voice_request",
                          return_value=(True, upstream)):
            status_response = self.client.get("/api/voice/status")
            self.assertEqual(status_response.json["state_label"], "提示音中")
            self.assertEqual(status_response.json["info"]["audio_output"], "UI only")
            wake_response = self.client.post(
                "/api/voice/wake", headers={"Origin": "http://localhost"})
            self.assertEqual(wake_response.json["state"], "ACK")
            self.assertEqual(wake_response.json["state_label"], "提示音中")

    def test_rules_api_exposes_gating_preset_list(self):
        """#77：页面需要「门控维护预设」名单来判断哪些被停用并给醒目提示。"""
        self.login()
        with tempfile.TemporaryDirectory() as directory:
            engine = AutomationEngine(Mock(), Mock(), Path(directory) / "rules.json")
            engine.load()
            self.addCleanup(engine.stop)
            with patch.object(automation.extensions, "automation", engine):
                payload = self.client.get("/api/automation/rules").get_json()
        self.assertEqual(payload["gating_presets"], list(GATING_PRESETS))
        # 内置门控预设确实随默认规则一起注入，页面才能在客户端判断「已停用」
        by_preset = {r.get("preset") for r in payload["rules"]}
        self.assertTrue(set(GATING_PRESETS) <= by_preset)

    def test_voice_events_has_no_hop_by_hop_header(self):
        """#88：SSE 代理不得设置 hop-by-hop 头。

        规范（PEP 3333）禁止 WSGI 应用设置 Connection 等逐跳头，waitress 会在
        start_response 处 assert 失败，导致 /api/voice/events 每次连接都 500。
        这里断言响应头里不再出现 Connection；上游不可达时仍要 200 + 一条提示帧。
        """
        self.login()
        with patch.object(voice.voice_client, "open_event_stream",
                          side_effect=OSError("voice 未运行")):
            response = self.client.get("/api/voice/events")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["Content-Type"].startswith("text/event-stream"))
        self.assertIsNone(response.headers.get("Connection"))
        body = response.get_data(as_text=True)
        self.assertIn("data:", body)
        self.assertIn("语音助手不可达", body)

    def test_voice_events_proxies_upstream_frames(self):
        """#88 的另一半：正常路径同样不能带逐跳头，且上游帧要原样透传。"""
        class Upstream:
            def __init__(self, chunks):
                self._chunks = list(chunks)

            def __iter__(self):
                return iter(self._chunks)

            def close(self):
                pass

        self.login()
        frame = 'data: {"type":"user","text":"开灯"}\n\n'
        with patch.object(voice.voice_client, "open_event_stream",
                          return_value=Upstream([frame.encode("utf-8")])):
            response = self.client.get("/api/voice/events")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get("Connection"))
        self.assertIn('"type":"user"', response.get_data(as_text=True))

    def test_ac_resends_unchanged_state(self):
        self.login()
        with patch.object(devices, "_ac_state_from_db", return_value=midea_ac.AcState()), \
             patch.object(devices, "_record_ac"), \
             patch.object(devices, "_hw_call", return_value=(True, "ok")) as hardware:
            response = self.client.post("/api/ac", json={"temperature": 26},
                                        headers={"Origin": "http://localhost"})
            self.assertEqual(response.status_code, 200)
            hardware.assert_called_once()

    def test_concurrent_ac_patches_do_not_overwrite(self):
        state = [midea_ac.AcState()]
        results = []
        def command(*args, **kwargs):
            time.sleep(.03)
            return True, "ok"
        def request(payload):
            client = self.app.test_client()
            self.login(client)
            results.append(client.post("/api/ac", json=payload,
                                       headers={"Origin": "http://localhost"}).status_code)
        with patch.object(devices, "_ac_state_from_db", side_effect=lambda: state[0]), \
             patch.object(devices, "_record_ac", side_effect=lambda value: state.__setitem__(0, value)), \
             patch.object(devices, "_hw_call", side_effect=command):
            threads = [threading.Thread(target=request, args=(payload,))
                       for payload in ({"temperature": 23}, {"fan": "high"})]
            for thread in threads: thread.start()
            for thread in threads: thread.join(2)
        self.assertEqual(results, [200, 200])
        self.assertEqual(state[0].temperature, 23)
        self.assertEqual(state[0].fan, "high")


class LightModeTests(unittest.TestCase):
    """/api/light 的「亮法」选择：白光 / 夜灯 / 色温 / 自定义颜色。

    只断言最终落到硬件桥的调用参数——这层决定灯带怎么亮，是本次改动的语义核心。
    记账与状态读取在这里打桩隔离（亮法自 #27 起也入库：`light_mode`/`light_temp`/
    `light_rgb`，其记账口径由 tests/test_light_style.py 覆盖）。
    """

    def setUp(self):
        self.app = create_app({"serial": {"enabled": True}}, start_hardware=False)
        self.app.testing = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user"] = "test-admin"

    def _post(self, payload):
        state = {"light_status": payload.get("status", "off"),
                 "light_brightness": payload.get("brightness", 0)}
        with patch.object(devices, "_record_light"), \
             patch.object(devices.db, "get_current_status", return_value=state), \
             patch.object(devices, "_hw_call", return_value=(True, "ok")) as hardware:
            response = self.client.post("/api/light", json=payload,
                                        headers={"Origin": "http://localhost"})
        return response, hardware

    def test_default_stays_white(self):
        response, hardware = self._post({"status": "on", "brightness": 60})
        self.assertEqual(response.status_code, 200)
        hardware.assert_called_once_with("control_light", "on", 60, "white")

    def test_night_mode_uses_night_action(self):
        response, hardware = self._post({"status": "on", "brightness": 25, "mode": "night"})
        hardware.assert_called_once_with("control_light", "on", 25, "night")
        self.assertIn("夜灯", response.get_json()["message"])

    def test_color_temperature_is_clamped(self):
        for given, expected in ((9000, 6500), (1000, 2700), (4000, 4000)):
            _, hardware = self._post({"status": "on", "brightness": 80, "temp": given})
            hardware.assert_called_once_with("control_light_temp", expected, 80)

    def test_custom_rgb_is_scaled_by_brightness(self):
        _, hardware = self._post({"status": "on", "brightness": 50, "rgb": [255, 128, 0]})
        hardware.assert_called_once_with("control_light_color", "rgb", 255, 128, 0,
                                         brightness_pct=50)

    def test_off_wins_over_any_style(self):
        _, hardware = self._post({"status": "off", "brightness": 50, "mode": "night",
                                  "temp": 3000, "rgb": [1, 2, 3]})
        hardware.assert_called_once_with("control_light", "off", 0)


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever)
        self.thread.start()
        self.bridge = McpHardwareBridge({}, Mock())
        self.bridge._online = True
        self.bridge._loop = self.loop
        self.bridge._call_lock = asyncio.Lock()
        self.bridge._fire_ack = Mock()
        self.calls = []
        async def call(name, args):
            self.calls.append(name)
            return SimpleNamespace(content=[SimpleNamespace(text="ok")], isError=False)
        self.bridge._session = SimpleNamespace(call_tool=call)

    def tearDown(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join()
        self.loop.close()

    def test_expired_queue_never_dispatches(self):
        asyncio.run_coroutine_threadsafe(self.bridge._call_lock.acquire(), self.loop).result(1)
        ok, message = self.bridge.call_tool("door", {"action": "open"}, timeout=.03)
        self.assertFalse(ok)
        self.assertIn("expired_not_sent", message)
        self.loop.call_soon_threadsafe(self.bridge._call_lock.release)
        time.sleep(.05)
        self.assertEqual(self.calls, [])

    def test_inflight_timeout_is_unknown_and_keeps_serialization(self):
        async def slow(name, args):
            self.calls.append(name)
            await asyncio.sleep(.12)
            return SimpleNamespace(content=[SimpleNamespace(text="ok")], isError=False)
        self.bridge._session.call_tool = slow
        ok, message = self.bridge.call_tool("door", {}, timeout=.02)
        self.assertFalse(ok)
        self.assertIn("unknown_sent", message)
        ok, message = self.bridge.call_tool("window", {}, timeout=.02)
        self.assertIn("expired_not_sent", message)
        time.sleep(.15)
        self.assertEqual(self.calls, ["door"])
        self.bridge._fire_ack.assert_called_once()

    def test_invalid_timeouts_do_not_dispatch(self):
        for timeout in (float("nan"), float("inf"), -1, 31, "bad"):
            self.assertFalse(self.bridge.call_tool("door", {}, timeout)[0])
        self.assertEqual(self.calls, [])

    def test_mcp_error_flag_is_respected(self):
        async def failure(name, args):
            return SimpleNamespace(content=[SimpleNamespace(text="not completed")], isError=True)
        self.bridge._session.call_tool = failure
        self.assertFalse(self.bridge.call_tool("door", {}, .2)[0])
        self.bridge._fire_ack.assert_not_called()

    def test_stale_cached_output_is_not_marked_live(self):
        import json
        for age, expected in ((60, False), (1, True)):
            self.bridge.db.reset_mock()
            async def cached(session, name, args):
                if name == "get_serial_health":
                    return json.dumps({"b": {"connected": True, "last_frame_ago_s": 1}})
                return json.dumps({"age_s": age, "state": {"door": "closed", "window": "normal", "fan": 0, "light": 0, "buzzer": "off"}})
            with patch.object(self.bridge, "_call", side_effect=cached), \
                 patch.object(self.bridge, "_after_readback"):
                asyncio.run_coroutine_threadsafe(self.bridge._readback_tick(None), self.loop).result(1)
            self.assertEqual(self.bridge.db.set_output_readback.called, expected)


class AcProtocolTests(unittest.TestCase):
    def test_same_state_reaches_ir_without_repeating_swing_toggle(self):
        from mcp_home_server import HomeController
        controller = HomeController.__new__(HomeController)
        controller._ac_lock = threading.Lock()
        controller._ac = midea_ac.AcState(power=True, swing_ud=True)
        controller._send_b = Mock(return_value="ok")
        payload = controller._ac.snapshot()
        self.assertTrue(controller.handle_ac(**payload).startswith("ok"))
        self.assertTrue(controller.handle_ac(**payload).startswith("ok"))
        self.assertEqual(controller._send_b.call_count, 2)
        expected = midea_ac.to_frames(controller._ac, {"power"})[0]
        for call in controller._send_b.call_args_list:
            self.assertEqual(call.args[0]["hex"], expected)


class LightSerialTests(unittest.TestCase):
    """Web 语义 → A 板串口帧的映射（MCP 工具层）。"""

    def _controller(self):
        from mcp_home_server import HomeController
        controller = HomeController.__new__(HomeController)
        controller._send_a = Mock(return_value="ok")
        return controller

    def test_white_is_unchanged(self):
        controller = self._controller()
        controller.handle_light("white", 180)
        controller._send_a.assert_called_once_with(
            {"cmd": "light", "action": "white", "value": 180})

    def test_night_falls_back_to_firmware_default(self):
        controller = self._controller()
        controller.handle_light("night")
        controller._send_a.assert_called_once_with(
            {"cmd": "light", "action": "night", "value": 60})

    def test_temp_needs_kelvin(self):
        controller = self._controller()
        self.assertTrue(controller.handle_light("temp").startswith("error"))
        controller.handle_light("temp", 200, temp=3000)
        controller._send_a.assert_called_once_with(
            {"cmd": "light", "action": "temp", "temp": 3000, "value": 200})

    def test_rgb_keeps_value_as_brightness(self):
        controller = self._controller()
        controller.handle_light("rgb", 128, r=255, g=128, b=0)
        controller._send_a.assert_called_once_with(
            {"cmd": "light", "action": "rgb", "r": 255, "g": 128, "b": 0, "value": 128})


class LightBridgeTests(unittest.TestCase):
    """硬件桥：百分比/色温 → MCP 工具参数。"""

    def setUp(self):
        self.bridge = McpHardwareBridge({}, Mock())
        self.bridge.call_tool = Mock(return_value=(True, "ok"))

    def test_night_uses_night_action(self):
        self.bridge.control_light("on", 25, "night")
        self.bridge.call_tool.assert_called_once_with("light", {"action": "night", "value": 64})

    def test_temperature_clamps_kelvin(self):
        self.bridge.control_light_temp(3000, 50)
        self.bridge.call_tool.assert_called_once_with(
            "light", {"action": "temp", "temp": 3000, "value": 128})
        self.bridge.control_light_temp(9000, 100)
        self.bridge.call_tool.assert_called_with(
            "light", {"action": "temp", "temp": 6500, "value": 255})

    def test_rgb_carries_brightness(self):
        self.bridge.control_light_color("rgb", 255, 128, 0, brightness_pct=50)
        self.bridge.call_tool.assert_called_once_with(
            "light", {"action": "rgb", "r": 255, "g": 128, "b": 0, "value": 128})

    def test_preset_color_has_no_brightness(self):
        self.bridge.control_light_color("red")
        self.bridge.call_tool.assert_called_once_with("light", {"action": "red"})

    def test_rgb_zero_brightness_is_preserved(self):
        self.bridge.control_light_color("rgb", 255, 128, 0, brightness_pct=0)
        self.bridge.call_tool.assert_called_once_with(
            "light", {"action": "rgb", "r": 255, "g": 128, "b": 0, "value": 0})

    def test_zero_brightness_ack_is_recorded_as_off(self):
        for action in ('night', 'temp', 'rgb'):
            self.assertEqual(devices._tool_state_report('light', {'action': action, 'value': 0}),
                             {'device': 'light', 'status': 'off', 'brightness': 0})


class CameraTests(unittest.TestCase):
    def test_encoding_shared_and_no_duplicate_frames(self):
        source = camera_stream.CameraSource()
        with patch.object(camera_stream.cv2, "imencode", return_value=(True, SimpleNamespace(tobytes=lambda: b"jpeg"))) as encode:
            source.set_frame(object())
            first = camera_stream.stream_multipart(source)
            second = camera_stream.stream_multipart(source)
            self.assertEqual(next(first), next(second))
            sequence, jpeg = source.jpeg_after()
            self.assertEqual(jpeg, b"jpeg")
            self.assertIsNone(source.jpeg_after(sequence, timeout=.01)[1])
            client = camera_stream.make_app(source, lambda: True).test_client()
            self.assertEqual(client.get("/snapshot").data, b"jpeg")
            encode.assert_called_once()
            source._frame_ts = time.monotonic() - 999
            self.assertEqual(client.get("/snapshot").status_code, 503)
            source.request_stop()


class AutomationTests(unittest.TestCase):
    def test_save_and_stop_cancel_delay(self):
        for stop in (False, True):
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as directory:
                engine = AutomationEngine(Mock(), Mock(), Path(directory) / "rules.json")
                rule = {"id": "r", "name": "test", "enabled": True,
                        "actions": [{"device": "delay", "seconds": 10}, {"device": "door", "status": "close"}]}
                engine.rules = [rule]
                started = threading.Event()
                original = engine._perform
                def perform(action, rule):
                    started.set()
                    return original(action, rule)
                lock = threading.Lock()
                lock.acquire()
                with patch.object(engine, "_perform", side_effect=perform) as performed, \
                     patch.object(engine, "_write_rules"), \
                     patch("web.automation.engine.validate_rules", return_value=[]):
                    thread = threading.Thread(target=engine._run_actions,
                        args=(rule, rule["actions"], True, "test", lock))
                    thread.start()
                    self.assertTrue(started.wait(1))
                    engine.stop() if stop else engine.save_rules([])
                    thread.join(1)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(performed.call_count, 1)
                    self.assertFalse(lock.locked())


if __name__ == "__main__":
    unittest.main(verbosity=2)
