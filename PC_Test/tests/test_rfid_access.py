# -*- coding: utf-8 -*-
"""刷卡即开门（issue #132）回归测试。

只使用临时 SQLite 与内存事件出口：不碰串口、摄像头、人脸模型。
覆盖点：
  - 已登记卡、未登记卡、停用人员的卡，刷卡都广播 access_granted{method:"rfid"}；
  - 重复读数仍在去抖窗口内只放行一次；
  - 无效卡号不产生通行；
  - 房卡录入会话、人脸识别等其它路径保持原行为。
"""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from web.access_guard import AccessGuard, UNREGISTERED_CARD_LABEL
from web.automation.engine import AutomationEngine
from web.database import SmartHomeDB


class RfidAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = SmartHomeDB(str(Path(self.temp.name) / "smart_home.db"))
        self.guard = AccessGuard(self.db)
        self.events = []
        self.guard.event_sink = self.events.append

    def swipe(self, uid="12:34:56:78"):
        self.guard.on_hardware_event({"event": "rfid", "uid": uid})

    def logs(self):
        return self.db.get_access_logs(limit=50)

    def test_unregistered_card_is_granted(self):
        self.swipe()
        log = self.logs()[0]
        self.assertEqual(log["status"], "granted")
        self.assertEqual(log["access_type"], "rfid")
        self.assertEqual(log["person_name"], UNREGISTERED_CARD_LABEL)
        self.assertEqual(len(self.events), 1)
        event = self.events[0]
        self.assertEqual((event["event"], event["status"], event["method"]),
                         ("access", "granted", "rfid"))

    def test_disabled_person_card_is_granted_and_keeps_name(self):
        person = self.db.create_person("停用人员")
        self.db.set_person_rfid(person["id"], "12:34:56:78")
        self.db.set_person_enabled(person["id"], False)
        self.swipe()
        log = self.logs()[0]
        self.assertEqual(log["status"], "granted")
        self.assertEqual(log["person_name"], "停用人员")
        self.assertEqual(self.events[-1]["person"], "停用人员")

    def test_registered_card_still_grants_and_attributes_person(self):
        person = self.db.create_person("已登记人员")
        self.db.set_person_rfid(person["id"], "12:34:56:78")
        self.swipe()
        log = self.logs()[0]
        self.assertEqual(log["status"], "granted")
        self.assertEqual(log["person_name"], "已登记人员")
        self.assertEqual(self.events[-1]["person"], "已登记人员")

    def test_repeated_swipes_only_grant_once(self):
        self.swipe()
        self.swipe()
        self.assertEqual(len(self.events), 1)
        self.assertEqual(len(self.logs()), 1)

    def test_invalid_card_does_not_grant(self):
        self.swipe("")
        self.assertEqual(self.events, [])
        self.assertEqual(self.logs(), [])

    def test_enrollment_swipe_still_binds_without_opening(self):
        person = self.db.create_person("录入人员")
        session = self.guard.start_card_session(person["id"], person["name"])
        self.swipe()
        self.assertEqual(self.guard.card_session(session["id"])["state"], "matched")
        self.assertEqual(self.events, [])

    def test_unknown_face_is_still_denied(self):
        result = self.guard.handle_face_result("", device_source="test")
        self.assertFalse(result["granted"])
        self.assertEqual(self.logs()[0]["status"], "denied")
        self.assertEqual(self.events[-1]["status"], "denied")

    def test_unregistered_card_reaches_the_door_rule(self):
        """刷卡 → access_granted → 默认 access_open_door → control_door(open)。"""
        bridge = Mock(online=True)
        bridge.control_door.return_value = (True, "ok")
        engine_db = Mock()
        engine_db.get_current_status.return_value = {
            "door_status": "closed", "window_status": "normal",
            "fan_speed": 0, "light_status": "off", "light_brightness": 0}
        engine = AutomationEngine(bridge, engine_db,
                                  Path(self.temp.name) / "automation_rules.json")
        self.addCleanup(engine.stop)
        engine.load()
        # 只验证开门这一段；去掉默认预设里的 10 秒等待，避免测试线程拖住临时目录。
        rule = next(r for r in engine.rules
                    if r.get("preset") == "access_open_door")
        rule["actions"] = [{"device": "door", "status": "open"}]
        self.guard.event_sink = engine.on_event
        self.swipe()
        for _ in range(100):
            if bridge.control_door.called:
                break
            time.sleep(0.02)
        bridge.control_door.assert_called_with("open")


if __name__ == "__main__":
    unittest.main()
