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
from web.api import access, devices, status
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
