"""MCP 硬件桥：web 服务经 MCP 子进程独占访问 A/B 板串口。

串口单进程约束：web 服务本身绝不能直接打开 COM 口，否则会与 mcp_home_server
抢串口。本桥在独立线程的 asyncio 循环里以 stdio MCP client 身份拉起
``mcp_home_server.py``（与 voice_assistant 完全相同的方式）：

    Flask 路由 ──(线程安全 future)──▶ 本桥 ──MCP stdio──▶ mcp_home_server
                                                       ├─ Module B 执行器
                                                       └─ Module A 传感器快照

后台每 sensor_poll_interval 秒调用一次 get_sensor_status，把 A 板新快照写入
SQLite（Web 仪表盘看到的温湿度/门灯状态全部来自真实硬件，而非按钮点击）。
MCP 子进程退出时自动指数退避重连。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request

from .config import MCP_SERVER_PATH, PC_TEST_DIR

logger = logging.getLogger(__name__)


class McpHardwareBridge:
    def __init__(self, cfg: dict, db):
        self.db = db
        serial_cfg = cfg.get("serial", {})
        self.enabled = bool(serial_cfg.get("enabled", True))
        self.port_a = serial_cfg.get("port_a") or "auto"
        self.port_b = serial_cfg.get("port_b") or "auto"
        self.poll_interval = float(cfg.get("sensor_poll_interval", 2.0))
        # 串口归语音助手时（如 start_all 联动启动），硬件调用经其 POST /tool 转发。
        # 环境变量 SMART_HOME_HW_RELAY 优先，其次 web_config.yaml: door.relay_url。
        relay = (os.environ.get("SMART_HOME_HW_RELAY")
                 or cfg.get("door", {}).get("relay_url") or "")
        self.relay_url = str(relay).rstrip("/")

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._session = None
        self._call_lock: asyncio.Lock | None = None
        self._snapshot_lock = threading.Lock()
        self._online = False
        self._last_error = ""
        self._last_sensor_ts = None
        self._seen_events: set[str] = set()

    # ==================== 生命周期 ====================

    @property
    def online(self) -> bool:
        with self._snapshot_lock:
            return self._online

    @property
    def last_error(self) -> str:
        with self._snapshot_lock:
            return self._last_error

    def start(self) -> None:
        if not self.enabled:
            if self.relay_url:
                # 串口归语音进程（Docker 联动/start_all 模式）：不拉 MCP 子进程，
                # 改由独立线程经 relay HTTP 周期拉取 A 板快照并入库 + 转发控制。
                self._thread = threading.Thread(target=self._relay_poll_loop,
                                                name="hw-relay-poll", daemon=True)
                self._thread.start()
                logger.info("[硬件桥] relay 轮询模式: %s（每 %.0fs）",
                            self.relay_url, self.poll_interval)
            else:
                logger.info("[硬件桥] serial.enabled=false，不拉 MCP 子进程（看板模式）")
            return
        self._thread = threading.Thread(target=self._thread_main,
                                        name="mcp-hardware-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping = True
        if self._loop is not None and self._task is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)
        if self._thread is not None:
            self._thread.join(timeout=6)

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._supervise())
        except asyncio.CancelledError:
            pass
        finally:
            self._loop.close()

    async def _supervise(self) -> None:
        """维护 MCP stdio 连接；断开/串口被占用时退避重连。"""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        args = [str(MCP_SERVER_PATH)]
        if self.port_a and self.port_a != "auto":
            args += ["--port-a", self.port_a]
        if self.port_b and self.port_b != "auto":
            args += ["--port-b", self.port_b]

        backoff = 1.0
        while not self._stopping:
            params = StdioServerParameters(
                command=sys.executable, args=args, cwd=str(PC_TEST_DIR))
            try:
                logger.info("[硬件桥] 启动 MCP 子进程: %s %s", sys.executable,
                            " ".join(args))
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self._set_online(True)
                        self._call_lock = asyncio.Lock()
                        self._session = session
                        backoff = 1.0
                        tools = await session.list_tools()
                        logger.info("[硬件桥] MCP 已连接，工具: %s",
                                    [t.name for t in tools.tools])
                        await self._poll_loop(session)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._last_error = str(e)
                logger.warning("[硬件桥] MCP 连接断开: %s（%.0fs 后重连）",
                               e, backoff)
            finally:
                self._set_online(False)
                self._session = None
            # 串口可能正被语音模式占用，等待后重试
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def _set_online(self, value: bool, error: str = "") -> None:
        with self._snapshot_lock:
            self._online = value
            self._last_error = error

    # ==================== 传感器轮询入库 ====================

    async def _poll_loop(self, session) -> None:
        while not self._stopping:
            await asyncio.sleep(self.poll_interval)
            try:
                text = await self._call(session, "get_sensor_status", {})
            except Exception as e:
                logger.debug("[硬件桥] 轮询失败: %s", e)
                continue
            if not text or text.startswith("error") or text.startswith("当前无传感器"):
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            self._ingest_snapshot(payload.get("data") or {})
            for event in payload.get("recent_events", []):
                self._ingest_event(event)

    def _relay_poll_loop(self) -> None:
        """relay 模式：串口在语音进程，本线程只做 HTTP 周期轮询 + 入库。

        控制指令走 call_tool → _relay_call（Flask 请求线程同步调用），
        本线程负责把 A 板传感器快照/事件持续写进 SQLite，供仪表盘展示。
        """
        while not self._stopping:
            ok, text = self._relay_call("get_sensor_status", {}, timeout=15)
            if ok:
                self._set_online(True)
                try:
                    payload = json.loads(text)
                    self._ingest_snapshot(payload.get("data") or {})
                    for event in payload.get("recent_events", []):
                        self._ingest_event(event)
                except json.JSONDecodeError:
                    pass
            else:
                self._set_online(False, text)
            # 可中断的间隔睡眠（stop() 时最多 0.2s 退出）
            waited = 0.0
            while not self._stopping and waited < self.poll_interval:
                time.sleep(0.2)
                waited += 0.2

    def _ingest_snapshot(self, snap: dict) -> None:
        ts = snap.get("timestamp")
        if ts is None or ts == self._last_sensor_ts:
            return
        data = {k: v for k, v in snap.items() if k != "timestamp"}
        try:
            self.db.ingest_sensor(
                {"module": "sensor", "type": "data",
                 "timestamp": ts, "data": data})
            self._last_sensor_ts = ts
        except Exception as e:
            # NaN/越界等脏数据：忽略本帧，不能杀死轮询循环
            logger.debug("[硬件桥] 传感器数据入库失败: %s", e)

    def _ingest_event(self, event: dict) -> None:
        key = json.dumps(event, sort_keys=True, ensure_ascii=False)
        if key in self._seen_events:
            return
        self._seen_events.add(key)
        if len(self._seen_events) > 30:
            self._seen_events.pop()
        try:
            name = event.get("event", "unknown")
            self.db.add_hardware_event(
                {"module": "sensor", "type": "event", "event": name,
                 **{k: v for k, v in event.items() if k != "event"}})
        except Exception as e:
            logger.debug("[硬件桥] 事件入库失败: %s", e)

    # ==================== 同步调用 API（供 Flask 路由） ====================

    async def _call(self, session, name: str, args: dict) -> str:
        async with self._call_lock:
            result = await session.call_tool(name, args or {})
        text = ""
        for chunk in (result.content or []):
            part = getattr(chunk, "text", None)
            if part is None and isinstance(chunk, dict):
                part = chunk.get("text")
            if part:
                text += part
        return text or "(工具无文本输出)"

    def call_tool(self, name: str, args: dict | None = None,
                  timeout: float = 10.0) -> tuple[bool, str]:
        """线程安全地调用 MCP 工具，返回 (是否成功, 结果文本)。

        本桥在线时直接走自有 MCP 子进程；本桥离线（如 --no-serial 联动模式）
        但配置了 relay_url 时，转发给语音助手的 POST /tool 静默执行。
        """
        if not self.online or self._session is None or self._loop is None:
            if self.relay_url:
                return self._relay_call(name, args or {}, timeout=timeout)
            return False, f"硬件服务离线（MCP 未连接：{self.last_error or '串口未连接'}）"
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._call(self._session, name, args or {}), self._loop)
            text = future.result(timeout=timeout)
        except Exception as e:
            return False, f"硬件调用失败: {e}"
        if text.startswith("error"):
            return False, text
        return True, text

    def _relay_call(self, name: str, args: dict, timeout: float = 10.0) -> tuple[bool, str]:
        """经语音助手 POST /tool 转发硬件调用（串口归语音进程时的联动通道）。"""
        url = f"{self.relay_url}/tool"
        payload = json.dumps({"name": name, "arguments": args}).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
                return False, body.get("error") or body.get("result") or f"relay HTTP {e.code}"
            except Exception:
                return False, f"硬件联动失败: relay HTTP {e.code}"
        except Exception as e:
            return False, f"硬件联动失败（语音助手不可达 {self.relay_url}）: {e}"
        if body.get("ok"):
            return True, str(body.get("result") or "ok")
        return False, str(body.get("error") or body.get("result") or "硬件联动被拒绝")

    # ── 设备语义映射：Web 百分比/状态 → B 板 MCP 工具参数 ──

    def control_door(self, status: str) -> tuple[bool, str]:
        action = "open" if status == "open" else "close"
        return self.call_tool("door", {"action": action})

    def control_window(self, status: str) -> tuple[bool, str]:
        action = "open" if status == "open" else "close"
        return self.call_tool("window", {"action": action})

    def control_light(self, status: str, brightness_pct: int) -> tuple[bool, str]:
        if status == "off" or brightness_pct <= 0:
            return self.call_tool("light", {"action": "off"})
        value = max(1, min(255, round(brightness_pct * 255 / 100)))
        return self.call_tool("light", {"action": "white", "value": value})

    def control_fan(self, speed_pct: int) -> tuple[bool, str]:
        if speed_pct <= 0:
            return self.call_tool("fan", {"action": "off"})
        value = max(1, min(255, round(speed_pct * 255 / 100)))
        return self.call_tool("fan", {"action": "set_speed", "value": value})
