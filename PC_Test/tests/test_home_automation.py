import contextlib
import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from keypad_code import KeypadCode
from web.automation.capabilities import DELAY_MAX_SECONDS
from web.automation.default_rules import PRESETS_VERSION
from web.automation.engine import (SAFETY_RETRY, AutomationEngine,
                                   _is_safety_action)
from web.automation.schema import (ValidationError, validate_action,
                                   validate_condition, validate_rule)
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
        self.assertEqual(saved["presets_version"], PRESETS_VERSION)

    def test_upgrade_keeps_preset_content_customised_by_user(self):
        # R4：与旧内置版不一致（用户改过）就不覆盖，只记一条告警
        mine = dict(self.rules["light_dark"])
        mine["conditions"] = [dict(c) for c in mine["conditions"]]
        mine["conditions"][-1] = {"sensor": "light", "op": "<", "value": 500}
        self.engine.rules_path.write_text(json.dumps({
            "presets_version": 7,
            "rules": [mine],
        }))
        self.engine.load()
        rules = {r["preset"]: r for r in self.engine.rules}
        dark = rules["light_dark"]["conditions"][-1]
        self.assertEqual((dark["sensor"], dark["op"], dark["value"]),
                         ("light", "<", 500))
        info = self.engine.consume_migration_info()
        self.assertTrue(any("已保留你的版本" in w for w in info["warnings"]))

    def test_upgrade_adds_manual_priority_gate_to_unmodified_window_normal(self):
        # R2/R4：v8 的 window_normal 与旧内置版一致 → 换成带「手动优先让位」的 v9
        self.engine.rules_path.write_text(json.dumps({
            "presets_version": 8,
            "rules": [{"preset": "window_normal", "name": "无雨无烟：恢复45°",
                       "enabled": True,
                       "trigger": {"kind": "interval", "seconds": 2},
                       "conditions": [{"sensor": "sensor_fresh", "op": "==", "value": True},
                                      {"sensor": "rain", "op": "==", "value": False},
                                      {"sensor": "smoke", "op": "==", "value": False}],
                       "actions": [{"device": "window", "status": "normal"}],
                       "match": "all", "cooldown": 0}],
        }))
        self.engine.load()
        rules = {r["preset"]: r for r in self.engine.rules}
        self.assertIn("g:手动优先_窗",
                      [c["sensor"] for c in rules["window_normal"]["conditions"]])

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
        # 雨水/烟雾关窗是安全动作：不看有人无人在家，也不让位给「手动优先」
        self.engine.global_state.set_value("g:有人在家", False)
        self.engine.global_state.set_value("g:手动优先_窗", True)
        for rain, smoke, expected in [(True,False,"closed"),(True,True,"closed"),
                                      (False,True,"closed"),(False,False,"closed")]:
            self.snapshot(rain=rain,smoke=smoke)
            self.apply("rain_window"); self.apply("window_normal")
            self.assertEqual(self.status["window_status"], expected)
        # 手动优先释放后，无雨无烟才恢复 45°（R2：window_normal 让位给手动操作）
        self.snapshot(rain=False,smoke=False)
        self.engine.global_state.set_value("g:手动优先_窗", False)
        self.apply("window_normal")
        self.assertEqual(self.status["window_status"], "normal")
        self.assertNotIn("g:手动优先_窗",
                         [c["sensor"] for c in self.rules["rain_window"]["conditions"]])

    def test_open_window_rechecks_hazard_at_execution(self):
        self.snapshot(smoke=True)
        self.assertFalse(self.engine._perform({"device":"window","status":"normal"})[0])
        self.bridge.control_window.assert_not_called()

    def test_stale_data_cannot_open_window_or_start_fan(self):
        self.engine._snapshot_ts = time.time()-11
        self.apply("window_normal"); self.apply("temp_hot")
        self.bridge.control_window.assert_not_called()
        self.bridge.control_fan.assert_not_called()

    @contextlib.contextmanager
    def clock(self, at):
        """同刻固定墙钟与单调时钟：hold/冷却用单调钟、快照陈旧判定用墙钟。"""
        with patch("web.automation.engine.time.time", return_value=at), \
                patch("web.automation.engine.time.monotonic", return_value=at):
            yield

    def test_absence_hold_and_disconnection_reset(self):
        r = self.rules["presence_timeout"]
        with patch.object(self.engine, "_fire") as fire, self.clock(1000):
            self.engine.on_snapshot(dict(motion=False))
            self.engine.on_snapshot(dict(motion=False))
            fire.assert_not_called()
            self.assertEqual(self.engine._hold_since[r["id"]],1000)
        with patch.object(self.engine, "_fire") as fire, self.clock(1121):
            # Gap means no continuous evidence of absence.
            self.engine.on_snapshot(dict(motion=False))
            fire.assert_not_called()
            self.assertEqual(self.engine._hold_since[r["id"]],1121)
        with patch.object(self.engine, "_fire") as fire:
            for now in range(1123,1243,2):
                with self.clock(now):
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


class AutomationRiskTests(unittest.TestCase):
    """issue-blocks-automation-risks（R1–R10）的定向回归。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = Mock(online=True)
        for name in ("control_door", "control_window", "control_fan", "control_light"):
            getattr(self.bridge, name).return_value = (True, "ok")
        self.status = dict(fan_speed=0, light_status="off",
                           light_brightness=0, window_status="normal")
        self.db = Mock()
        self.db.get_current_status.side_effect = lambda: dict(self.status)
        self.db.update_status.side_effect = lambda **kw: self.status.update(kw)
        self.engine = AutomationEngine(self.bridge, self.db,
                                       Path(self.temp.name) / "rules.json")
        self.engine.load()
        self.addCleanup(self.engine.stop)

    def snapshot(self, **data):
        self.engine._snapshot.update(data)
        self.engine._snapshot_ts = time.time()

    def test_R1_ac_fan_enum_accepts_legacy_levels(self):
        def fan_level(raw):
            rule = validate_rule(dict(
                name="空调", trigger=dict(kind="time", hhmm="08:00"), conditions=[],
                actions=[dict(device="ac", temperature=26, fan=raw)]))
            return rule["actions"][0]["fan"]
        for raw, want in [("low", "low"), ("MID", "mid"), ("60", "mid"),
                          ("100", "high"), (20, "low"), ("auto", "auto")]:
            self.assertEqual(fan_level(raw), want)
        with self.assertRaises(ValidationError):
            fan_level("turbo")

    def test_R7_comparison_checked_by_source_kind_on_save(self):
        for bad in [dict(sensor="temperature", op=">", value="26"),
                    dict(sensor="temperature", op=">", value=999),
                    dict(sensor="light_dark", op=">", value=True),
                    dict(sensor="ac_mode", op="==", value="turbo")]:
            with self.assertRaises(ValidationError):
                validate_condition(dict(bad))
        # 宽松模式（引擎读盘）不拒绝历史脏值，只把数字字符串归一
        clean = validate_condition(dict(sensor="temperature", op=">", value="26"),
                                   strict=False)
        self.assertEqual(clean["value"], 26)

    def test_R8_state_action_checked_against_variable_definition(self):
        info = {"g:全屋模式": {"type": "enum", "label": "全屋模式",
                               "choices": ["auto", "manual", "away"]}}
        ok = validate_action(dict(device="state", name="g:全屋模式",
                                  op="set", value="away"), vars_info=info)
        self.assertEqual(ok["value"], "away")
        for bad in [dict(device="state", name="g:全屋模式", op="set", value="party"),
                    dict(device="state", name="g:全屋模式", op="add", value=1),
                    dict(device="state", name="g:全屋模式", op="toggle")]:
            with self.assertRaises(ValidationError):
                validate_action(dict(bad), vars_info=info)
        # 宽松模式：变量被删掉也不该让整条规则失效
        validate_action(dict(device="state", name="g:已删除", op="set", value="x"),
                        strict=False)

    def test_R9_event_rule_requires_matching_payload(self):
        self.engine.rules = [validate_rule(dict(
            id="touch", name="触摸开门", enabled=True,
            trigger=dict(kind="event", event="touch_on"), conditions=[],
            actions=[dict(device="door", status="open")], cooldown=0))]
        with patch.object(self.engine, "_fire") as fire:
            self.engine.on_event(dict(event="motion", state=True))
            self.engine.on_event(dict(event="touch", state=False))
            fire.assert_not_called()
            self.engine.on_event(dict(event="touch", state=True))
            fire.assert_called_once()

    def test_R10_time_trigger_catches_up_inside_window(self):
        rule = validate_rule(dict(
            id="t", name="定时", enabled=True,
            trigger=dict(kind="time", hhmm="07:30"), conditions=[],
            actions=[dict(device="fan", op="off", speed=0)], cooldown=0))
        with patch.object(self.engine, "_fire") as fire:
            self.engine._maybe_fire_time(rule, datetime(2026, 10, 8, 7, 31))
            self.engine._maybe_fire_time(rule, datetime(2026, 10, 8, 7, 32))
            fire.assert_called_once()
            # 超出补触发窗口（300 秒）后当天不再补
            self.engine._maybe_fire_time(rule, datetime(2026, 10, 8, 7, 40))
            fire.assert_called_once()

    def test_R6_hold_marks_fired_only_when_enqueued(self):
        rule = validate_rule(dict(
            id="h", name="烟雾持续", enabled=True,
            trigger=dict(kind="sensor", sensor="smoke", op="==", value=True,
                         hold_sec=2), conditions=[],
            actions=[dict(device="buzzer", mode="beep", count=1)], cooldown=0))
        self.engine.rules = [rule]
        self.snapshot(smoke=True)
        self.engine._armed.add("h")
        self.engine._prev_trigger["h"] = True
        self.engine._hold_since["h"] = time.monotonic() - 10
        with patch.object(self.engine, "_fire", return_value=False):
            self.engine._evaluate_sensor_rule(rule)
            self.assertFalse(self.engine._hold_fired.get("h"))
        with patch.object(self.engine, "_fire", return_value=True):
            self.engine._evaluate_sensor_rule(rule)
            self.assertTrue(self.engine._hold_fired["h"])

    def test_R3_tick_evaluates_state_source_rules(self):
        # A 板离线（从未 on_snapshot）时，g: 触发也要能到期释放
        rule = validate_rule(dict(
            id="g1", name="状态触发", enabled=True,
            trigger=dict(kind="sensor", sensor="g:有人在家", op="==", value=True,
                         hold_sec=1), conditions=[],
            actions=[dict(device="state", name="g:全屋模式", op="set", value="away")],
            cooldown=0))
        self.engine.rules = [rule]
        self.engine.global_state.set_value("g:有人在家", True)
        self.engine._armed.add("g1")
        self.engine._prev_trigger["g1"] = True
        self.engine._hold_since["g1"] = time.monotonic() - 10
        thread = threading.Thread(target=self.engine._tick_loop, daemon=True)
        thread.start()
        deadline = time.time() + 3
        while time.time() < deadline and not self.engine._hold_fired.get("g1"):
            time.sleep(0.05)
        self.engine._stopping = True
        thread.join(timeout=3)
        self.assertTrue(self.engine._hold_fired.get("g1"))

    def test_R5_safety_action_retries_then_flags_partial(self):
        rule = dict(id="s", name="关窗", actions=[{"device": "window", "status": "close"}])
        self.engine.rules = [rule]
        self.bridge.control_window.return_value = (False, "串口忙")
        lock = threading.Lock()
        lock.acquire()
        with patch("web.automation.engine.SAFETY_RETRY_DELAY", 0), \
                patch.object(self.engine, "_log") as log:
            self.engine._run_actions(rule, rule["actions"], True, "测试", lock)
        self.assertEqual(self.bridge.control_window.call_count, 1 + SAFETY_RETRY)
        detail = log.call_args.kwargs["detail"]
        self.assertFalse(detail[-1]["ok"])
        self.assertTrue(detail[-1]["partial"])

    def test_R5_non_safety_action_fails_fast(self):
        rule = dict(id="o", name="开门", actions=[{"device": "door", "status": "open"}])
        self.engine.rules = [rule]
        self.bridge.control_door.return_value = (False, "串口忙")
        lock = threading.Lock()
        lock.acquire()
        with patch("web.automation.engine.SAFETY_RETRY_DELAY", 0), \
                patch.object(self.engine, "_log"):
            self.engine._run_actions(rule, rule["actions"], True, "测试", lock)
        self.assertEqual(self.bridge.control_door.call_count, 1)

    def test_R2_door_ac_manual_priority_write_only_presets_removed(self):
        from web.automation.default_rules import DEFAULT_RULES
        presets = {r.get("preset") for r in DEFAULT_RULES}
        for gone in ("manual_mark_door", "manual_clear_door",
                     "manual_mark_ac", "manual_clear_ac"):
            self.assertNotIn(gone, presets)
        # 门/空调不再写「只写不读」的手动优先变量
        door_rule = next(r for r in DEFAULT_RULES
                         if r.get("preset") == "ir_remote_door_toggle")
        for key in ("actions", "else_actions"):
            for act in door_rule.get(key) or []:
                self.assertNotEqual(act.get("name"), "g:手动优先_门")
        # 旧文件里遗留的这几条预设要被迁移丢弃，不回到规则集
        self.engine.rules_path.write_text(json.dumps({
            "presets_version": 9,
            "rules": [{"id": "d1", "preset": "manual_mark_door", "name": "旧门优先",
                       "enabled": True,
                       "trigger": {"kind": "event", "event": "manual_control",
                                   "device": "door"},
                       "actions": [{"device": "state", "name": "g:手动优先_门",
                                    "op": "set", "value": True}],
                       "cooldown": 0}]}))
        self.engine.load()
        self.assertEqual(
            [r for r in self.engine.rules if r.get("preset") == "manual_mark_door"], [])

    def test_R14_unexpected_action_exception_is_logged(self):
        rule = self.engine.rules[0]
        captured = []
        self.engine._log = lambda *a, **k: captured.append(k)
        lock = threading.Lock()
        lock.acquire()
        with patch.object(self.engine, "_perform_with_retry",
                          side_effect=RuntimeError("boom")):
            self.engine._run_actions(rule, [{"device": "fan", "speed": 10}],
                                     True, "测试", lock)
        self.assertEqual(len(captured), 1)
        self.assertFalse(captured[0]["ok"])
        self.assertTrue(any("执行异常" in (d.get("result") or "")
                            for d in captured[0]["detail"]))
        self.assertTrue(lock.acquire(blocking=False), "动作锁未释放")


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


class AccessPathCloseoutTests(unittest.TestCase):
    """issue #19 收尾：门禁行为由 Blocks 规则决定。

    - 删光全部规则（含内置预设）后，触摸 / 门禁通过这类「自动化行为」不再产生任何
      开门动作，且被删预设不会在重启时被 seed_presets 重新注入；
    - 面板这类「用户显式指令」仍直达硬件，行为不受规则集影响。
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = Mock(online=True)
        for name in ("control_door", "control_window", "control_fan", "control_light"):
            getattr(self.bridge, name).return_value = (True, "ok")
        self.db = Mock()
        self.db.get_current_status.return_value = dict(
            door_status="closed", window_status="normal", fan_speed=0,
            light_status="off", light_brightness=0)
        self.engine = AutomationEngine(self.bridge, self.db,
                                       Path(self.temp.name) / "rules.json")
        self.engine.load()
        self.addCleanup(self.engine.stop)

    def test_default_rules_fire_then_deletion_stops_automation_door(self):
        # 基线：内置预设里，触摸与门禁通过各有一条会开门的规则
        door_presets = {r.get("preset") for r in self.engine.rules
                        if any(a.get("device") == "door"
                               for a in r.get("actions") or [])}
        self.assertTrue({"touch_open_close", "access_open_door"} <= door_presets)
        with patch.object(self.engine, "_fire") as fire:
            self.engine.on_event({"event": "touch", "state": True, "ts": 1})
            self.engine.on_event({"event": "access", "status": "granted",
                                  "method": "keypad", "ts": 2})
            self.assertEqual({c.args[0]["preset"] for c in fire.call_args_list},
                             {"touch_open_close", "access_open_door"})

        # 用户删光全部规则后，同两个自动化触发既不开火也不再下发开门动作
        self.engine.save_rules([])
        with patch.object(self.engine, "_fire") as fire:
            self.engine.on_event({"event": "touch", "state": True, "ts": 3})
            self.engine.on_event({"event": "access", "status": "granted",
                                  "method": "keypad", "ts": 4})
            fire.assert_not_called()
        self.bridge.control_door.assert_not_called()

        # 重启不得把删掉的预设塞回来（按下 presets_seen 记名）
        self.engine.load()
        self.assertEqual(self.engine.rules, [])

    def test_explicit_panel_door_command_ignores_rule_set(self):
        """面板按钮是「用户显式指令」：规则被删光也照常直达硬件。"""
        from werkzeug.security import generate_password_hash
        from web import extensions as ext_module
        from web.app import create_app
        from web.api import devices
        from web.database import SmartHomeDB

        env = {"SMART_HOME_ADMIN_USER": "test-admin",
               "SMART_HOME_ADMIN_PASSWORD_HASH": generate_password_hash("x"),
               "SMART_HOME_SESSION_SECRET": "s" * 48,
               "SMART_HOME_SERVICE_TOKEN": "t" * 48}
        with patch.dict(os.environ, env), tempfile.TemporaryDirectory() as directory:
            app = create_app({"serial": {"enabled": False}}, start_hardware=False)
            app.testing = True
            client = app.test_client()
            with client.session_transaction() as session:
                session["user"] = "test-admin"
            db = SmartHomeDB(str(Path(directory) / "smart_home.db"))
            hardware = Mock(return_value=(True, "ok"))
            # automation 置空：只验证「显式指令不经过规则集」，不牵动其它用例的引擎
            with patch.object(ext_module, "automation", None), \
                    patch.object(devices, "db", db), \
                    patch.object(devices, "_hw_call", hardware):
                response = client.post("/api/door", json={"status": "open"},
                                       headers={"Origin": "http://localhost"})
            self.assertEqual(response.status_code, 200)
            hardware.assert_called_once_with("control_door", "open")
            self.assertEqual(db.get_current_status()["door_status"], "open")


class SleepBlockTests(unittest.TestCase):
    """issue #20：等待（延时）上限放宽到 1 小时，且语义明确。

    - 校验：1~``DELAY_MAX_SECONDS`` 秒可用，越界/非数字被拒；
    - 取消：等待期间同规则被取消（停用 / 保存规则集 / 服务停止）会立即中断；
    - 重启：等待是内存里的运行态、不落盘，重启不补执行任何延时动作。
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = Mock(online=True)
        for name in ("control_door", "control_window", "control_fan", "control_light"):
            getattr(self.bridge, name).return_value = (True, "ok")
        self.db = Mock()
        self.db.get_current_status.return_value = dict(
            door_status="closed", window_status="normal", fan_speed=0,
            light_status="off", light_brightness=0)
        self.engine = AutomationEngine(self.bridge, self.db,
                                       Path(self.temp.name) / "rules.json")

    def test_delay_seconds_validation_bounds(self):
        def seconds(value):
            return validate_action({"device": "delay", "seconds": value})["seconds"]

        self.assertEqual(seconds(1), 1)
        self.assertEqual(seconds(DELAY_MAX_SECONDS), DELAY_MAX_SECONDS)
        self.assertGreater(DELAY_MAX_SECONDS, 300, "上限应已放宽到超过旧的 300 秒")
        for bad in (0, -1, DELAY_MAX_SECONDS + 1, "abc"):
            with self.assertRaises(ValidationError):
                seconds(bad)

    def test_long_delay_is_cancelled_promptly(self):
        rule = dict(id="d", name="延时后关门",
                    actions=[{"device": "delay", "seconds": 600},
                             {"device": "door", "status": "close"}])
        self.engine.rules = [rule]
        lock = threading.Lock()
        lock.acquire()
        done = threading.Event()
        logs = []

        def run():
            try:
                self.engine._run_actions(rule, rule["actions"], True, "测试", lock)
            finally:
                done.set()

        self.engine._log = lambda *a, **k: logs.append(k)
        threading.Thread(target=run, daemon=True).start()
        for _ in range(100):                        # 等它真正进入等待
            if self.engine._running.get(rule["id"]):
                break
            time.sleep(0.02)
        started = time.monotonic()
        self.engine._running[rule["id"]].set()      # 等价于停用/保存/停止
        self.assertTrue(done.wait(2), "取消后延时线程应立即结束，不再睡满 600 秒")
        self.assertLess(time.monotonic() - started, 2)
        self.bridge.control_door.assert_not_called()
        self.assertTrue(logs, "取消后应留下一条执行日志")
        last = logs[0]["detail"][-1]
        self.assertFalse(last.get("ok"))
        self.assertIn("取消", str(last.get("result") or ""))
        self.assertFalse(lock.locked(), "动作锁应已释放")

    def test_waiting_is_not_persisted_and_restart_never_replays_it(self):
        rule = dict(id="d", name="延时后关门", enabled=True,
                    trigger={"kind": "event", "event": "access_granted"},
                    conditions=[],
                    actions=[{"device": "door", "status": "open"},
                             {"device": "delay", "seconds": 600},
                             {"device": "door", "status": "close"}],
                    else_actions=[], cooldown=0)
        self.engine.save_rules([rule])

        # 落盘的只有规则配置：没有「剩余秒数 / 截止时刻 / 待执行」这类调度状态
        flat = json.dumps(json.loads(self.engine.rules_path.read_text()),
                          ensure_ascii=False)
        for key in ("pending", "remaining", "deadline", "scheduled", "fire_at"):
            self.assertNotIn(key, flat)

        # 模拟重启：新引擎从同一份规则文件加载，不补执行任何等待中的动作
        bridge = Mock(online=True)
        bridge.control_door.return_value = (True, "ok")
        restarted = AutomationEngine(bridge, self.db, self.engine.rules_path)
        self.addCleanup(restarted.stop)
        restarted.load()
        restarted.bridge.control_door.assert_not_called()
        self.assertEqual(restarted._running, {})


class WaitBlockTests(unittest.TestCase):
    """issue #100：「等待事件」动作——等到条件成立再继续，超时必填且有上界。

    覆盖：校验（超时必填/越界、非法比较符、未知源、按源类型归一阈值）、
    立即成立 / 等待中转真 / 超时 / 取消四条执行路径，以及「等待不参与安全重试、
    不持久化运行态」。
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = Mock(online=True)
        for name in ("control_door", "control_window", "control_fan", "control_light"):
            getattr(self.bridge, name).return_value = (True, "ok")
        self.db = Mock()
        self.status = {"door_status": "open", "window_status": "normal",
                       "fan_speed": 0, "light_status": "off", "light_brightness": 0}
        self.db.get_current_status.side_effect = lambda: dict(self.status)
        self.engine = AutomationEngine(self.bridge, self.db,
                                       Path(self.temp.name) / "rules.json")
        self.engine.load()
        self.addCleanup(self.engine.stop)

    @staticmethod
    def _wait(**kwargs):
        action = {"device": "wait", "sensor": "door_status", "op": "==",
                  "value": "closed", "timeout_sec": 30}
        action.update(kwargs)
        return action

    def test_timeout_is_required_and_bounded(self):
        self.assertEqual(validate_action(self._wait())["timeout_sec"], 30)
        self.assertEqual(validate_action(self._wait(timeout_sec=DELAY_MAX_SECONDS))["timeout_sec"],
                         DELAY_MAX_SECONDS)
        for bad in (0, -1, DELAY_MAX_SECONDS + 1, "abc"):
            with self.assertRaises(ValidationError):
                validate_action(self._wait(timeout_sec=bad))
        # 超时必填：缺省即拒绝（#20 验收 3：等待必须有上界）
        with self.assertRaises(ValidationError):
            validate_action({"device": "wait", "sensor": "door_status",
                             "op": "==", "value": "closed"})

    def test_source_and_value_checked_like_a_condition(self):
        with self.assertRaises(ValidationError):
            validate_action(self._wait(op="~"))                  # 非法比较符
        with self.assertRaises(ValidationError):
            validate_action(self._wait(sensor="nope"))           # 未知源
        with self.assertRaises(ValidationError):
            validate_action(self._wait(value="ajar"))            # 枚举源非法取值
        # 布尔源：字符串 "true" 归一成 True
        cleaned = validate_action(self._wait(sensor="motion", value="true"))
        self.assertIs(cleaned["value"], True)

    def test_wait_is_not_a_safety_action(self):
        self.assertFalse(_is_safety_action(self._wait()))

    def test_returns_immediately_when_condition_already_holds(self):
        self.status["door_status"] = "closed"
        started = time.monotonic()
        ok, msg = self.engine._perform(self._wait(timeout_sec=5))
        self.assertTrue(ok, msg)
        self.assertIn("成立", msg)
        self.assertLess(time.monotonic() - started, 1)

    def test_succeeds_when_condition_becomes_true(self):
        threading.Thread(target=lambda: (time.sleep(0.4),
                                         self.status.update(door_status="closed")),
                         daemon=True).start()
        started = time.monotonic()
        ok, msg = self.engine._perform(self._wait(timeout_sec=5))
        self.assertTrue(ok, msg)
        self.assertLess(time.monotonic() - started, 3)

    def test_times_out_within_bound(self):
        started = time.monotonic()
        ok, msg = self.engine._perform(self._wait(timeout_sec=1))
        elapsed = time.monotonic() - started
        self.assertFalse(ok)
        self.assertIn("超时", msg)
        self.assertGreaterEqual(elapsed, 1.0)
        self.assertLess(elapsed, 3)

    def test_can_be_cancelled_promptly(self):
        rule = dict(id="w", name="等到关门", actions=[self._wait(timeout_sec=600)])
        self.engine.rules = [rule]
        lock = threading.Lock()
        lock.acquire()
        done = threading.Event()
        logs = []
        self.engine._log = lambda *a, **k: logs.append(k)

        def run():
            try:
                self.engine._run_actions(rule, rule["actions"], True, "测试", lock)
            finally:
                done.set()

        threading.Thread(target=run, daemon=True).start()
        for _ in range(100):                        # 等它真正进入等待
            if self.engine._running.get(rule["id"]):
                break
            time.sleep(0.02)
        started = time.monotonic()
        self.engine._running[rule["id"]].set()      # 等价于停用/保存/停止
        self.assertTrue(done.wait(2), "取消后等待线程应立即结束，不再等满 600 秒")
        self.assertLess(time.monotonic() - started, 2)
        self.assertFalse(lock.locked(), "动作锁应已释放")
        last = logs[0]["detail"][-1]
        self.assertFalse(last.get("ok"))
        self.assertIn("取消", str(last.get("result") or ""))

    def test_rule_round_trips_and_not_persisted(self):
        rule = dict(id="w", name="等到关门后收尾", enabled=True,
                    trigger={"kind": "event", "event": "access_granted"},
                    conditions=[],
                    actions=[self._wait(timeout_sec=15),
                             {"device": "door", "status": "close"}],
                    else_actions=[], cooldown=0)
        saved = self.engine.save_rules([rule])
        act = saved[0]["actions"][0]
        self.assertEqual(act, {"device": "wait", "sensor": "door_status", "op": "==",
                               "value": "closed", "timeout_sec": 15})
        # 落盘只有动作配置：没有「剩余秒数 / 截止时刻 / 待执行」这类调度状态
        flat = json.dumps(json.loads(self.engine.rules_path.read_text(encoding="utf-8")),
                          ensure_ascii=False)
        for key in ("pending", "remaining", "deadline", "scheduled", "fire_at"):
            self.assertNotIn(key, flat)


class GatingPresetTests(unittest.TestCase):
    """issue #77：门控维护预设名单的完整性——不漂移、不误报。"""

    def test_listed_presets_exist_and_include_the_culprits(self):
        from web.automation.default_rules import DEFAULT_RULES, GATING_PRESETS
        presets = {r.get("preset") for r in DEFAULT_RULES}
        self.assertTrue(GATING_PRESETS)
        # 名单里的每个预设都要真实存在，否则改名后名单会静默失效
        for pid in GATING_PRESETS:
            self.assertIn(pid, presets, f"门控名单里的 {pid} 已不在默认规则里")
        # #77 的两个当事者必须在名单里
        self.assertIn("presence_motion", GATING_PRESETS)
        self.assertIn("manual_clear_light", GATING_PRESETS)

    def test_listed_presets_write_gating_state(self):
        from web.automation.default_rules import DEFAULT_RULES, GATING_PRESETS
        by_preset = {r["preset"]: r for r in DEFAULT_RULES if r.get("preset")}
        for pid in GATING_PRESETS:
            names = [a.get("name")
                     for key in ("actions", "else_actions")
                     for a in by_preset[pid].get(key) or []
                     if a.get("device") == "state"]
            self.assertTrue(
                any(str(n) in ("g:有人在家", "g:全屋模式")
                    or str(n).startswith("g:手动优先_") for n in names),
                f"{pid} 被列为门控预设，却没写任何门控变量")

    def test_incidental_writers_are_not_flagged(self):
        from web.automation.default_rules import GATING_PRESETS
        # 红外切换只是顺带写 g:手动优先_x，主职不是维护门控；不写门控变量的更不该上报
        for pid in ("ir_remote_light_toggle", "ir_remote_fan_toggle",
                    "ir_remote_window_toggle", "temp_hot", "light_dark", "smoke_buzzer"):
            self.assertNotIn(pid, GATING_PRESETS)
