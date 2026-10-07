"""mcp_home_server.py — 智能家居 MCP server（stdio）

独占持有 Module A（传感器）/Module B（执行器）两块 Arduino 串口，
通过标准 MCP 协议向大模型暴露控制/查询工具：
    light / door / window / fan / buzzer / oled / display / ir / ac / get_sensor_status
    get_distance / get_serial_health / get_output_state / self_test

数据流：
    LLM(voice_assistant) ──MCP stdio──▶ 本 server ──JSON 命令──▶ Module B (USB)
                                         ├─ light 命令 ───────▶ Module A (USB)
                                         └─ A 板读线程缓存最新传感器状态

启动：
    py -3.13 mcp_home_server.py                       # 自动探测串口
    py -3.13 mcp_home_server.py --port-a COM7 --port-b COM6
    py -3.13 mcp_home_server.py --no-serial            # 不连串口（仅暴露工具 schema）

⚠️ 因 stdout 是 MCP stdio 传输通道，所有日志一律走 stderr。
"""
import argparse
import asyncio
import json
import sys
import threading
import time
import uuid
from collections import deque
from typing import Literal, Optional

import serial
import serial.tools.list_ports

import midea_ac

BAUD = 115200

# ---- 矩阵键盘开门密码（正式版硬件：仅 "1" 键，密码 1111 = 连按 4 次）----
KEYPAD_CODE = "1111"          # 开门密码
KEYPAD_WINDOW_S = 10.0        # 全部按键必须在该时间窗口内完成，超时清空


# ==================== 串口探测 / 连接（早期串口工具移植而来）====================

def list_ports():
    return [(p.device, p.description) for p in serial.tools.list_ports.comports()]


def connect(port: str, label: str):
    try:
        ser = serial.Serial(port, BAUD, timeout=1)
        time.sleep(0.2)
        ser.reset_input_buffer()
        print(f"[{label}] 已连接 {port} @ {BAUD}", file=sys.stderr)
        return ser
    except Exception as e:
        print(f"[{label}] 连接 {port} 失败: {e}", file=sys.stderr)
        return None


def detect_board(expect_substr: str, label: str) -> Optional[str]:
    """在所有串口上发 WHO 探测，返回命中的端口名。"""
    for dev, desc in list_ports():
        print(f"[探测] 尝试 {dev} ({desc})...", end="", file=sys.stderr, flush=True)
        try:
            ser = serial.Serial(dev, BAUD, timeout=0.3)
            time.sleep(0.1)
            ser.reset_input_buffer()
            ser.write(b'{"cmd":"system","action":"who"}\n')  # B 板
            ser.write(b"WHO\n")                                # A 板
            deadline = time.time() + 0.6
            found = False
            while time.time() < deadline:
                line = ser.readline().decode("utf-8", "replace")
                if expect_substr in line:
                    found = True
                    break
            ser.close()
            print(" 命中!" if found else " 无响应", file=sys.stderr)
            if found:
                return dev
        except Exception as e:
            print(f" 跳过 ({e})", file=sys.stderr)
    return None


# ==================== 红外发射（NEC 码换算）====================

def nec_code(address: int, command: int) -> int:
    """按 Module B 的红外发送约定拼 32 位码（bit31 先发，不是 LSB-first）。

    B 板 IR.cpp 是最低位在最后、最高位先发，因此**不能**直接填 IRremote 那套
    常见的 LSB-first 值（如 0xBA45FF00）。要让它解出 address/command，必须按
    NEC 帧序摆放：addr、~addr、cmd、~cmd 各占一个字节。

    例：nec_code(0x00, 0x45) -> 0x00FF45BA -> 16729530
    （对应 A 板遥控器「1」键 address=0x00 / command=0x45）
    """
    a = address & 0xFF
    c = command & 0xFF
    return ((a << 24) | ((~a & 0xFF) << 16) | (c << 8) | (~c & 0xFF)) & 0xFFFFFFFF


# ==================== 智能家居控制器（持有串口）====================

# A 板读线程自愈参数
_A_REOPEN_BASE_DELAY = 1.0     # 首次重连等待（秒），之后指数退避
_A_REOPEN_MAX_DELAY = 10.0
_A_ERR_SUMMARY_INTERVAL = 30.0  # 持续故障时摘要日志最小间隔（秒）

# B 板：命令响应超时 / 空闲心跳 / 连续失败多少次才重开
_B_CMD_TIMEOUT = 2.0            # 单条命令等响应的上限（0.8s 对舵机/红外/OLED 混跑太紧）
_B_HEARTBEAT_S = 10.0
_B_HB_FAILS_TO_REOPEN = 3       # 单次抖动不重开：重开会经 DTR 复位 B 板
_B_CMD_FAILS_TO_REOPEN = 3      # 命令连续超时这么多次才重开（理由同上，见 _send_b）


class HomeController:
    """独占 A/B 串口；A 板后台读线程缓存状态；B 板同步发命令。"""

    def __init__(self, ser_a=None, ser_b=None, port_a: Optional[str] = None,
                 port_b: Optional[str] = None):
        # 进程实例标识/启动时刻：随 get_serial_health 上报。上游（web 的复位对账）
        # 靠它判断「MCP 换进程了」——换进程那一刻开串口必然复位 B 板，而 reset_count
        # 是进程内计数、重启归零，只看增量会漏判。
        self._instance = uuid.uuid4().hex[:8]
        self._started_ts = time.time()
        self.ser_a = ser_a
        # port_a 仅 A 板读线程重连用（必须是 by-id 等稳定路径）
        self.port_a = port_a
        self.ser_b = ser_b
        # port_b 记下稳定路径，句柄损坏后仍能重开（原先只能从当前句柄取端口名，
        # 句柄一旦被清成 None 就再也开不回来）
        self.port_b = port_b or (getattr(ser_b, "port", None)
                                 if ser_b is not None else None)
        self._b_lock = threading.Lock()
        self._snapshot_lock = threading.Lock()
        self._snapshot: dict = {}
        self._events: deque = deque(maxlen=50)
        self._ready: dict = {}
        self._ac_lock = threading.Lock()
        self._ac = midea_ac.AcState()  # 美的空调当前状态（本进程内维护）
        self._a_thread: Optional[threading.Thread] = None
        self._a_stop = threading.Event()
        # A 板故障状态（仅读线程访问，无需加锁）
        self._a_err_count = 0
        self._a_err_first_ts = 0.0
        self._a_err_last_log = 0.0
        self._a_reopen_delay = _A_REOPEN_BASE_DELAY
        # A 板同时负责传感器上报与灯带命令。读取仍由唯一后台线程完成；命令发送方
        # 只登记 id 并等待该线程分发 response，避免两个读者争抢串口帧。
        self._a_cmd_lock = threading.Lock()
        self._a_resp_lock = threading.Lock()
        self._a_resp_event = threading.Event()
        self._a_resp: Optional[dict] = None
        self._a_waiter_id = -1
        self._a_next_id = 0

        # ── B 板：常驻读取线程 + 等待者表（与 A 板同构）──
        # B 板串口也必须**只有一个读者**。原先"发一条等一条"内联读，没有命令时
        # B 板的主动上报（复位横幅 ready / 引脚自愈 alert / state）无人消费，会被
        # 清缓冲静默丢掉。现在读写彻底分开：
        #   写：_send_b 持 _b_lock → 登记等待者 → 写 → 等事件（超时/被唤醒）
        #   读：_read_b_loop 常驻消费，按 type 分类，命中等待者就唤醒
        self._b_thread: Optional[threading.Thread] = None
        self._b_maint_thread: Optional[threading.Thread] = None
        self._b_stop = threading.Event()
        self._b_resp_lock = threading.Lock()
        self._b_resp_event = threading.Event()
        self._b_resp: Optional[dict] = None
        self._b_expect: tuple = ()
        self._b_waiter = False
        self._b_waiter_id = -1
        self._b_next_id = 0
        self._b_last_frame_ts = 0.0
        self._b_last_cmd_ts = 0.0
        self._b_hb_fails = 0
        self._b_cmd_timeouts = 0       # 连续命令超时计数（达门限才重开，成功后清零）
        # B 板故障状态（仅读线程访问）
        self._b_err_count = 0
        self._b_err_first_ts = 0.0
        self._b_err_last_log = 0.0
        # 串口健康度（供 get_serial_health）
        self._b_reopen_count = 0
        self._b_reset_count = 0        # 收到的 ready 帧数 = B 板复位/重启次数
        self._b_last_reset_ts = 0.0
        self._b_alert_count = 0
        self._b_last_alert = ""
        self._b_last_alert_ts = 0.0
        self._b_last_state: dict = {}
        self._b_last_state_ts = 0.0
        # 最近一条下发命令的完整反馈（命令/参数/成败/耗时/固件回读状态），
        # 供 get_serial_health 暴露给中间层日志与排障。
        self._b_last_cmd: dict = {}

        if self.ser_a is not None:
            self._a_thread = threading.Thread(
                target=self._read_a_loop, daemon=True, name="module-a-reader")
            self._a_thread.start()
        if self.ser_b is not None:
            self._b_thread = threading.Thread(
                target=self._read_b_loop, daemon=True, name="module-b-reader")
            self._b_thread.start()
            self._b_maint_thread = threading.Thread(
                target=self._b_maintenance_loop, daemon=True,
                name="module-b-maintenance")
            self._b_maint_thread.start()

    # ── A 板读取线程 ──
    def _note_a_ok(self) -> None:
        """读到字节：若此前处于故障态，打印一条恢复摘要并复位计数/退避。"""
        if self._a_err_count:
            dur = time.time() - self._a_err_first_ts
            print(f"[A] 读取恢复正常（此前连续 {self._a_err_count} 次异常，"
                  f"持续 {dur:.0f}s）", file=sys.stderr, flush=True)
        self._a_err_count = 0
        self._a_err_first_ts = 0.0
        self._a_err_last_log = 0.0
        self._a_reopen_delay = _A_REOPEN_BASE_DELAY

    def _note_a_error(self, e: Exception) -> None:
        """记录一次读异常：首条立即打印，持续故障期限频打印摘要，避免刷屏掩盖问题。"""
        now = time.time()
        if self._a_err_count == 0:
            self._a_err_count = 1
            self._a_err_first_ts = now
            self._a_err_last_log = now
            print(f"[A] 读线程异常: {e}", file=sys.stderr, flush=True)
        else:
            self._a_err_count += 1
            if now - self._a_err_last_log >= _A_ERR_SUMMARY_INTERVAL:
                self._a_err_last_log = now
                dur = now - self._a_err_first_ts
                print(f"[A] 读异常持续中：近 {self._a_err_count} 次 / {dur:.0f}s，"
                      f"最近错误: {type(e).__name__}: {str(e)[:80]}",
                      file=sys.stderr, flush=True)

    def _reopen_a(self) -> bool:
        """A 板串口进入坏状态后，按指数退避关闭旧句柄并重开 port_a（by-id）。

        CDC-ACM 瞬断/USB 重枚举后旧 fd 永久不可用，继续 readline 只会无限刷异常；
        重开 by-id 节点可在设备重新枚举后自动恢复，无需重启容器。
        """
        old = self.ser_a
        try:
            if old is not None:
                old.close()
        except Exception:
            pass
        self.ser_a = None
        if not self.port_a:
            # auto/无路径模式无法定位设备，等待上层下一轮（限频日志仍会出摘要）
            self._a_stop.wait(_A_REOPEN_MAX_DELAY)
            return False
        while not self._a_stop.is_set():
            delay = self._a_reopen_delay
            self._a_reopen_delay = min(delay * 2, _A_REOPEN_MAX_DELAY)
            if self._a_stop.wait(delay):
                return False
            try:
                ser = serial.Serial(self.port_a, BAUD, timeout=1)
                time.sleep(0.2)
                ser.reset_input_buffer()
                self.ser_a = ser
                self._a_reopen_delay = _A_REOPEN_BASE_DELAY
                print(f"[A] 串口重连成功 {self.port_a} @ {BAUD}",
                      file=sys.stderr, flush=True)
                return True
            except Exception as e:
                print(f"[A] 重连失败（{self.port_a}）：{type(e).__name__}: "
                      f"{str(e)[:80]}；{self._a_reopen_delay:.0f}s 后重试",
                      file=sys.stderr, flush=True)
        return False

    def _read_a_loop(self):
        while not self._a_stop.is_set():
            try:
                raw = self.ser_a.readline()
                if not raw:
                    continue  # timeout=1 的正常空读
                self._note_a_ok()
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mtype = msg.get("type")
                if mtype == "ready":
                    with self._snapshot_lock:
                        self._ready = msg
                elif mtype == "data":
                    with self._snapshot_lock:
                        self._snapshot = msg.get("data", {})
                        self._snapshot["timestamp"] = msg.get("timestamp")
                elif mtype == "event":
                    ev_name = msg.get("event")
                    with self._snapshot_lock:
                        self._events.append({
                            "event": ev_name,
                            **{k: v for k, v in msg.items()
                               if k not in ("module", "type")},
                            # A 板事件本身不带时间戳：同一按键连按时 JSON 完全相同，
                            # web 侧按整包去重会把第二次以后全丢掉（遥控器连按失效）。
                            # 这里在「到达时刻」打一次标记：同一物理事件跨轮询保持不变
                            # （仍能去重），不同次按键则因时间戳不同而各自触发。
                            "ts": int(time.time() * 1000),
                        })
                    if ev_name == "keypad":
                        self._handle_keypad(msg.get("key", ""))
                elif mtype == "response":
                    with self._a_resp_lock:
                        if msg.get("id") == self._a_waiter_id:
                            self._a_resp = msg
                            self._a_resp_event.set()
                # who 忽略
            except (serial.SerialException, OSError) as e:
                # 设备级错误（USB 断连/重枚举/多访问者）：关闭旧句柄并退避重开
                self._note_a_error(e)
                self._reopen_a()
            except Exception as e:
                # 其他未知异常：限频记录并轻度等待，避免紧密空转
                self._note_a_error(e)
                time.sleep(0.5)

    # ── 矩阵键盘：密码聚合开门 ──
    def _handle_keypad(self, key: str):
        from keypad_code import KeypadCode
        with self._snapshot_lock:
            if not hasattr(self, "_keypad_code"):
                self._keypad_code = KeypadCode(KEYPAD_CODE, KEYPAD_WINDOW_S)
            result = self._keypad_code.feed(key)
            if result is not None:
                result["timestamp"] = time.time_ns()
                self._events.append(result)
        if result and result["status"] == "granted":
            # Only the web automation engine owns door commands and its close timer.
            self._report_granted_event()

    def _report_granted_event(self):
        """键盘密码开门上报为「门禁通过」事件，供 web 全屋模式判定进门。

        复用 A 板 event 通道（recent_events），web 侧 _ingest_event →
        automation.on_event({"event":"access","status":"granted","method":"keypad"})
        → 积木规则（预设 access_open_door / access_auto_close）开门并延时关门。
        全屋模式状态机已拆除，进门后的「切自动」也由规则读写 g:全屋模式 完成。
        """
        with self._snapshot_lock:
            self._events.append({
                "event": "face", "status": "granted",
                "person": "键盘密码",
                "method": "keypad",
                "face_id": "keypad",
                "timestamp": int(time.time() * 1000),
            })

    # ── B 板发命令 + 收响应 ──
    def _send_a(self, cmd: dict) -> str:
        """向 Module A 下发灯带命令，并等待 A 读线程按请求 id 交付响应。"""
        if self.ser_a is None:
            return "error: Module A 未连接，无法执行灯光操作"
        with self._a_cmd_lock:
            self._a_next_id = (self._a_next_id + 1) & 0x7FFFFFFF
            request_id = self._a_next_id
            packet = dict(cmd, id=request_id)
            with self._a_resp_lock:
                self._a_waiter_id = request_id
                self._a_resp = None
                self._a_resp_event.clear()
            try:
                self.ser_a.write((json.dumps(packet, separators=(",", ":")) + "\n").encode())
                self.ser_a.flush()
            except Exception as e:
                return f"error: A 板写入失败: {e}"
            if not self._a_resp_event.wait(_B_CMD_TIMEOUT):
                return "error: A 板响应超时"
            with self._a_resp_lock:
                response = self._a_resp or {}
                self._a_waiter_id = -1
            if response.get("result") != "ok":
                return "error: A 板拒绝灯光命令"
            return "ok"

    def _send_b(self, cmd: dict, allow_reopen: bool = True,
                expect: tuple = ("response",)) -> str:
        """发命令给 Module B；连续多次超时才重开串口自愈。

        响应由常驻读取线程 _read_b_loop 收下并按等待者唤醒，本方法只负责
        「登记等待者 → 写 → 等事件」。

        **单次超时不再重开**：重开会经 DTR 复位 B 板，而复位把固件执行器全打回默认
        （灯灭 / 门关 / 窗回 45°）——一次偶发超时就复位板子，等于让用户看到"设备自己
        变了、点了没用"（实测 11 分钟复位 8 次、重开 4 次，单条命令被拖到 3s）。改为
        连续 _B_CMD_FAILS_TO_REOPEN 次超时才重开，任何一次成功即清零。
        心跳走 allow_reopen=False + expect=("state",)：它有自己的失败门限。
        """
        if self.ser_b is None:
            # 未连接也要留档/打印：静默返回错误会让「点了没反应」查不到任何线索
            result = "error: Module B 未连接，无法执行硬件操作"
            self._note_b_cmd(cmd, result, 0.0)
            return result
        with self._b_lock:
            t0 = time.monotonic()
            result = self._send_b_one(cmd, expect=expect)
            if result.startswith("error: B 板响应超时"):
                self._b_cmd_timeouts += 1
                if allow_reopen and self._b_cmd_timeouts >= _B_CMD_FAILS_TO_REOPEN:
                    self._b_cmd_timeouts = 0
                    print(f"[B] 连续 {_B_CMD_FAILS_TO_REOPEN} 次命令超时，重开串口自愈",
                          file=sys.stderr, flush=True)
                    self._reopen_b()
                    result = self._send_b_one(cmd, expect=expect)   # 重试重新分配 id
            else:
                self._b_cmd_timeouts = 0
            self._note_b_cmd(cmd, result, time.monotonic() - t0)
            return result

    def _note_b_cmd(self, cmd: dict, result: str, elapsed: float) -> None:
        """记录并打印一条命令的完整反馈：**这是「命令成功/失败 + 固件实际状态」的
        唯一收口点**（面板、语音、自动化全部经此下发）。

        固件 V2.9 起成功响应自带 state 快照（见 _dispatch_b_frame 会把它并入
        _b_last_state），因此这里能当场打印「意图 → 固件回读」，不必等心跳。失败
        （超时/未知命令/串口无连接）也原样打印，方便把「网络慢」和「指令被吞」分开。
        """
        name = f"{cmd.get('cmd')}/{cmd.get('action')}"
        ok = result.startswith("ok")
        # 心跳/只读查询（system）与 OLED 轮播逐行刷新不算「设备命令」：前者每 10s、
        # 后者每 ~5s 各来一次，若也记账，「最近命令」会被它们永远顶掉，排查时反而
        # 看不到真正的用户操作（面板/语音/自动化）。
        if cmd.get("cmd") in ("system", "oled", "ultrasonic"):
            return
        self._b_last_cmd = {
            "cmd": cmd.get("cmd"), "action": cmd.get("action"),
            "args": {k: v for k, v in cmd.items()
                     if k not in ("cmd", "action", "id")},
            "ok": ok, "result": result[:200],
            "ms": round(elapsed * 1000, 1), "ts": time.time(),
            "state": dict(self._b_last_state),
        }
        if ok:
            print(f"[B] {name} ok {elapsed * 1000:.0f}ms"
                  f" | 固件回读 {self._b_last_state or '{}'}",
                  file=sys.stderr, flush=True)
        else:
            print(f"[B] {name} 失败 {elapsed * 1000:.0f}ms: {result[:160]}",
                  file=sys.stderr, flush=True)

    def _send_b_one(self, cmd: dict, expect: tuple = ("response",),
                    timeout: float = _B_CMD_TIMEOUT) -> str:
        """给命令分配单调 id、序列化并下发一次（调用方需持有 _b_lock）。

        带 id 是为了让响应可被归属：迟到/串味的响应 id 对不上就直接丢弃，不会被
        当成本次命令的结果（固件 V2.6 起回显 id；旧固件不回显则退化为「只认第一条」）。
        """
        cmd_id = self._b_next_id
        self._b_next_id += 1
        line = json.dumps(dict(cmd, id=cmd_id), ensure_ascii=False) + "\n"
        return self._send_b_once(line, cmd_id, expect=expect, timeout=timeout)

    def _send_b_once(self, line: str, cmd_id: int = -1,
                     expect: tuple = ("response",),
                     timeout: float = _B_CMD_TIMEOUT) -> str:
        """写一条命令并等它的响应帧（调用方需持有 _b_lock）。

        只等 ``expect`` 里列出的帧类型：普通命令等 response，心跳等 state（B 板的
        system/status 回的是 state 帧，不是 response）。响应还要 id 对得上（或对端
        是旧固件、根本不回显 id）才算本次结果，其余一律丢弃并记录。
        """
        if self.ser_b is None:
            return "error: Module B 未连接"
        with self._b_resp_lock:
            self._b_resp = None
            self._b_expect = expect
            self._b_waiter_id = cmd_id
            self._b_waiter = True
            self._b_resp_event.clear()
        try:
            self.ser_b.write(line.encode("utf-8"))
            self._b_last_cmd_ts = time.time()
        except Exception as e:                       # noqa: BLE001
            with self._b_resp_lock:
                self._b_waiter = False
                self._b_expect = ()
                self._b_waiter_id = -1
            return f"error: 串口写入失败 {e}"
        got = self._b_resp_event.wait(timeout)
        with self._b_resp_lock:
            self._b_waiter = False
            self._b_expect = ()
            self._b_waiter_id = -1
            resp = self._b_resp
            self._b_resp = None
        if not got or resp is None:
            return "error: B 板响应超时"
        if resp.get("type") != "response":
            # state 等非 response 帧即代表链路通；自检帧要把内容原样带回上层
            if resp.get("type") in ("selftest", "distance"):
                return json.dumps(resp, ensure_ascii=False)
            return "ok"
        if resp.get("result") == "ok":
            if "distance" in expect:
                return "error: B 板未返回测距数据，请确认固件 V2.10 或以上"
            return "ok"
        return f"error: B 板返回 {resp}"

    # ── B 板常驻读取线程（串口唯一读者）──
    def _note_b_error(self, e: Exception) -> None:
        """B 板读异常限频：首条立即、持续时按窗口打摘要，避免刷屏掩盖问题。"""
        now = time.time()
        if self._b_err_count == 0:
            self._b_err_count = 1
            self._b_err_first_ts = now
            self._b_err_last_log = now
            print(f"[B] 读线程异常: {e}", file=sys.stderr, flush=True)
        else:
            self._b_err_count += 1
            if now - self._b_err_last_log >= _A_ERR_SUMMARY_INTERVAL:
                self._b_err_last_log = now
                print(f"[B] 读异常持续中：近 {self._b_err_count} 次 / "
                      f"{now - self._b_err_first_ts:.0f}s，最近: "
                      f"{type(e).__name__}: {str(e)[:80]}",
                      file=sys.stderr, flush=True)

    def _read_b_loop(self) -> None:
        """B 板唯一读者：把所有上行帧按 type 分类，命中等待者就唤醒。

        不重开串口（重开由 _send_b 超时路径或心跳线程持 _b_lock 执行）；异常限频记录
        后继续读，句柄被重开后自动续上新的 self.ser_b。
        """
        while not self._b_stop.is_set():
            ser = self.ser_b
            if ser is None:
                self._b_stop.wait(0.5)
                continue
            try:
                raw = ser.readline()
            except Exception as e:                   # noqa: BLE001
                # 句柄被重开路径换走了：_send_b（命令响应超时）与心跳线程都会重开 B
                # 口，它们 close 掉旧 fd 后，本线程手里的 ser 就成了死句柄，readline
                # 必然抛——pyserial 内部常给出 "'NoneType' object cannot be
                # interpreted as an integer" 这类牛头不对马嘴的 TypeError。这不是链路
                # 故障（重开是正常自愈，成功日志由 _reopen_b 打），所以不计入异常计数、
                # 不打误导日志，直接换到新句柄继续读。
                if ser is not self.ser_b:
                    self._b_stop.wait(0.2)
                    continue
                self._note_b_error(e)
                self._b_stop.wait(0.5)
                continue
            if not raw:
                continue
            text = raw.decode("utf-8", "replace").strip()
            if not text:
                continue
            if self._b_err_count:
                print(f"[B] 读取恢复正常（此前连续 {self._b_err_count} 次异常）",
                      file=sys.stderr, flush=True)
                self._b_err_count = 0
            self._b_last_frame_ts = time.time()
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                print(f"[B] 非JSON行: {text[:120]}", file=sys.stderr, flush=True)
                continue
            self._dispatch_b_frame(msg, text)

    def _dispatch_b_frame(self, msg: dict, text: str) -> None:
        """按 type 分类一帧：response/state 唤醒等待者，ready/alert 记账并上报。"""
        mtype = msg.get("type")
        if mtype == "response":
            rid = msg.get("id")
            # 固件 V2.9 起成功响应自带执行后的 state 快照：立刻把它并入回读缓存，
            # 这样「命令意图 vs 固件实际」当场可比，不必等下一次心跳（也顺带让
            # 心跳判据看到「刚有新鲜状态」，空闲时才会真正去打心跳探测）。
            st = msg.get("state")
            if isinstance(st, dict) and st:
                self._b_last_state = st
                self._b_last_state_ts = time.time()
            with self._b_resp_lock:
                wid = self._b_waiter_id
                # id 对得上才算本次结果；对端是旧固件、不回显 id(None) 时退化为「只认第一条」
                id_ok = rid is None or rid == wid
                if self._b_waiter and "response" in self._b_expect and id_ok:
                    self._b_resp = msg
                    self._b_resp_event.set()
                    return
            print(f"[B] 丢弃非本次响应（等待者={wid}, 收到 id={rid}）: {text}",
                  file=sys.stderr, flush=True)
        elif mtype == "distance":
            # New firmware always echoes the request id. Reject stale/unowned samples.
            with self._b_resp_lock:
                if (self._b_waiter and "distance" in self._b_expect
                        and msg.get("id") == self._b_waiter_id):
                    self._b_resp = msg
                    self._b_resp_event.set()
        elif mtype == "state":
            self._b_last_state = msg
            self._b_last_state_ts = time.time()
            with self._b_resp_lock:
                if self._b_waiter and "state" in self._b_expect:
                    self._b_resp = msg
                    self._b_resp_event.set()
        elif mtype == "selftest":
            # 自检帧（V2.9）：只读诊断，按 type 唤醒等待者并原样带给上层
            with self._b_resp_lock:
                if self._b_waiter and "selftest" in self._b_expect:
                    self._b_resp = msg
                    self._b_resp_event.set()
                    return
            print(f"[B] 自检: {text}", file=sys.stderr, flush=True)
        elif mtype == "ready":
            # 上电或串口 DTR 复位都会发这条：计数即 B 板复位次数
            self._b_reset_count += 1
            self._b_last_reset_ts = time.time()
            st = msg.get("state")
            if isinstance(st, dict) and st:
                # 复位后固件执行器已回默认，这条 state 就是「复位后真值」，
                # 立刻入缓存让上层对账不必再等一个心跳周期。
                self._b_last_state = st
                self._b_last_state_ts = time.time()
            print(f"[B] 复位/就绪 #{self._b_reset_count}: {text}",
                  file=sys.stderr, flush=True)
        elif mtype == "alert":
            self._b_alert_count += 1
            self._b_last_alert = text
            self._b_last_alert_ts = time.time()
            print(f"[B] ⚠ 告警: {text}", file=sys.stderr, flush=True)
        else:
            print(f"[B] 未知帧: {text[:120]}", file=sys.stderr, flush=True)

    # ── B 板空闲心跳：久无流量时周期探测，连续失败才退避重开 ──
    def _b_maintenance_loop(self) -> None:
        """空闲期维护：超过一个心跳周期没有 B 板流量，就发一次只读 system/status。

        连续失败 _B_HB_FAILS_TO_REOPEN 次才重开（单次抖动不重开，避免 DTR 反复复位
        B 板）；心跳是只读命令，不改变任何执行器状态。
        """
        while not self._b_stop.wait(_B_HEARTBEAT_S):
            # 判据必须用「最后一次 state 帧」而不是「最后一次任何帧」：回读缓存只由
            # state 帧更新，而命令响应/告警等帧会一直刷出「有帧 = 链路活跃」的假象
            # （OLED 轮播每秒十几个 ACK）。一旦被跳过，心跳就再也不发，回读永久过期
            # （实测 age 261s，连带复位对账与不一致检测全部失效）。
            if time.time() - self._b_last_state_ts < _B_HEARTBEAT_S:
                continue                      # 刚拿到 state，等价于一次心跳
            text = self._send_b({"cmd": "system", "action": "status"},
                                allow_reopen=False, expect=("state",))
            if text.startswith("error"):
                self._b_hb_fails += 1
                print(f"[B] 心跳失败 {self._b_hb_fails} 次: {text}",
                      file=sys.stderr, flush=True)
                # 每失败 _B_HB_FAILS_TO_REOPEN 次才重开一次：单次抖动不重开（重开会经
                # DTR 复位 B 板）。**不在此处清零计数**，否则成功后就打不出「恢复正常」。
                if self._b_hb_fails % _B_HB_FAILS_TO_REOPEN == 0:
                    with self._b_lock:
                        self._reopen_b()
            else:
                if self._b_hb_fails:
                    print(f"[B] 心跳恢复正常（此前连续失败 {self._b_hb_fails} 次）",
                          file=sys.stderr, flush=True)
                    self._b_hb_fails = 0

    def serial_health(self) -> str:
        """串口链路健康度快照（只读，供 get_serial_health / 排障）。"""
        now = time.time()
        return json.dumps({
            # 进程实例标识：每起一个 MCP 进程换一个。上游据此判断「换了 MCP 进程」——
            # 换进程那一刻开串口必然 DTR 复位 B 板，而 reset_count 是进程内计数、
            # 重启即归零，只看增量会漏（上游 hardware.py 的复位对账依赖本字段）。
            "instance": self._instance,
            "uptime_s": round(now - self._started_ts, 1),
            "a": {
                "connected": self.ser_a is not None,
                "read_err_streak": self._a_err_count,
            },
            "b": {
                "connected": self.ser_b is not None,
                "port": self.port_b,
                "reopen_count": self._b_reopen_count,
                "reset_count": self._b_reset_count,
                "last_reset_ago_s": (round(now - self._b_last_reset_ts, 1)
                                     if self._b_last_reset_ts else None),
                "alert_count": self._b_alert_count,
                "last_alert": self._b_last_alert,
                "last_alert_ago_s": (round(now - self._b_last_alert_ts, 1)
                                     if self._b_last_alert_ts else None),
                "heartbeat_fails": self._b_hb_fails,
                "cmd_timeouts": self._b_cmd_timeouts,
                "read_err_streak": self._b_err_count,
                "last_frame_ago_s": (round(now - self._b_last_frame_ts, 1)
                                     if self._b_last_frame_ts else None),
                "last_state": self._b_last_state,
                "last_cmd": self._b_last_cmd,
            },
        }, ensure_ascii=False)

    def output_state(self) -> str:
        """B 板（执行器）硬件回读快照：来自 state 帧，以及 V2.9 起命令响应/就绪帧
        自带的 state 快照（后者让回读在每条命令后都立即刷新一遍）。

        与「命令下发值」不同，这是 B 板自己的实际电平。用它对比指令值，就能暴露
        「面板显示 0% 而风扇在转」这类静默失效（以前 B 板不上报，根本看不出来）。
        """
        now = time.time()
        return json.dumps({
            "state": dict(self._b_last_state),
            "age_s": (round(now - self._b_last_state_ts, 1)
                      if self._b_last_state_ts else None),
            "last_cmd": self._b_last_cmd,
        }, ensure_ascii=False)

    def _reopen_b(self) -> None:
        """重开 B 板串口（调用方需持有 _b_lock）。

        Uno 在串口 open 时会因 DTR 拉低而复位，需留足 2s 等 bootloader 退出再发命令，
        否则复位期间写入的命令会被丢弃。端口名优先用构造时记下的 port_b，句柄被清成
        None 后仍能重开。**不清输入缓冲**：复位横幅(ready)要留给读取线程计数上报，
        帧分类已经由读取线程负责，不再需要靠清缓冲来避免误匹配。
        """
        port = self.port_b or getattr(self.ser_b, "port", None)
        try:
            self.ser_b.close()
        except Exception:                            # noqa: BLE001
            pass
        if not port:
            print("[B] 串口重开失败：未知端口名", file=sys.stderr)
            self.ser_b = None
            return
        try:
            time.sleep(0.2)
            self.ser_b = serial.Serial(port, BAUD, timeout=1)
            time.sleep(2.0)
            # 只在真正打开成功时计数：失败重试不算「重开自愈」，否则日志里的
            # 第 N 次会把 24 次失败也算进去，读数严重失真。
            self._b_reopen_count += 1
            print(f"[B] 串口已重开自愈（第 {self._b_reopen_count} 次）: {port}",
                  file=sys.stderr)
        except Exception as e:                       # noqa: BLE001
            print(f"[B] 串口重开失败: {e}", file=sys.stderr)
            # 重开失败：清掉损坏句柄，后续调用明确返回「Module B 未连接」
            # 而不是对坏句柄继续写，避免静默丢指令。
            try:
                self.ser_b.close()
            except Exception:                        # noqa: BLE001
                pass
            self.ser_b = None

    # ── 工具实现 ──
    def handle_light(self, action, value=None, r=None, g=None, b=None, temp=None, count=None) -> str:
        cmd = {"cmd": "light", "action": action}
        if action == "white":
            cmd["value"] = value if value is not None else 255
        elif action == "night":
            # 夜灯只点亮居中的几颗灯珠；缺省亮度与固件 Config.h 的 LIGHT_NIGHT_LEVEL 一致
            cmd["value"] = value if value is not None else 60
        elif action == "temp":
            if temp is None:
                return "error: temp 需要 temp 参数(2700~6500)"
            cmd["temp"] = temp
            cmd["value"] = value if value is not None else 255
        elif action in ("rgb", "pixels"):
            if None in (r, g, b):
                return "error: rgb 需要 r/g/b 三个参数(0~255)"
            if action == "pixels":
                if type(count) is not int or not 1 <= count <= 8:
                    return "error: pixels count 必须为 1~8 的整数"
                cmd["count"] = count
            cmd.update({"r": r, "g": g, "b": b})
            if value is not None:
                cmd["value"] = value          # 整体亮度缩放，缺省由固件按 255 处理
        return self._send_a(cmd)

    def handle_door(self, action) -> str:
        return self._send_b({"cmd": "door", "action": action})

    def handle_window(self, action) -> str:
        return self._send_b({"cmd": "window", "action": action})

    def handle_fan(self, action, value=None) -> str:
        cmd = {"cmd": "fan", "action": action}
        if action == "set_speed":
            if value is None:
                return "error: set_speed 需要 value(0~255)"
            cmd["value"] = value
        return self._send_b(cmd)

    def handle_buzzer(self, action, count=None, on_ms=None, off_ms=None) -> str:
        cmd = {"cmd": "buzzer", "action": action}
        if action == "beep":
            cmd.update({
                "count": count if count is not None else 1,
                "on_ms": on_ms if on_ms is not None else 100,
                "off_ms": off_ms if off_ms is not None else 100,
            })
        return self._send_b(cmd)

    def handle_oled(self, action, line=None, text=None) -> str:
        cmd = {"cmd": "oled", "action": action}
        if action == "show_text":
            if line is None or text is None:
                return "error: show_text 需要 line(0~7) 和 text"
            cmd.update({"line": line, "text": text})
        return self._send_b(cmd)

    def handle_display(self, action, hour=None, minute=None, value=None) -> str:
        cmd = {"cmd": "display", "action": action}
        if action == "show_time":
            if hour is None or minute is None:
                return "error: show_time 需要 hour(0~23) 和 minute(0~59)"
            cmd.update({"hour": hour, "minute": minute})
        elif action == "show_number":
            if value is None:
                return "error: show_number 需要 value"
            cmd["value"] = value
        return self._send_b(cmd)

    def handle_ir(self, code=None, address=None, command=None) -> str:
        """红外发射。给 address+command 时由 nec_code 拼码，否则直接用十进制 code。"""
        if address is not None and command is not None:
            value = nec_code(int(address), int(command))
        elif code is not None:
            value = int(code)
        else:
            return "error: 红外发射需要 code，或 address + command"
        if not 0 <= value <= 0xFFFFFFFF:
            return "error: NEC 码需为 0~4294967295（32 位无符号）"
        # B 板 CommandParser 用 strtoul(...,10) 解析 code，必须下发十进制整数
        return self._send_b({"cmd": "ir", "action": "send_nec", "code": value})

    def handle_ac(self, **kwargs) -> str:
        """美的空调（RN02G(X) 红外状态帧）。把本次变更翻译成若干帧，逐帧下发。

        kwargs 里为 None 的项表示"保持不变"；任一帧失败即整体失败且不更新状态
        （B 板没收到时空调并未改变，状态必须保持一致）。
        """
        with self._ac_lock:
            try:
                new_state, changed = midea_ac.apply_overrides(self._ac, **kwargs)
            except ValueError as e:
                return f"error: {e}"
            # Reassert the absolute power/state frame even when our cache matches.
            # Swing uses toggle frames: only include those when explicitly changed.
            changed = changed | {"power"}
            frames = midea_ac.to_frames(new_state, changed)
            if not frames:
                return "ok 空调未开机，已忽略本次设置（请先 power=true）"
            for hexstr in frames:
                result = self._send_b({"cmd": "ir", "action": "send_midea",
                                       "hex": hexstr})
                if not result.startswith("ok"):
                    return result
            self._ac = new_state
            return f"ok 空调已更新（{len(frames)} 帧）"

    def handle_get_distance(self) -> str:
        """按需测量 B 板 HC-SR04；保留测距状态，不把无回波当成零距离。"""
        # Also accept response so old firmware's unknown_command fails immediately.
        return self._send_b({"cmd": "ultrasonic", "action": "read"},
                            allow_reopen=False, expect=("distance", "response"))

    def handle_get_sensor_status(self) -> str:
        with self._snapshot_lock:
            snap = dict(self._snapshot)
            events = list(self._events)
        if not snap:
            return "当前无传感器数据（Module A 未连接或未上报）"
        return json.dumps({"data": snap, "recent_events": events},
                          ensure_ascii=False)

    def handle_self_test(self) -> str:
        """B 板自检（固件 system/selftest，V2.9+）。

        返回固件侧的铁证：命令成功/失败计数、风扇两脚的方向位与电平、灯带 show()
        实际调用次数、以及直接把灯带数据脚当 GPIO 拉高/拉低后的读回值。用来二分
        「固件没执行」和「引脚物理没信号」。
        """
        return self._send_b({"cmd": "system", "action": "selftest"},
                            expect=("selftest",))


# ==================== MCP server 定义 ====================

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("smart-home")
HOME: Optional[HomeController] = None  # 在 main() 里赋值


def _audit(name: str) -> None:
    """工具调用审计行（stdout 是 stdio 通道，一律走 stderr）。

    mcp SDK 自带的 "Processing request of type CallToolRequest" 不含工具名，
    调用异常时无法定位是哪个工具/调用方，这里补一行带工具名的审计。
    """
    print(f"[MCP] -> {name}", file=sys.stderr, flush=True)


@mcp.tool()
async def light(
    action: Literal["off", "white", "night", "temp", "red", "green", "blue",
                    "yellow", "purple", "cyan", "rgb", "pixels"],
    value: Optional[int] = None,
    r: Optional[int] = None,
    g: Optional[int] = None,
    b: Optional[int] = None,
    temp: Optional[int] = None,
    count: Optional[int] = None,
) -> str:
    """控制灯光。action：off/white(可带 value 亮度 0-255)/night(夜灯，只亮中间几颗，value 可选)/
    temp(色温，需 temp 2700-6500K，value 可选亮度)/red/green/blue/yellow/purple/cyan/rgb(需 r,g,b 0-255，value 可选亮度缩放)。

    pixels：居中点亮 count(1~8) 颗，需 r/g/b，value 为亮度；旧固件会拒绝此动作。
    注意：B 板固件没有 "on" 分支，开灯请用 white（或彩色预设/色温）。
    """
    _audit("light")
    return await asyncio.to_thread(HOME.handle_light, action, value, r, g, b, temp, count)


@mcp.tool()
async def door(action: Literal["open", "close"]) -> str:
    """控制门。action：open(开门)/close(关门)。"""
    _audit("door")
    return await asyncio.to_thread(HOME.handle_door, action)


@mcp.tool()
async def window(action: Literal["open", "close", "normal"]) -> str:
    """控制窗。action：open/close/normal(恢复半开)。"""
    _audit("window")
    return await asyncio.to_thread(HOME.handle_window, action)


@mcp.tool()
async def fan(action: Literal["on", "off", "set_speed"],
              value: Optional[int] = None) -> str:
    """控制风扇。action：on(全速)/off(停)/set_speed(需 value 0-255)。"""
    _audit("fan")
    return await asyncio.to_thread(HOME.handle_fan, action, value)


@mcp.tool()
async def buzzer(action: Literal["on", "off", "beep"],
                 count: Optional[int] = None,
                 on_ms: Optional[int] = None,
                 off_ms: Optional[int] = None) -> str:
    """控制蜂鸣器。action：on(持续)/off(停)/beep(间歇，count 次数/on_ms 响时/off_ms 停时)。"""
    _audit("buzzer")
    return await asyncio.to_thread(HOME.handle_buzzer, action, count, on_ms, off_ms)


@mcp.tool()
async def oled(action: Literal["show_text", "clear"],
               line: Optional[int] = None,
               text: Optional[str] = None) -> str:
    """OLED 显示。action：show_text(需 line 0-7 与 text)/clear(清屏)。"""
    _audit("oled")
    return await asyncio.to_thread(HOME.handle_oled, action, line, text)


@mcp.tool()
async def display(action: Literal["show_time", "show_number", "clear"],
                  hour: Optional[int] = None,
                  minute: Optional[int] = None,
                  value: Optional[int] = None) -> str:
    """数码管显示。action：show_time(需 hour 0-23/minute 0-59)/show_number(需 value)/clear。"""
    _audit("display")
    return await asyncio.to_thread(HOME.handle_display, action, hour, minute, value)


@mcp.tool()
async def ir(code: Optional[int] = None,
             address: Optional[int] = None,
             command: Optional[int] = None) -> str:
    """红外发射（NEC 38kHz，Module B D12）。

    二选一：code 为十进制 32 位码；或 address(0-255)+command(0-255) 由服务端按 NEC
    帧序拼码（推荐，避免手算）。本系统不支持红外自学习/回环转发。
    """
    _audit("ir")
    return await asyncio.to_thread(HOME.handle_ir, code, address, command)


@mcp.tool()
async def ac(
    power: Optional[bool] = None,
    mode: Optional[Literal["auto", "cool", "heat", "dry", "fan"]] = None,
    temperature: Optional[int] = None,
    fan: Optional[Literal["auto", "low", "mid", "high"]] = None,
    swing_ud: Optional[bool] = None,
    swing_lr: Optional[bool] = None,
) -> str:
    """控制美的空调（红外遥控，Module B 的 D12 发射管）。

    只传需要改变的参数，未传的保持不变（服务端进程内记住当前设定）。
    power：开关机；mode：auto(自动)/cool(制冷)/heat(制热)/dry(抽湿)/fan(送风)；
    temperature：17~30℃ 的整数度（真遥控器 RN02G(X) 没有半度档）；
    fan：风速 auto(自动)/low(低)/mid(中)/high(高)；
    swing_ud/swing_lr：上下/左右扫风。遥控器上它们是**翻转键**，每次下发即翻转一次，
    所以只在设定值发生变化时才补发，实际朝向取决于空调当时的状态。
    注意：设置模式/温度/风速会连带把空调开机（状态帧自带开机效果），无需先 power=true。
    """
    _audit("ac")
    return await asyncio.to_thread(
        HOME.handle_ac, power=power, mode=mode, temperature=temperature,
        fan=fan, swing_ud=swing_ud, swing_lr=swing_lr)


@mcp.tool()
async def get_distance() -> str:
    """读取 B 板 HC-SR04 距离（Trig D6、Echo D5），单位厘米，范围 2~400 cm。

    每次调用实时测量；JSON 中 valid=true 才能使用 distance_cm。
    无回波/超范围时 valid=false、distance_cm=null，status 给出原因。
    仅测距，不控制任何执行器。串口断开或旧固件返回 error。
    """
    _audit("get_distance")
    return await asyncio.to_thread(HOME.handle_get_distance)


@mcp.tool()
async def get_sensor_status() -> str:
    """查询 A 板温度、湿度、光照、烟雾、雨、人体运动及最近事件。B 板距离请调用 get_distance。"""
    _audit("get_sensor_status")
    return await asyncio.to_thread(HOME.handle_get_sensor_status)


@mcp.tool()
async def get_serial_health() -> str:
    """查询串口链路健康度（只读，排障用）：A/B 板连接状态、B 板复位次数、最近引脚告警、心跳失败数。"""
    _audit("get_serial_health")
    return await asyncio.to_thread(HOME.serial_health)


@mcp.tool()
async def get_output_state() -> str:
    """查询 B 板（执行器）硬件回读状态：门/窗/风扇/灯/蜂鸣器的实际电平 + 观测时刻（只读）。"""
    _audit("get_output_state")
    return await asyncio.to_thread(HOME.output_state)


@mcp.tool()
async def self_test() -> str:
    """B 板自检（只读诊断，需固件 V2.9+）：固件版本、命令成败计数、风扇两脚的
    引脚方向与电平、灯带 show 次数、以及灯带数据脚拉高/拉低的读回值。

    排查「灯不亮 / 风扇自转」时用它区分：固件有没有真的执行 vs 引脚有没有被外设抢走
    vs 引脚物理短路/带载。"""
    _audit("self_test")
    return await asyncio.to_thread(HOME.handle_self_test)


# ==================== 入口 ====================

def main():
    global HOME
    # mcp SDK 每个请求打一行 "Processing request of type CallToolRequest"（不含工具名），
    # 轮询场景下每小时上千行纯噪声；工具名审计由 _audit() 负责，这里提到 WARNING。
    import logging
    logging.getLogger("mcp").setLevel(logging.WARNING)

    p = argparse.ArgumentParser(description="智能家居 MCP server (stdio)")
    p.add_argument("--port-a", help="Module A 串口（auto=探测）")
    p.add_argument("--port-b", help="Module B 串口（auto=探测）")
    p.add_argument("--no-serial", action="store_true",
                   help="不连接串口（仅暴露工具 schema，工具会返回错误）")
    args = p.parse_args()

    ser_a = ser_b = None
    port_a = port_b = None
    if not args.no_serial:
        port_a = args.port_a
        port_b = args.port_b
        if (not port_a or port_a == "auto") or (not port_b or port_b == "auto"):
            print("[探测] 自动识别模块中...", file=sys.stderr)
            if not port_a or port_a == "auto":
                port_a = detect_board('"board":"MODULE_A"', "A")
            if not port_b or port_b == "auto":
                port_b = detect_board('"board":"MODULE_B"', "B")
        if port_a:
            ser_a = connect(port_a, "A")
        if port_b:
            ser_b = connect(port_b, "B")
        if not ser_a and not ser_b:
            print("[警告] 未连接任何 Arduino 模块；工具将返回错误信息。", file=sys.stderr)

    HOME = HomeController(ser_a=ser_a, ser_b=ser_b, port_a=port_a, port_b=port_b)
    print("[MCP] 暴露 14 个工具：light/door/window/fan/buzzer/oled/display/ir/ac"
          "/get_sensor_status/get_distance/get_serial_health/get_output_state/self_test",
          file=sys.stderr)
    print("[MCP] stdio 传输已就绪，等待 client。", file=sys.stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
