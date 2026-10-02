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
from collections import deque

from .config import MCP_SERVER_PATH, PC_TEST_DIR
from .readback import output_mismatch

logger = logging.getLogger(__name__)

# 钩子通道（见 McpHardwareBridge.add_listener）
HOOK_KINDS = ("snapshot", "event", "ack")
# 收到成功 ACK 即视为「输出板在线」并广播 ack 钩子的执行器工具
ACK_TRACKED_TOOLS = ("door", "window", "light", "fan", "buzzer", "ir", "ac")


def _looks_like_error(text: str) -> bool:
    """判断 MCP 返回文本是否为失败。

    注意：MCP 框架在工具内部抛异常时仍返回 ``isError`` 之外的成功封装，
    文本形如 ``Error executing tool xxx: ...``（大写 E），只判 ``startswith("error")``
    会把它当成功，导致前端显示"已打开"但硬件根本没动。
    """
    t = (text or "").strip()
    if not t:
        return True
    low = t.lower()
    return low.startswith("error") or "b 板响应超时" in low


# ==================== B 板复位 → DB 对账 ====================
# 打开串口会拉低 DTR 复位 Uno；复位/欠压/看门狗之后固件 begin() 把执行器锁回默认
# （门 closed、窗 normal、风扇 0、灯 0、蜂鸣器 off），而 web 的 DB 里只有「上次命令
# 下发值」——两者就此长期脱节。实测：DB 说门开着、硬件回读早已是 closed，且这条
# 陈旧值还会被自动化规则当成事实。检测到复位后用硬件回读把 DB 拉回一致并留审计。
# 只写 DB、不动硬件，改动仅限于「命令值与硬件不一致」的那几个执行器列。
_B_RESET_BOOT_WINDOW_S = 120.0   # 距上次复位小于该秒数 ⇒ 本次启动刚把 B 板复位


def reset_needs_reconcile(prev_instance, prev_count, instance, count,
                          last_reset_ago_s,
                          boot_window_s: float = _B_RESET_BOOT_WINDOW_S) -> bool:
    """判断「B 板是否在上次观测之后复位过」，决定要不要做 DB 对账。

    `reset_count` 是 MCP **进程内**的计数，重启即归零——只看「是否增大」会漏掉
    （实测踩过：上一进程 4、新进程 1，增量为负，复位被整段漏掉）。因此按实例标识判：

    * 本进程首次观测：容器与 MCP 通常一起重启，新 MCP 刚打开过串口（必然 DTR 复位），
      用「距上次复位多久」判断；web 单独重启且 MCP 已跑很久时返回 False，
      由「命令未生效」审计去兜这类不一致；
    * 实例变了：**换了 MCP 进程**，开串口那一刻必然复位过 B 板 → 一定对账；
    * 实例没变：`reset_count` 变大即运行期真复位（欠压 / DTR 抖动 / 看门狗）。
    """
    if instance is None or count is None:
        return False
    if prev_instance is None:
        return last_reset_ago_s is not None and last_reset_ago_s <= boot_window_s
    if instance != prev_instance:
        return True
    return count > prev_count


def readback_status(readback: dict) -> dict:
    """把 rb_* 硬件回读换算成 system_status 的执行器列（缺项不写、不猜）。"""
    out: dict = {}
    for rb_key, column in (("rb_door_status", "door_status"),
                           ("rb_window_status", "window_status"),
                           ("rb_buzzer_status", "buzzer_status")):
        if readback.get(rb_key) is not None:
            out[column] = readback[rb_key]
    if readback.get("rb_fan_speed") is not None:
        out["fan_speed"] = int(readback["rb_fan_speed"])
    if readback.get("rb_light_brightness") is not None:
        level = int(readback["rb_light_brightness"])
        out["light_brightness"] = level
        out["light_status"] = "on" if level > 0 else "off"
    return out


class McpHardwareBridge:
    def __init__(self, cfg: dict, db):
        self.db = db
        serial_cfg = cfg.get("serial", {})
        self.enabled = bool(serial_cfg.get("enabled", True))
        self.port_a = serial_cfg.get("port_a") or "auto"
        self.port_b = serial_cfg.get("port_b") or "auto"
        self.poll_interval = float(cfg.get("sensor_poll_interval", 2.0))
        # B 板硬件回读轮询间隔：与 voice 侧心跳（10s）同频即可——回读值来自心跳
        # 缓存的 state 帧，这里只是搬运，不额外占用串口。
        self.readback_interval = float(cfg.get("readback_interval", 10.0))
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
        # relay（web → voice /tool）通道必须串行：所有命令共用同一条 USB 串口，
        # 并发请求会在 A/B 板侧交错导致 ACK 超时与状态错乱（实测门连点触发雪崩）。
        self._relay_lock = threading.Lock()
        self._online = False
        self._last_error = ""
        self._last_sensor_ts = None
        # 事件去重：MCP 的 get_sensor_status 每轮返回 recent_events 全量（有界 50 条），
        # 这里必须按稳定身份记住「已处理过」的事件。旧实现用容量 30 的 set + pop()
        # （无序淘汰）：50 条全量里总有 ≥20 条被淘汰后又当新事件，导致历史红外/键盘
        # 事件每 2 秒重放一次给自动化引擎（规则反复开关设备）。改为 deque+set 有序
        # 淘汰，容量远大于 MCP 窗口；身份优先用事件自带的 ts/timestamp（MCP 收到时打），
        # 没有时间戳的事件才回退整包 JSON。
        self._seen_event_keys: set[str] = set()
        self._seen_event_order: deque[str] = deque()
        # 首轮 recent_events 只登记不触发：桥重启/重建后 MCP 仍留着最近 50 条
        # 历史事件，不能让这些旧账在重启瞬间把红外/键盘规则重新执行一遍。
        self._events_primed = False
        # 数据钩子（二次开发接缝）：快照 / 事件 / 执行器 ACK 三个通道。
        # 每个通道一个「主订阅者」（属性赋值，extensions 启动时注入自动化引擎）
        # 加任意多个「观察者」（add_listener）——观察者不会被属性赋值顶掉，
        # 第三方模块（对接 HA、写外部数据库、调试记录）可以并行监听同一份数据。
        self._hook_primary: dict[str, object] = {k: None for k in HOOK_KINDS}
        self._hook_extra: dict[str, list] = {k: [] for k in HOOK_KINDS}
        self._hooks_lock = threading.Lock()
        # B 板复位对账：上次见到的 reset_count（None = 本进程还没建基线）
        self._last_b_reset_count: int | None = None
        # 上次见到的 MCP 实例标识：换实例 = 换了 MCP 进程 = B 板刚被复位过
        self._b_health_instance: str | None = None
        # 串口健康度缓存（get_serial_health 的低频快照，供 /api/status 上仪表盘）
        self.serial_health: dict | None = None
        # 「命令成功但状态未变」审计去重：上一轮记过的不一致组合
        self._audited_mismatch: set = set()

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
            self._ingest_events(payload.get("recent_events") or [])

    def _relay_poll_loop(self) -> None:
        """relay 模式：串口在语音进程，本线程只做 HTTP 周期轮询 + 入库。

        控制指令走 call_tool → _relay_call（Flask 请求线程同步调用），
        本线程负责把 A 板传感器快照/事件持续写进 SQLite，供仪表盘展示。
        voice 不可用时按指数退避（2→4→…→30s），避免故障期高频打爆/刷日志。
        """
        fail_streak = 0
        last_readback = 0.0
        while not self._stopping:
            ok, text = self._relay_call("get_sensor_status", {}, timeout=15)
            if ok:
                fail_streak = 0
                self._set_online(True)
                try:
                    payload = json.loads(text)
                    self._ingest_snapshot(payload.get("data") or {})
                    self._ingest_events(payload.get("recent_events") or [])
                except json.JSONDecodeError:
                    pass
                # 硬件回读（低频）：把 B 板实际电平写进 rb_* 列，供面板对比出不一致
                if time.time() - last_readback >= self.readback_interval:
                    last_readback = time.time()
                    self._refresh_serial_health()
                    readback = self.read_output_state()
                    if readback:
                        try:
                            self.db.set_output_readback(readback)
                        except Exception as e:           # noqa: BLE001
                            logger.debug("[硬件桥] 硬件回读写库失败: %s", e)
                        # 回读新鲜：顺手做复位对账 / 「命令成功但状态未变」审计
                        self._after_readback(readback)
            else:
                fail_streak += 1
                self._set_online(False, text)
            # 成功按 poll_interval；连续失败指数退避，封顶 30s（可中断睡眠）
            interval = self._poll_interval(fail_streak, self.poll_interval)
            waited = 0.0
            while not self._stopping and waited < interval:
                time.sleep(0.2)
                waited += 0.2

    @staticmethod
    def _poll_interval(fail_streak: int, base: float) -> float:
        """轮询节拍：成功 base 秒；第 n 次连续失败 base*2^n，封顶 30s。"""
        if fail_streak <= 0:
            return float(base)
        return min(float(base) * (2 ** fail_streak), 30.0)

    def read_output_state(self) -> dict | None:
        """读 B 板「硬件回读」快照，归一化成与命令下发值同构的 rb_* 字段。

        B 板的 state 帧给的是原始电平（fan 0/255、light 0~255、door open/closed），
        这里换算成百分比/文本，才能和 db.fan_speed、light_brightness 直接对比。
        取值失败返回 None，绝不写坏数据。
        """
        ok, text = self.call_tool("get_output_state", {}, timeout=5)
        if not ok:
            return None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        state = payload.get("state") or {}
        if not state:
            return None

        def _pct(raw, full):
            try:
                return max(0, min(100, round(int(raw) * 100 / full)))
            except (TypeError, ValueError):
                return None

        return {
            "rb_fan_speed": _pct(state.get("fan"), 255),
            "rb_light_brightness": _pct(state.get("light"), 255),
            "rb_door_status": state.get("door"),
            "rb_window_status": state.get("window"),
            "rb_buzzer_status": state.get("buzzer"),
        }

    def _after_readback(self, readback: dict) -> None:
        """一次回读节拍的后处理：复位对账 与「命令未生效」审计，二者互斥。

        判定为 B 板复位时原因已明确，走对账（把 DB 拉回硬件）；否则才看是否存在
        「命令 ACK 成功、过了稳定期、硬件回读仍不跟随」的静默失效。
        """
        prev_inst, prev_count, inst, count, ago = self._b_reset_state()
        if reset_needs_reconcile(prev_inst, prev_count, inst, count, ago):
            self._reconcile_after_reset(readback, count,
                                        boot=prev_inst is None or inst != prev_inst)
        else:
            self._audit_unapplied()

    def _refresh_serial_health(self) -> None:
        """低频刷新串口健康度缓存（get_serial_health），供 /api/status 与复位判定。

        取不到就置空：宁可让页面显示「离线」，也不拿旧健康度冒充现状。
        """
        ok, text = self.call_tool("get_serial_health", {}, timeout=5)
        health = None
        if ok:
            try:
                health = json.loads(text)
            except json.JSONDecodeError:
                health = None
        self.serial_health = health if isinstance(health, dict) else None

    def _b_reset_state(self) -> tuple:
        """取 (上次实例, 上次计数, 本次实例, 本次计数, 距上次复位秒数)，并推进基线。

        实例标识来自 MCP（进程级随机串）：换实例 = 换了 MCP 进程 = 换进程那一刻必然
        复位过 B 板。比只看 reset_count 增量可靠（计数是进程内的，重启即归零）。
        """
        health = self.serial_health or {}
        b = health.get("b") or {}
        instance = health.get("instance")
        count, ago = b.get("reset_count"), b.get("last_reset_ago_s")
        prev_instance, prev_count = self._b_health_instance, self._last_b_reset_count
        self._b_health_instance, self._last_b_reset_count = instance, count
        return prev_instance, prev_count, instance, count, ago

    def _audit_unapplied(self) -> None:
        """「命令成功但状态未变」审计（P2 防呆）。

        命令 ACK 成功、且已过稳定期，硬件回读仍与命令值不符——这是真正的静默失效
        （指令被吞、驱动没动），与 B 板复位无关。此时**不改 DB**（保持不一致，看板上
        继续告警），只留一条审计。同一批不一致还在就不重复记，状态变化才记一次。
        """
        try:
            status = self.db.get_current_status()
        except Exception as e:                           # noqa: BLE001
            logger.debug("[硬件桥] 命令未生效审计读状态失败: %s", e)
            return
        mismatch = output_mismatch(status)
        marker = {(m["device"], str(m["commanded"]), str(m["readback"]))
                  for m in mismatch}
        if marker == self._audited_mismatch:
            return
        self._audited_mismatch = marker
        if not mismatch:
            return
        logger.warning("[硬件桥] 命令成功但状态未变：%s", mismatch)
        try:
            self.db.add_automation_log(
                rule_id="cmd_not_applied", rule_name="命令未生效审计", triggered=1,
                conditions_hold=0,
                reason="命令 ACK 成功但硬件回读未跟随（已过稳定期，非 B 板复位）",
                success=0, detail=json.dumps(mismatch, ensure_ascii=False))
        except Exception as e:                           # noqa: BLE001
            logger.debug("[硬件桥] 命令未生效审计写库失败: %s", e)

    def _reconcile_after_reset(self, readback: dict, count=None,
                               boot: bool = False) -> None:
        """B 板复位后用硬件回读把 DB 执行器值拉回一致（只写库、不动硬件）。

        reset_count 由 get_serial_health 给出：MCP 读线程每收到一帧 B 板 ready 即 +1
        （上电、DTR 复位、看门狗都会发）。是否该对账由 reset_needs_reconcile 判定。
        只写真正变化的列，一次复位最多记一条审计，避免刷屏。
        """
        try:
            current = self.db.get_current_status()
        except Exception as e:                           # noqa: BLE001
            logger.debug("[硬件桥] 复位对账读当前状态失败: %s", e)
            return
        changed = {k: v for k, v in readback_status(readback).items()
                   if current.get(k) != v}
        if not changed:
            return
        try:
            self.db.update_status(**changed)
            self.db.add_automation_log(
                rule_id="b_reset", rule_name="B板复位对账", triggered=1,
                conditions_hold=1,
                reason="B 板复位（固件执行器已回默认），按硬件回读同步 DB；"
                       f"reset_count={count}，"
                       + ("本次启动即复位" if boot else "运行期复位"),
                success=1,
                detail=json.dumps({k: {"before": current.get(k), "after": v}
                                   for k, v in changed.items()},
                                  ensure_ascii=False))
        except Exception as e:                           # noqa: BLE001
            logger.debug("[硬件桥] 复位对账写库失败: %s", e)
            return
        logger.warning("[硬件桥] B 板复位对账：%s（reset_count=%s）", changed, count)

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
            return
        self._fire("snapshot", data)

    @staticmethod
    def _event_identity(event: dict) -> str:
        """事件稳定身份：优先 event 名 + 板侧/接收时间戳；无 ts 则整包 JSON。"""
        ts = event.get("ts") or event.get("timestamp")
        if ts:
            return f"{event.get('event', 'unknown')}@{ts}"
        return "raw:" + json.dumps(event, sort_keys=True, ensure_ascii=False)

    def _remember_event(self, key: str, maxlen: int = 256) -> bool:
        """登记事件身份；返回 True=首次见到（应处理），False=重放（丢弃）。"""
        if key in self._seen_event_keys:
            return False
        self._seen_event_keys.add(key)
        self._seen_event_order.append(key)
        while len(self._seen_event_order) > maxlen:
            self._seen_event_keys.discard(self._seen_event_order.popleft())
        return True

    def _ingest_events(self, events: list) -> None:
        """处理一轮 recent_events。

        首轮（桥启动/重连后第一次拿到快照）只登记身份、不入库不触发规则，
        把 MCP 残留的历史事件静默消化；之后到达的才是真正的新事件。
        """
        for event in events or []:
            key = self._event_identity(event)
            if not self._events_primed:
                self._remember_event(key)
                continue
            if not self._remember_event(key):
                continue
            try:
                name = event.get("event", "unknown")
                self.db.add_hardware_event(
                    {"module": "sensor", "type": "event", "event": name,
                     **{k: v for k, v in event.items() if k != "event"}})
            except Exception as e:
                logger.debug("[硬件桥] 事件入库失败: %s", e)
            self._fire("event", event)
        self._events_primed = True

    # ==================== 数据钩子（二次开发接缝） ====================
    #
    # 三个通道：snapshot（A 板原始快照 dict）、event（硬件事件 dict）、
    # ack（执行器成功 ACK，回调签名 fn(tool_name, args)）。
    #
    # 每通道一个主订阅者 + 任意多个观察者：
    #   bridge.event_listener = engine.on_event        # 老写法，仍是主订阅者
    #   bridge.add_listener("event", my_observer)      # 并挂，互不顶掉
    # 观察者异常只写 debug，绝不影响主订阅者与轮询线程。

    @property
    def snapshot_listener(self):
        return self._hook_primary["snapshot"]

    @snapshot_listener.setter
    def snapshot_listener(self, fn) -> None:
        self._hook_primary["snapshot"] = fn

    @property
    def event_listener(self):
        return self._hook_primary["event"]

    @event_listener.setter
    def event_listener(self, fn) -> None:
        self._hook_primary["event"] = fn

    @property
    def command_ack_listener(self):
        return self._hook_primary["ack"]

    @command_ack_listener.setter
    def command_ack_listener(self, fn) -> None:
        self._hook_primary["ack"] = fn

    def add_listener(self, kind: str, fn, *, primary: bool = False) -> bool:
        """挂一个钩子订阅者；同一函数重复注册只生效一次。"""
        if kind not in HOOK_KINDS or not callable(fn):
            return False
        with self._hooks_lock:
            if primary:
                self._hook_primary[kind] = fn
            elif fn not in self._hook_extra[kind]:
                self._hook_extra[kind].append(fn)
        return True

    def remove_listener(self, kind: str, fn) -> bool:
        """撤销订阅（主订阅者与观察者都能撤），返回是否真的撤掉了。"""
        if kind not in HOOK_KINDS:
            return False
        with self._hooks_lock:
            if self._hook_primary[kind] is fn:
                self._hook_primary[kind] = None
                return True
            if fn in self._hook_extra[kind]:
                self._hook_extra[kind].remove(fn)
                return True
        return False

    def _fire(self, kind: str, payload, *rest) -> None:
        with self._hooks_lock:
            primary = self._hook_primary[kind]
            subs = ([primary] if primary else []) + list(self._hook_extra[kind])
        for fn in subs:
            try:
                if rest:
                    fn(payload, *rest)
                else:
                    fn(payload)
            except Exception as e:                       # noqa: BLE001
                logger.debug("[硬件桥] %s 钩子异常: %s", kind, e)

    def _fire_ack(self, name: str, args: dict) -> None:
        """执行器指令成功 ACK：刷新 output_last_seen 并广播 ack 通道。"""
        if name in ACK_TRACKED_TOOLS:
            self._fire("ack", name, args or {})

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
        if _looks_like_error(text):
            return False, text
        # B 板不自报状态：任何执行器工具成功 ACK 都视为输出板在线
        self._fire_ack(name, args or {})
        return True, text

    # ==================== 语音助手联动（面板 → 语音） ====================
    # 语音助手（voice_assistant.py）自带 TriggerHTTPServer：/trigger 免唤醒词直接
    # 进入指令模式，/state 查状态，/say 直接下发文本指令。它的地址就是 relay 地址
    # （两个部署形态都由 SMART_HOME_HW_RELAY 指向语音助手）。

    def voice_request(self, path: str, payload: dict | None = None,
                      timeout: float = 3.0) -> tuple[bool, str]:
        """请求语音助手 HTTP 接口，返回 (是否成功, 文本)。未配置 relay 时明确失败。"""
        if not self.relay_url:
            return False, "未配置语音助手地址（SMART_HOME_HW_RELAY / door.relay_url）"
        url = f"{self.relay_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json",
                     "X-Trigger-Source": "web"},
            method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
                return False, str(body.get("error") or f"语音助手 HTTP {e.code}")
            except Exception:
                return False, f"语音助手 HTTP {e.code}"
        except Exception as e:
            return False, f"语音助手不可达（{self.relay_url}）: {e}"
        if not body.get("ok", True):
            return False, str(body.get("error") or "语音助手拒绝了请求")
        return True, json.dumps(body, ensure_ascii=False)

    def _relay_call(self, name: str, args: dict, timeout: float = 10.0) -> tuple[bool, str]:
        """经语音助手 POST /tool 转发硬件调用（串口归语音进程时的联动通道）。

        全局串行：所有设备共用一条串口，排队等锁（最多 timeout），拿不到锁
        快速失败，避免慢指令（舵机/红外数秒）期间请求在串口上交错雪崩。
        """
        if not self._relay_lock.acquire(timeout=timeout):
            return False, "硬件正忙（上一条指令尚未执行完），请稍后再试"
        try:
            return self._relay_call_locked(name, args, timeout)
        finally:
            self._relay_lock.release()

    def _relay_call_locked(self, name: str, args: dict,
                           timeout: float) -> tuple[bool, str]:
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
        if not body.get("ok"):
            return False, str(body.get("error") or body.get("result") or "硬件联动被拒绝")
        # relay 的 ok 只代表「工具被调用」，B 板超时等失败会写在 result 里
        text = str(body.get("result") or "ok")
        if _looks_like_error(text):
            return False, text
        self._fire_ack(name, args or {})
        return True, text

    # ── 设备语义映射：Web 百分比/状态 → B 板 MCP 工具参数 ──

    def control_door(self, status: str) -> tuple[bool, str]:
        action = "open" if status == "open" else "close"
        return self.call_tool("door", {"action": action})

    def control_window(self, status: str) -> tuple[bool, str]:
        """status: open/close/normal(恢复 45° 半开)。"""
        action = {"open": "open", "close": "close", "normal": "normal"}.get(status, "close")
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

    def control_light_color(self, color: str, r=None, g=None, b=None) -> tuple[bool, str]:
        """灯颜色：MCP 工具名仍是 light（复用 ACK 心跳与 output_online）。

        color: white/red/green/blue/yellow/purple/cyan/rgb；rgb 需 r/g/b(0-255)。
        彩色预设不接受亮度参数（B 板只有 white 用 value）。
        """
        args = {"action": color}
        if color == "rgb":
            if None in (r, g, b):
                return False, "RGB 需要 r/g/b 三个值(0~255)"
            args.update({"r": int(r), "g": int(g), "b": int(b)})
        return self.call_tool("light", args)

    def self_test(self, timeout: float = 8.0) -> tuple[bool, str]:
        """B 板固件自检（V2.9+）：引脚方向与电平/灯带 show 次数/命令成败计数快照。"""
        return self.call_tool("self_test", {}, timeout=timeout)

    def control_ir(self, code=None, address=None, command=None) -> tuple[bool, str]:
        """红外发射（NEC）。给 address+command 或直接给十进制 32 位 code。

        码的拼装由 MCP 侧的 nec_code() 统一完成，这里只负责转发。
        """
        args: dict = {}
        if address is not None and command is not None:
            args.update({"address": int(address), "command": int(command)})
        elif code is not None:
            args["code"] = int(code)
        else:
            return False, "红外发射需要 code，或 address + command"
        return self.call_tool("ir", args)

    def control_ac(self, **kwargs) -> tuple[bool, str]:
        """美的空调（RN02G(X) 红外状态帧）。kwargs 只带要改变的字段，None = 保持不变。

        一次变更最多翻译成几帧（状态帧 + 扫风翻转帧），B 板发射是阻塞的，
        因此超时放宽到 20s。MCP 侧负责帧编码与状态合并，这里只转发。
        """
        args = {k: v for k, v in kwargs.items() if v is not None}
        if not args:
            return False, "空调控制至少需要一个参数"
        return self.call_tool("ac", args, timeout=20.0)
