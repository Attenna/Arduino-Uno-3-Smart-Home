import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from web.access_guard import AccessGuard
from web.database import SmartHomeDB


class RfidEnrollmentStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = SmartHomeDB(str(Path(self.temp.name) / "smart_home.db"))
        self.person = self.db.create_person("测试人员")
        self.guard = AccessGuard(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_status_exposes_age_and_remaining_time(self):
        session = self.guard.start_card_session(self.person["id"], self.person["name"])
        status = self.guard.card_session(session["id"])
        self.assertGreaterEqual(status["age_seconds"], 0)
        self.assertGreater(status["remaining_seconds"], 0)

    def test_expiry_has_actionable_reason(self):
        session = self.guard.start_card_session(self.person["id"], self.person["name"])
        with patch("web.access_guard.time.time", return_value=session["expires_at"] + 0.1):
            status = self.guard.card_session(session["id"])
        self.assertEqual(status["state"], "expired")
        # 超时也要给出可操作的原因：RC522 常见「检出卡但读失败」，提示重贴/换卡
        # 比只说"没收到事件"有用（issue #87）。
        self.assertIn("未读到卡", status["error"])
        self.assertIn("重", status["error"])

    def test_bad_reader_event_fails_pending_session_immediately(self):
        session = self.guard.start_card_session(self.person["id"], self.person["name"])
        self.guard.on_hardware_event({"event": "rfid", "uid": ""})
        status = self.guard.card_session(session["id"])
        self.assertEqual(status["state"], "error")
        self.assertIn("无效卡号", status["error"])

    def test_valid_event_binds_card_once(self):
        session = self.guard.start_card_session(self.person["id"], self.person["name"])
        self.guard.on_hardware_event({"event": "rfid", "uid": "12:34:56:78"})
        status = self.guard.card_session(session["id"])
        self.assertEqual(status["state"], "matched")
        self.assertEqual(status["uid"], "12 34 56 78")
        self.assertEqual(self.db.get_person(self.person["id"])["rfid_uid"], "12 34 56 78")


if __name__ == "__main__":
    unittest.main()
