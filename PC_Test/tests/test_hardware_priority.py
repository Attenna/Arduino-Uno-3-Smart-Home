# -*- coding: utf-8 -*-
"""硬件桥调用优先级：只读轮询不能被慢执行器命令堵住（issue #146）。"""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from web.hardware import McpHardwareBridge


class FakeSession:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append(name)
        if name == "door":
            self.started.set()
            await self.release.wait()
        return SimpleNamespace(
            content=[SimpleNamespace(text="ok")], isError=False)


class HardwarePriorityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bridge = McpHardwareBridge({"serial": {"enabled": False}}, Mock())
        self.bridge._call_lock = asyncio.Lock()
        self.bridge._read_lock = asyncio.Lock()
        self.session = FakeSession()

    async def test_read_only_poll_bypasses_slow_command_lock(self):
        door = asyncio.create_task(self.bridge._call(self.session, "door", {}))
        await asyncio.wait_for(self.session.started.wait(), 1)
        read = asyncio.create_task(
            self.bridge._call(self.session, "get_sensor_status", {}))
        # 门命令还卡在串口上时，A 板事件轮询必须能先完成。
        self.assertEqual(await asyncio.wait_for(read, 1), "ok")
        self.assertFalse(door.done())
        self.session.release.set()
        self.assertEqual(await asyncio.wait_for(door, 1), "ok")

    async def test_pending_command_skips_distance_poll(self):
        self.bridge.tool_schemas = [{"name": "get_distance"}]
        self.bridge._mark_command_pending(1)
        task = asyncio.create_task(self.bridge._distance_loop(self.session))
        try:
            await asyncio.sleep(0.15)
            self.assertNotIn("get_distance", self.session.calls)
            self.bridge._mark_command_pending(-1)
            await asyncio.sleep(0.7)
            self.assertIn("get_distance", self.session.calls)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def test_pending_counter_is_balanced(self):
        self.assertFalse(self.bridge.command_pending())
        self.bridge._mark_command_pending(1)
        self.assertTrue(self.bridge.command_pending())
        self.bridge._mark_command_pending(-1)
        self.assertFalse(self.bridge.command_pending())
        self.bridge._mark_command_pending(-1)   # 不能变成负数卡死测距
        self.assertFalse(self.bridge.command_pending())

    async def test_call_tool_marks_pending_until_ack(self):
        self.bridge._loop = asyncio.get_running_loop()
        self.bridge._session = self.session
        self.bridge._set_online(True)
        task = asyncio.create_task(
            asyncio.to_thread(self.bridge.control_door, "open"))
        await asyncio.wait_for(self.session.started.wait(), 1)
        self.assertTrue(self.bridge.command_pending())
        self.session.release.set()
        ok, text = await asyncio.wait_for(task, 1)
        self.assertTrue(ok)
        self.assertEqual(text, "ok")
        self.assertFalse(self.bridge.command_pending())


if __name__ == "__main__":
    unittest.main()
