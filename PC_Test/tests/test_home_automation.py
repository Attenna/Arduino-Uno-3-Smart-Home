import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from keypad_code import KeypadCode
from web.automation.engine import AutomationEngine
from web.security_monitor import DoorwayDwell, SecurityMonitor


class HomeRulesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = Mock(online=True)
        for name in ("control_door", "control_window", "control_fan", "control_light"):
            getattr(self.bridge, name).return_value = (True, "ok")
        self.status = dict(fan_speed=0, light_status="off", light_brightness=0, window_status="normal")
        self.db = Mock()
        self.db.get_current_status.side_effect = lambda: dict(self.status)
        self.db.update_status.side_effect = lambda **kw: self.status.update(kw)
        self.engine = AutomationEngine(self.bridge, self.db, Path(self.temp.name) / "rules.json")
        self.engine.load()
        self.addCleanup(self.engine.stop)
        self.rules = {r["preset"]: r for r in self.engine.rules}
        self.snapshot(temperature=27, light=900, motion=True, rain=False, smoke=False, touch=False)

    def snapshot(self, **data):
        self.engine._snapshot.update(data)
        self.engine._snapshot_ts = time.time()

    def apply(self, preset):
        r = self.rules[preset]
        if self.engine._conditions_hold(r, self.engine._context()):
            for action in r["actions"]:
                ok, message = self.engine._perform(action, r)
                self.assertTrue(ok, message)

    def test_occupied_temperature_and_light_hysteresis(self):
        self.apply("temp_hot"); self.apply("light_dark")
        self.assertEqual((self.status["fan_speed"], self.status["light_status"]), (100, "on"))
        self.snapshot(temperature=26, light=700)
        self.apply("temp_cool"); self.apply("light_off")
        self.assertEqual((self.status["fan_speed"], self.status["light_status"]), (100, "on"))
        self.snapshot(temperature=25, light=479)
        self.apply("temp_cool"); self.apply("light_off")
        self.assertEqual((self.status["fan_speed"], self.status["light_status"]), (0, "off"))

    def test_light_band_without_state_does_not_start_light(self):
        # 无历史状态时落在回差区间（670~730）：既不判暗也不判亮，两条光照预设都不动作。
        self.engine._light_dark = None
        self.snapshot(temperature=26, light=700)
        self.apply("temp_hot"); self.apply("light_dark"); self.apply("light_off")
        self.bridge.control_light.assert_not_called()

    def test_light_dark_hysteresis_holds_state_inside_band(self):
        # raw≥730 判暗、raw≤670 判亮，区间内维持上一状态，避免灯光回照自激。
        self.snapshot(temperature=26, light=900)
        self.engine._context()
        self.assertTrue(self.engine._light_dark)
        self.snapshot(temperature=26, light=700)
        self.engine._context()
        self.assertTrue(self.engine._light_dark)
        self.snapshot(temperature=26, light=479)
        self.engine._context()
        self.assertFalse(self.engine._light_dark)

    def test_v8_upgrade_only_updates_light_presets(self):
        old_dark = dict(self.rules["light_dark"])
        old_dark["conditions"] = [dict(c) for c in old_dark["conditions"]]
        old_dark["conditions"][-1] = {
            "sensor": "light", "op": "<", "value": 400}
        old_off = dict(self.rules["light_off"])
        old_off["conditions"] = [dict(c) for c in old_off["conditions"]]
        old_off["conditions"][-1] = {
            "sensor": "light", "op": ">", "value": 700}
        untouched = dict(self.rules["temp_hot"])
        untouched["name"] = "保留的温度规则"
        self.engine.rules_path.write_text(json.dumps({
            "presets_version": 7,
            "rules": [old_dark, old_off, untouched],
        }))

        self.engine.load()
        rules = {r["preset"]: r for r in self.engine.rules}
        dark = rules["light_dark"]["conditions"][-1]
        bright = rules["light_off"]["conditions"][-1]
        self.assertEqual((dark["sensor"], dark["op"], dark["value"]),
                         ("light_dark", "==", True))
        self.assertEqual((bright["sensor"], bright["op"], bright["value"]),
                         ("light_dark", "==", False))
        self.assertEqual(rules["temp_hot"]["name"], "保留的温度规则")
        saved = json.loads(self.engine.rules_path.read_text())
        self.assertEqual(saved["presets_version"], 9)

    def test_access_uses_one_unconditional_open_close_sequence(self):
        r = self.rules["access_open_door"]
        self.assertEqual(r["conditions"], [])
        self.assertEqual(r["actions"], self.rules["touch_open_close"]["actions"])
        self.assertNotIn("access_auto_close", self.rules)

    def test_entry_rechecks_existing_hot_dark_environment(self):
        self.engine.global_state.set_value("g:有人在家", False)
        self.apply("temp_hot"); self.apply("light_dark")
        self.bridge.control_fan.assert_not_called()
        self.apply("presence_motion")
        self.apply("temp_hot"); self.apply("light_dark")
        self.assertEqual(self.status["fan_speed"], 100)
        self.assertEqual(self.status["light_status"], "on")

    def test_away_only_closes_light_and_fan(self):
        self.apply("temp_hot"); self.apply("light_dark")
        self.snapshot(motion=False)
        self.engine.global_state.set_value("g:有人在家", False)
        self.apply("away_close_all")
        self.assertEqual(self.status["fan_speed"], 0)
        self.assertEqual(self.status["light_status"], "off")
        self.bridge.control_window.assert_not_called()

    def test_rain_and_smoke_window_priority_independent_of_presence(self):
        self.engine.global_state.set_value("g:有人在家", False)
        self.engine.global_state.set_value("g:手动优先_窗", True)
        for rain, smoke, expected in [(True,False,"closed"),(True,True,"closed"),
                                      (False,True,"closed"),(False,False,"closed")]:
            self.snapshot(rain=rain,smoke=smoke)
            self.apply("rain_window"); self.apply("window_normal")
            self.assertEqual(self.status["window_status"], expected)
        self.engine.global_state.set_value("g:手动优先_窗", False)
        self.apply("window_normal")
        self.assertEqual(self.status["window_status"], "normal")

    def test_open_window_rechecks_hazard_at_execution(self):
        self.snapshot(smoke=True)
        self.assertFalse(self.engine._perform({"device":"window","status":"normal"})[0])
        self.bridge.control_window.assert_not_called()

    def test_stale_data_cannot_open_window_or_start_fan(self):
        self.engine._snapshot_ts = time.time()-11
        self.apply("window_normal"); self.apply("temp_hot")
        self.bridge.control_window.assert_not_called()
        self.bridge.control_fan.assert_not_called()

    def test_absence_hold_and_disconnection_reset(self):
        r = self.rules["presence_timeout"]
        with patch.object(self.engine, "_fire") as fire, patch("web.automation.engine.time.time", return_value=1000):
            self.engine.on_snapshot(dict(motion=False))
            self.engine.on_snapshot(dict(motion=False))
            fire.assert_not_called()
            self.assertEqual(self.engine._hold_since[r["id"]],1000)
        with patch.object(self.engine, "_fire") as fire, patch("web.automation.engine.time.time", return_value=1121):
            # Gap means no continuous evidence of absence.
            self.engine.on_snapshot(dict(motion=False))
            fire.assert_not_called()
            self.assertEqual(self.engine._hold_since[r["id"]],1121)
        with patch.object(self.engine, "_fire") as fire:
            for now in range(1123,1243,2):
                with patch("web.automation.engine.time.time", return_value=now):
                    self.engine.on_snapshot(dict(motion=False))
            fire.assert_called_once()

    def test_touch_has_open_delay_close_sequence_and_no_startup_open(self):
        r=self.rules["touch_open_close"]
        with patch.object(self.engine,"_fire") as fire:
            # 周期快照（包括启动时已经按住）不应当触发开门。
            self.engine.on_snapshot(dict(touch=True))
            fire.assert_not_called()
            self.engine.on_snapshot(dict(touch=False))
            fire.assert_not_called()
        actions=[]
        lock=threading.Lock(); lock.acquire()
        with patch.object(self.engine,"_perform",side_effect=lambda a,r:(actions.append(a) is None,"ok")):
            self.engine._run_actions(r,r["actions"],True,"touch",lock)
        self.assertEqual(actions,[{"device":"door","status":"open"},
                                  {"device":"delay","seconds":10},
                                  {"device":"door","status":"close"}])

    def test_short_touch_between_snapshots_uses_press_event_once(self):
        self.engine.on_snapshot(dict(touch=False))
        pressed = {'event': 'touch', 'state': True, 'ts': 100}
        released = {'event': 'touch', 'state': False, 'ts': 101}
        with patch.object(self.engine, '_fire') as fire:
            self.engine.on_event(pressed)
            self.engine.on_event(released)
            self.engine.on_event(pressed)  # 同一个事件重放不能再次开门。
            self.engine.on_snapshot(dict(touch=False))
            fire.assert_called_once()
            self.assertEqual(fire.call_args.args[0]['preset'], 'touch_open_close')

    def test_manual_grace_is_immediate_and_repeated_event_renews_it(self):
        r=self.rules["manual_mark_fan"]
        self.engine._perform(r["actions"][0],r)
        self.apply("temp_hot")
        self.bridge.control_fan.assert_not_called()
        waiting=self.rules["manual_clear_fan"]["id"]
        self.engine._hold_since[waiting]=10
        self.engine._perform(r["actions"][0],r)
        self.assertNotIn(waiting,self.engine._hold_since)

    def test_manual_change_invalidates_command_deduplication(self):
        self.apply("temp_hot"); self.apply("temp_hot")
        self.bridge.control_fan.assert_called_once()
        self.status["fan_speed"]=0
        self.apply("temp_hot")
        self.assertEqual(self.bridge.control_fan.call_count,2)

    def test_upgrade_removes_conflicting_presets_and_preserves_custom_rules(self):
        old={"id":"old", "preset":"touch_to_auto", "name":"old", "enabled":True,
             "trigger":{"kind":"sensor","sensor":"touch","op":"==","value":True},
             "actions":[{"device":"door","status":"open"}]}
        custom=dict(old,id="custom",preset=None,name="custom")
        self.engine.rules_path.write_text(json.dumps({"presets_version":5,"rules":[old,custom]}))
        self.engine.load()
        self.assertNotIn("touch_to_auto",[r.get("preset") for r in self.engine.rules])
        self.assertIn("custom",[r["id"] for r in self.engine.rules])
        self.assertTrue(self.engine.global_state.values()["g:允许自动开风扇"])


class KeypadTests(unittest.TestCase):
    def test_complete_attempts_and_success_reset(self):
        keypad=KeypadCode("1111")
        for attempt in range(1,5):
            for digit in "222": self.assertIsNone(keypad.feed(digit))
            self.assertEqual(keypad.feed("2")["failures"],attempt)
        for digit in "111": keypad.feed(digit)
        self.assertEqual(keypad.feed("1")["failures"],0)
        for digit in "222": keypad.feed(digit)
        self.assertEqual(keypad.feed("2")["failures"],1)

    def test_clear_submit_and_timeout(self):
        keypad=KeypadCode("1111",window=10)
        keypad.feed("1",0);keypad.feed("*",1)
        self.assertIsNone(keypad.feed("#",2))
        keypad.feed("1",3)
        self.assertEqual(keypad.feed("#",4)["failures"],1)
        keypad.feed("1",5)
        self.assertIsNone(keypad.feed("1",20))
        self.assertEqual(keypad.buffer,"1")

    def test_gateway_emits_results_without_direct_actuation_or_password(self):
        from mcp_home_server import HomeController
        from collections import deque
        controller=HomeController.__new__(HomeController)
        controller._snapshot_lock=threading.Lock();controller._events=deque(maxlen=64)
        for digit in "2222222222221111": controller._handle_keypad(digit)
        events=list(controller._events)
        self.assertEqual([e["failures"] for e in events if e["event"]=="password_result"],[1,2,3,0])
        self.assertNotIn("1111",json.dumps(events))


class SecurityTests(unittest.TestCase):
    def test_doorway_dwell_distinct_disabled_and_gaps(self):
        disabled=DoorwayDwell()
        self.assertFalse(disabled.feed(50,0));self.assertFalse(disabled.feed(50,60))
        dwell=DoorwayDwell(enabled=True)
        for now in range(0,30,2): self.assertFalse(dwell.feed(100,now))
        self.assertTrue(dwell.feed(100,30));self.assertFalse(dwell.feed(100,32))
        self.assertFalse(dwell.feed(101,34))
        self.assertFalse(dwell.feed(80,36));self.assertFalse(dwell.feed(80,70))
        for invalid in (None,0,-1,float("nan"),True): self.assertFalse(dwell.feed(invalid,72))

    def test_third_and_later_failures_record_even_camera_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor=SecurityMonitor(directory)
            for failures in range(1,5):
                monitor.on_event(dict(event="password_result",status="denied",failures=failures))
            self.assertEqual(monitor.pending.qsize(),2)
            while not monitor.pending.empty(): monitor.capture(monitor.pending.get_nowait())
            events=monitor.events()
            self.assertEqual(len(events),2)
            self.assertTrue(all(e["capture"]=="failed" and e["status"]=="suspicious" for e in events))

    def test_successful_photo_and_indoor_motion_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor=SecurityMonitor(directory,{"camera":{"stream_url":"http://camera/video_feed"},
                                               "security":{"doorway":{"enabled":True}}})
            monitor.on_snapshot({"motion":True,"distance":20})
            self.assertEqual(monitor.events(),[])
            event=monitor.record("keypad_failures",{"failures":3})
            response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            response.read.return_value=b"\xff\xd8photo\xff\xd9"
            with patch("web.security_monitor.urllib.request.urlopen",return_value=response): monitor.capture(event)
            self.assertEqual(monitor.events()[0]["capture"],"saved")
            self.assertTrue((Path(directory)/(event["id"]+".jpg")).exists())

    def test_restart_marks_pending_capture_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor=SecurityMonitor(directory)
            monitor.record("keypad_failures",{"failures":3})
            replacement=SecurityMonitor(directory)
            replacement.start()
            replacement.stop()
            self.assertEqual(replacement.events()[0]["capture"],"failed")

    def test_security_endpoints_require_login(self):
        from web.app import create_app
        from werkzeug.security import generate_password_hash
        # 可独立运行，不依赖 test_hardening 模块先初始化认证环境。
        with patch.dict('os.environ', {
            'SMART_HOME_ADMIN_USER': 'test-admin',
            'SMART_HOME_ADMIN_PASSWORD_HASH': generate_password_hash('test-password'),
            'SMART_HOME_SESSION_SECRET': 's' * 48,
            'SMART_HOME_SERVICE_TOKEN': 't' * 48,
        }):
            app=create_app({"serial":{"enabled":False}},start_hardware=False)
        client=app.test_client()
        self.assertEqual(client.get("/api/security/events").status_code,401)
        self.assertEqual(client.get("/api/security/images/"+"a"*32).status_code,401)
        with client.session_transaction() as session: session["user"]="test-admin"
        self.assertEqual(client.get("/security").status_code,200)
        self.assertEqual(client.get("/api/security/images/bad").status_code,404)

