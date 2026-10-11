"""#106：B 板「每帧只吐约 146 字节就停住」时，只读帧的取回策略。

- 只读帧（自检/测距/状态）超过断流阈值，必须靠"再写一条命令"把余量顶开；
- **不能**再补发 ``system/status``：它自己的回帧内嵌 ``"state":{...}``，与上一帧余量
  交错后会被重组器当成"一帧"抠出来（日志刷屏 ``未知帧: {"door":...}``），真帧永远
  匹配不上 → 自检恒超时 → 连续超时重开串口 → DTR 再复位 B 板一次；
- 改为**原样重发同一条只读命令**顶开（无副作用、不插别的帧）；
- **设备命令必须保持原样**：绝不能重发（会二次驱动执行器），仍走 ``system/status`` 补发。
"""
import json
import unittest

import mcp_home_server as mcp


def _selftest_frame():
    return (b'{"module":"output","type":"selftest","version":"V2.13","uptime_ms":1234,'
            b'"ok":0,"err":0,"fan":{"speed":0,"reclaim":0,"pin":[1,0,1,0]},'
            b'"light":{"level":0,"bright":144,"shows":0,"lit":0,"d4":[1,1,0]},'
            b'"buzzer":"off","ram":{"hw":108,"win":293,"margin":185,"free":144,'
            b'"prv_hw":182,"boot":84}}')


class _ScriptedSerial:
    """假串口：第 N 次 write 后"板子吐出"预先编排好的字节（模拟断流分两段到）。"""

    def __init__(self, emissions):
        self._emissions = list(emissions)
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(data.decode("utf-8", "replace") if isinstance(data, bytes)
                           else str(data))
        if self._emissions:
            self._emissions.pop(0)()
        return len(data)

    def close(self):
        self.closed = True


class ReadonlyFrameStallTests(unittest.TestCase):
    def setUp(self):
        self.home = mcp.HomeController(ser_a=None, ser_b=None,
                                       port_a="/dev/null-a", port_b="/dev/null-b")
        self.home._b_stop.set()          # 测试不需要真读线程抢串口

    def _feed(self, payload: bytes):
        for text in self.home._take_b_frames(payload):
            self.home._dispatch_b_frame(json.loads(text), text)

    def test_readonly_frame_arrives_in_two_segments_without_nudge(self):
        frame = _selftest_frame()
        seg1, seg2 = frame[:150], frame[150:]     # 模拟 ~146B 断流
        home = self.home

        def first_write():
            self._feed(seg1)                       # 只来前半段 → 等不到完整帧

        def second_write():
            self._feed(seg2)                       # 重发的同一条命令把余量顶开

        home.ser_b = _ScriptedSerial([first_write, second_write])
        result = home._send_b({"cmd": "system", "action": "selftest"},
                              expect=("selftest",))

        # 取回完整自检帧
        self.assertTrue(result.startswith("{"), f"未取回自检帧: {result[:120]}")
        payload = json.loads(result)
        self.assertEqual(payload["type"], "selftest")
        self.assertEqual(payload["ram"]["prv_hw"], 182)

        # 判定：重发的是「同一条只读命令」，不是 system/status；且没有触发重开
        writes = home.ser_b.writes
        self.assertEqual(len(writes), 2, f"应只写两次（首次+原样重发）: {writes}")
        self.assertIn('"action": "selftest"', writes[0])
        self.assertIn('"action": "selftest"', writes[1])
        self.assertNotIn("status", writes[1])
        self.assertEqual(home._b_reopen_count, 0)
        self.assertEqual(home._b_cmd_timeouts, 0)

    def test_device_command_is_never_rewritten(self):
        """设备命令超时只能补发只读的 system/status，绝不能原样重发（会二次驱动执行器）。"""
        home = self.home
        home.ser_b = _ScriptedSerial([])          # 永远不回帧
        result = home._send_b({"cmd": "light", "action": "on", "value": 255},
                              expect=("response",))
        self.assertTrue(result.startswith("error"), result)
        writes = home.ser_b.writes
        light_writes = [w for w in writes if '"cmd": "light"' in w]
        self.assertEqual(len(light_writes), 1, f"设备命令被重发: {writes}")
        self.assertTrue(any("status" in w for w in writes),
                        f"设备命令应仍走 system/status 补发: {writes}")

    def test_readonly_timeout_is_not_counted_toward_reopen(self):
        """只读超时不得推进「连续超时→重开」：重开会经 DTR 复位 B 板，复位期间下发必丢，
        会把一次只读失败滚成自重开循环（实测 1 分钟内 boot 145→152）。"""
        home = self.home
        home.ser_b = _ScriptedSerial([])          # 永远不回帧
        home._b_cmd_timeouts = mcp._B_CMD_FAILS_TO_REOPEN - 1
        before = home._b_cmd_timeouts

        result = home._send_b({"cmd": "system", "action": "selftest"},
                              expect=("selftest",))

        self.assertTrue(result.startswith("error"), result)
        self.assertEqual(home._b_cmd_timeouts, before,
                         "只读超时推进了重开门限")
        self.assertEqual(home._b_reopen_count, 0, "只读超时触发了重开")


if __name__ == "__main__":
    unittest.main()