"""#27：灯的亮度 / 色温 / 自定义颜色要能互相转化，且不再互相冲掉。

分四层看：
  * light_state 的纯函数口径（亮法归一、缺省继承、亮度 0 的语义）；
  * /api/light 端到端：下发后**库里**记的是什么（临时 SQLite，不碰开发库）；
  * 语音工具网关：MCP 的 0~255 参数换算成面板等效状态；
  * 自动化规则：规则改灯后库里的亮法要跟着变。
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from werkzeug.security import generate_password_hash

os.environ.update(SMART_HOME_ADMIN_USER="test-admin",
                  SMART_HOME_ADMIN_PASSWORD_HASH=generate_password_hash("test-password"),
                  SMART_HOME_SESSION_SECRET="s" * 48,
                  SMART_HOME_SERVICE_TOKEN="t" * 48)

from web import light_state as ls
from web.app import create_app
from web.api import devices, status
from web.database import SmartHomeDB


class StyleResolutionTests(unittest.TestCase):
    def test_rgb_wins_over_temp_and_mode(self):
        self.assertEqual(ls.resolve(mode="night", temp=3000, rgb=[1, 2, 3]),
                         ("rgb", None, (1, 2, 3)))
        self.assertEqual(ls.resolve(mode="white", temp=9000), ("temp", 6500, None))

    def test_mode_temp_or_rgb_without_parameters_falls_back_to_white(self):
        # 固件需要 K 值或 (r,g,b) 才能下发，缺了只能当普通白光，不能凭空猜颜色
        self.assertEqual(ls.resolve(mode="temp"), ("white", None, None))
        self.assertEqual(ls.resolve(mode="rgb"), ("white", None, None))

    def test_request_without_any_style_key_means_keep_current(self):
        self.assertIsNone(ls.from_request({"status": "on", "brightness": 40}))
        self.assertEqual(ls.from_request({"mode": "night"}), ("night", None, None))
        self.assertEqual(ls.from_request({"rgb": [255, 128, 0]}),
                         ("rgb", None, (255, 128, 0)))

    def test_brightness_zero_and_off_are_the_same_state(self):
        self.assertEqual(ls.target_from_request({"status": "on", "brightness": 0}, 80),
                         ("off", 0))
        # 只改亮法的命令不带亮度：沿用当前值，绝不能被打回 0（那等于关灯）
        self.assertEqual(ls.target_from_request({"status": "on", "temp": 4000}, 42),
                         ("on", 42))
        self.assertEqual(ls.target_from_request({"status": "on"}, 0), ("on", 100))
        self.assertEqual(ls.status_values("off", 80, ("temp", 4000, None))["light_status"], "off")
        self.assertEqual(ls.status_values("off", 80, ("temp", 4000, None))["light_temp"], 4000)

    def test_db_field_round_trip(self):
        self.assertEqual(ls.rgb_field((255, 128, 0)), "255,128,0")
        self.assertEqual(ls.parse_rgb("255,128,0"), (255, 128, 0))
        self.assertEqual(ls.from_status({"light_mode": "rgb", "light_rgb": "10,20,30"}),
                         ("rgb", None, (10, 20, 30)))
        # 没写过亮法的旧库、以及「mode=temp 却没有 K」的残缺行都退回白光
        self.assertEqual(ls.from_status({}), ("white", None, None))
        self.assertEqual(ls.from_status({"light_mode": "temp"}), ("white", None, None))

    def test_tool_arguments_become_panel_equivalent_state(self):
        self.assertEqual(ls.from_tool_args({"action": "off"}), ("off", 0, None))
        # 缺省值按固件口径补全，语音只说「开灯」时面板记的亮度才是真的
        self.assertEqual(ls.from_tool_args({"action": "white"}),
                         ("on", 100, ("white", None, None)))
        self.assertEqual(ls.from_tool_args({"action": "night"}),
                         ("on", 24, ("night", None, None)))
        self.assertEqual(ls.from_tool_args({"action": "temp", "temp": 4000, "value": 128}),
                         ("on", 50, ("temp", 4000, None)))
        self.assertEqual(ls.from_tool_args({"action": "red"}),
                         ("on", 100, ("rgb", None, (255, 0, 0))))
        # value=0 在任何亮法上都是关灯
        for args in ({"action": "night", "value": 0}, {"action": "temp", "temp": 3000, "value": 0}):
            self.assertEqual(ls.from_tool_args(args), ("off", 0, None))
        # 工具侧会直接报错、不动硬件的调用没有状态可记
        self.assertIsNone(ls.from_tool_args({"action": "temp"}))
        self.assertIsNone(ls.from_tool_args({"action": "rgb", "r": 1}))
        self.assertIsNone(ls.from_tool_args({"action": "bogus"}))

    def test_hardware_plan_picks_one_firmware_command(self):
        self.assertEqual(ls.hardware_plan("off", 80, ("rgb", None, (1, 2, 3))),
                         ("control_light", ("off", 0), {}))
        self.assertEqual(ls.hardware_plan("on", 80, ("rgb", None, (255, 0, 0))),
                         ("control_light_color", ("rgb", 255, 0, 0), {"brightness_pct": 80}))
        self.assertEqual(ls.hardware_plan("on", 80, ("temp", 4000, None)),
                         ("control_light_temp", (4000, 80), {}))
        self.assertEqual(ls.hardware_plan("on", 80, ("night", None, None)),
                         ("control_light", ("on", 80, "night"), {}))

    def test_automation_color_maps_to_style(self):
        self.assertEqual(ls.from_color_param(None), ("white", None, None))
        self.assertEqual(ls.from_color_param("cyan"), ("rgb", None, (0, 180, 255)))
        self.assertEqual(ls.from_color_param("rgb", 9, 8, 7), ("rgb", None, (9, 8, 7)))
        self.assertEqual(ls.from_color_param("rgb", None, None, None), ("white", None, None))


class LightApiTests(unittest.TestCase):
    """POST /api/light 之后，临时库里的 light_mode/light_temp/light_rgb 才是判据。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = SmartHomeDB(str(Path(self.temp.name) / "smart_home.db"))
        self.app = create_app({"serial": {"enabled": True}}, start_hardware=False)
        self.app.testing = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user"] = "test-admin"
        self.hardware = Mock(return_value=(True, "ok"))
        patcher = [patch.object(devices, "db", self.db),
                   patch.object(devices, "_hw_call", self.hardware)]
        for p in patcher:
            p.start()
            self.addCleanup(p.stop)

    def _row(self):
        return self.db.get_current_status()

    def _post(self, payload):
        return self.client.post("/api/light", json=payload,
                               headers={"Origin": "http://localhost"})

    def test_brightness_only_keeps_color_temperature(self):
        self._post({"status": "on", "brightness": 80, "temp": 4000})
        self.assertEqual((self._row()["light_mode"], self._row()["light_temp"]),
                         ("temp", 4000))
        self.hardware.reset_mock()
        self._post({"status": "on", "brightness": 40})
        # 灯带收到的仍是同一条色温命令，只是变暗 —— 旧实现这里下发白光
        self.hardware.assert_called_once_with("control_light_temp", 4000, 40)
        row = self._row()
        self.assertEqual((row["light_mode"], row["light_temp"], row["light_brightness"]),
                         ("temp", 4000, 40))

    def test_brightness_only_keeps_custom_color(self):
        self._post({"status": "on", "brightness": 50, "rgb": [255, 128, 0]})
        self.assertEqual(self._row()["light_rgb"], [255, 128, 0])
        self.hardware.reset_mock()
        self._post({"status": "on", "brightness": 20})
        self.hardware.assert_called_once_with("control_light_color", "rgb", 255, 128, 0,
                                              brightness_pct=20)

    def test_status_endpoint_reports_rgb_as_list(self):
        """库里 light_rgb 是 "r,g,b" 文本，公开契约必须是三元列表。

        浏览器验证时把文本直接回传，页面恢复亮法时字符串没有 .map 就静默炸掉，
        色温和取色器都不回显 —— 存储格式不能漏到 API 边界外。
        """
        self._post({"status": "on", "brightness": 40, "rgb": [255, 0, 128]})
        with patch.object(status, "db", self.db):
            payload = self.client.get("/api/status",
                                      headers={"Origin": "http://localhost"}).get_json()
        self.assertEqual((payload["light_mode"], payload["light_rgb"],
                          payload["light_brightness"]), ("rgb", [255, 0, 128], 40))

    def test_style_switches_are_bidirectional(self):
        self._post({"status": "on", "brightness": 60, "temp": 3000})
        self._post({"status": "on", "brightness": 60, "rgb": [0, 200, 120]})
        row = self._row()
        self.assertEqual((row["light_mode"], row["light_temp"], row["light_rgb"]),
                         ("rgb", None, [0, 200, 120]))
        self._post({"status": "on", "brightness": 60, "mode": "night"})
        row = self._row()
        self.assertEqual((row["light_mode"], row["light_temp"], row["light_rgb"]),
                         ("night", None, None))
        self._post({"status": "on", "brightness": 60, "mode": "white"})
        row = self._row()
        self.assertEqual((row["light_mode"], row["light_temp"], row["light_rgb"]),
                         ("white", None, None))

    def test_off_keeps_style_and_on_returns_to_it(self):
        self._post({"status": "on", "brightness": 70, "temp": 5000})
        self._post({"status": "off", "brightness": 0})
        row = self._row()
        self.assertEqual((row["light_status"], row["light_brightness"], row["light_mode"]),
                         ("off", 0, "temp"))
        self.hardware.reset_mock()
        self._post({"status": "on", "brightness": 70})
        self.hardware.assert_called_once_with("control_light_temp", 5000, 70)

    def test_on_with_zero_brightness_is_off_not_full_white(self):
        response = self._post({"status": "on", "brightness": 0, "mode": "white"})
        self.assertEqual(response.status_code, 200)
        row = self._row()
        self.assertEqual((row["light_status"], row["light_brightness"]), ("off", 0))
        self.hardware.assert_called_once_with("control_light", "off", 0)

    def test_get_reports_status_and_style(self):
        self._post({"status": "on", "brightness": 30, "rgb": [10, 20, 30]})
        payload = self.client.get("/api/light",
                                  headers={"Origin": "http://localhost"}).get_json()
        self.assertEqual(payload, {"light_status": "on", "light_brightness": 30,
                                   "light_mode": "rgb", "light_temp": None,
                                   "light_rgb": [10, 20, 30]})

    def test_voice_tool_report_is_bookkept_with_style(self):
        """语音经 /api/hardware/tool 执行成功后，面板记账要带上同一个亮法。"""
        report = devices._tool_state_report(
            "light", {"action": "temp", "temp": 2700, "value": 200})
        code, body = devices._bookkeep(report, "语音")
        self.assertEqual(code, 200)
        row = self._row()
        self.assertEqual((row["light_mode"], row["light_temp"], row["light_brightness"]),
                         ("temp", 2700, 78))
        self.assertEqual(body["light_mode"], "temp")
        # 关灯记账不动亮法：库里保持语音刚设的色温
        devices._bookkeep({"device": "light", "status": "off"}, "语音")
        row = self._row()
        self.assertEqual((row["light_status"], row["light_mode"], row["light_temp"]),
                         ("off", "temp", 2700))


class AutomationStyleTests(unittest.TestCase):
    """规则改灯后库里记的亮法必须跟着变，否则面板显示的还是上一次的颜色。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = Mock()
        self.bridge.control_light.return_value = (True, "ok")
        self.bridge.control_light_color.return_value = (True, "ok")
        self.status = {"light_status": "off", "light_brightness": 0}
        self.db = Mock()
        self.db.get_current_status.side_effect = lambda: dict(self.status)
        self.db.update_status.side_effect = lambda **kw: self.status.update(kw)
        from web.automation.engine import AutomationEngine
        self.engine = AutomationEngine(self.bridge, self.db,
                                       Path(self.temp.name) / "rules.json")

    def _perform(self, **action):
        action.setdefault("device", "light")
        ok, message = self.engine._perform(action, {"id": "t", "name": "测试"})
        self.assertTrue(ok, message)

    def test_rule_color_is_recorded_as_style(self):
        self._perform(status="on", brightness=60, color="red")
        self.assertEqual((self.status["light_mode"], self.status["light_status"],
                          self.status["light_rgb"]), ("rgb", "on", "255,0,0"))

    def test_rule_without_color_is_white(self):
        self.status.update(light_mode="rgb", light_rgb="255,0,0")
        self._perform(status="on", brightness=60)
        self.assertEqual(self.status["light_mode"], "white")
        self.assertIsNone(self.status["light_rgb"])

    def test_rule_off_keeps_previous_style(self):
        self.status.update(light_mode="temp", light_temp=4000)
        self._perform(status="off", brightness=0)
        self.assertEqual((self.status["light_status"], self.status["light_mode"],
                          self.status["light_temp"]), ("off", "temp", 4000))


if __name__ == "__main__":
    unittest.main()
