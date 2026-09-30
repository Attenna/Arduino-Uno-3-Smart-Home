"""mcp_home_server.py — 智能家居 MCP server（stdio）

独占持有 Module A（传感器）/Module B（执行器）两块 Arduino 串口，
通过标准 MCP 协议向大模型暴露 8 个控制/查询工具：
    light / door / window / fan / buzzer / oled / display / get_sensor_status

数据流：
    LLM(voice_assistant) ──MCP stdio──▶ 本 server ──JSON 命令──▶ Module B (USB)
                                         │
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
from collections import deque
from typing import Literal, Optional

import serial
import serial.tools.list_ports

BAUD = 115200

# ---- 矩阵键盘开门密码（正式版硬件：仅 "1" 键，密码 1111 = 连按 4 次）----
KEYPAD_CODE = "1111"          # 开门密码
KEYPAD_WINDOW_S = 10.0        # 全部按键必须在该时间窗口内完成，超时清空
KEYPAD_OPEN_HOLD_S = 10.0     # 触发后开门保持秒数，到时自动关门（需求2：门禁通过 10 秒后关门）


# ==================== 串口探测 / 连接（移植自 link_server.py）====================

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


# ==================== 智能家居控制器（持有串口）====================

class HomeController:
    """独占 A/B 串口；A 板后台读线程缓存状态；B 板同步发命令。"""

    def __init__(self, ser_a=None, ser_b=None):
        self.ser_a = ser_a
        self.ser_b = ser_b
        self._b_lock = threading.Lock()
        self._snapshot_lock = threading.Lock()
        self._snapshot: dict = {}
        self._events: deque = deque(maxlen=50)
        self._ready: dict = {}
        self._keypad_buf: list = []   # [(ts, key), ...] 键盘密码缓冲
        self._a_thread: Optional[threading.Thread] = None
        if self.ser_a is not None:
            self._a_thread = threading.Thread(
                target=self._read_a_loop, daemon=True, name="module-a-reader")
            self._a_thread.start()

    # ── A 板读取线程 ──
    def _read_a_loop(self):
        while True:
            try:
                raw = self.ser_a.readline()
                if not raw:
                    continue
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
                        })
                    if ev_name == "keypad":
                        self._handle_keypad(msg.get("key", ""))
                # response / who 忽略
            except Exception as e:
                print(f"[A] 读线程异常: {e}", file=sys.stderr)
                time.sleep(0.5)

    # ── 矩阵键盘：密码聚合开门 ──
    def _handle_keypad(self, key: str):
        """A 板矩阵键盘按键事件 → 在时间窗内聚合成密码 → 1111 正确则开门。"""
        if not key:
            return
        now = time.time()
        with self._snapshot_lock:
            self._keypad_buf.append((now, key))
            self._keypad_buf[:] = [(t, k) for t, k in self._keypad_buf
                                   if now - t <= KEYPAD_WINDOW_S]
            seq = "".join(k for _, k in self._keypad_buf)
            # 序列不再是密码前缀 → 以当前键重新起序列
            if not KEYPAD_CODE.startswith(seq):
                self._keypad_buf = [(now, key)] if key == KEYPAD_CODE[0] else []
                seq = key if key == KEYPAD_CODE[0] else ""
            granted = seq == KEYPAD_CODE
            if granted:
                self._keypad_buf.clear()

        if granted:
            print(f"[键盘] 密码 {KEYPAD_CODE} 正确，执行静默开门",
                  file=sys.stderr)
            self._report_granted_event()
            threading.Thread(target=self._open_door_by_keypad,
                             daemon=True, name="keypad-door").start()
        else:
            print(f"[键盘] 按键 {key!r}，当前序列 {seq!r}"
                  f"（{len(seq)}/{len(KEYPAD_CODE)}）", file=sys.stderr)

    def _report_granted_event(self):
        """键盘密码开门上报为「门禁通过」事件，供 web 全屋模式判定进门。

        复用 A 板 event 通道（recent_events），web 侧 _ingest_event →
        automation.on_event({"event":"face","status":"granted"}) →
        home_mode.on_face_granted()，由 Linux 统一记录日志与延时关门。
        """
        with self._snapshot_lock:
            self._events.append({
                "event": "face", "status": "granted",
                "person": f"键盘密码({KEYPAD_CODE})",
                "face_id": f"keypad:{KEYPAD_CODE}",
                "timestamp": int(time.time() * 1000),
            })

    def _open_door_by_keypad(self):
        """键盘密码开门：蜂鸣 2 短声提示 → 开门 → 延时自动关门。"""
        self.handle_buzzer("beep", count=2, on_ms=80, off_ms=80)
        r = self.handle_door("open")
        print(f"[键盘] 开门指令 → Module B：{r}", file=sys.stderr)
        time.sleep(KEYPAD_OPEN_HOLD_S)
        r2 = self.handle_door("close")
        print(f"[键盘] {KEYPAD_OPEN_HOLD_S}s 后自动关门 → Module B：{r2}",
              file=sys.stderr)

    # ── B 板发命令 + 收响应 ──
    def _send_b(self, cmd: dict) -> str:
        if self.ser_b is None:
            return "error: Module B 未连接，无法执行硬件操作"
        line = json.dumps(cmd, ensure_ascii=False) + "\n"
        with self._b_lock:
            try:
                self.ser_b.reset_input_buffer()
                self.ser_b.write(line.encode("utf-8"))
                # 读一行 response（800ms 超时，Serial.timeout 已设）
                deadline = time.time() + 0.8
                while time.time() < deadline:
                    raw = self.ser_b.readline()
                    if not raw:
                        continue
                    text = raw.decode("utf-8", "replace").strip()
                    if not text:
                        continue
                    try:
                        resp = json.loads(text)
                    except json.JSONDecodeError:
                        return f"ok (非JSON回显: {text})"
                    if resp.get("result") == "ok":
                        return "ok"
                    return f"error: B 板返回 {resp}"
                return "error: B 板响应超时"
            except Exception as e:
                return f"error: 串口写入失败 {e}"

    # ── 工具实现 ──
    def handle_light(self, action, value=None, r=None, g=None, b=None) -> str:
        cmd = {"cmd": "light", "action": action}
        if action == "white":
            cmd["value"] = value if value is not None else 255
        elif action == "rgb":
            if None in (r, g, b):
                return "error: rgb 需要 r/g/b 三个参数(0~255)"
            cmd.update({"r": r, "g": g, "b": b})
        return self._send_b(cmd)

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

    def handle_get_sensor_status(self) -> str:
        with self._snapshot_lock:
            snap = dict(self._snapshot)
            events = list(self._events)
        if not snap:
            return "当前无传感器数据（Module A 未连接或未上报）"
        return json.dumps({"data": snap, "recent_events": events},
                          ensure_ascii=False)


# ==================== MCP server 定义 ====================

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("smart-home")
HOME: Optional[HomeController] = None  # 在 main() 里赋值


@mcp.tool()
async def light(
    action: Literal["on", "off", "white", "red", "green", "blue",
                    "yellow", "purple", "cyan", "rgb"],
    value: Optional[int] = None,
    r: Optional[int] = None,
    g: Optional[int] = None,
    b: Optional[int] = None,
) -> str:
    """控制灯光。action：on/off/white(可带 value 亮度 0-255)/red/green/blue/yellow/purple/cyan/rgb(需 r,g,b 0-255)。"""
    return await asyncio.to_thread(HOME.handle_light, action, value, r, g, b)


@mcp.tool()
async def door(action: Literal["open", "close"]) -> str:
    """控制门。action：open(开门)/close(关门)。"""
    return await asyncio.to_thread(HOME.handle_door, action)


@mcp.tool()
async def window(action: Literal["open", "close", "normal"]) -> str:
    """控制窗。action：open/close/normal(恢复半开)。"""
    return await asyncio.to_thread(HOME.handle_window, action)


@mcp.tool()
async def fan(action: Literal["on", "off", "set_speed"],
              value: Optional[int] = None) -> str:
    """控制风扇。action：on(全速)/off(停)/set_speed(需 value 0-255)。"""
    return await asyncio.to_thread(HOME.handle_fan, action, value)


@mcp.tool()
async def buzzer(action: Literal["on", "off", "beep"],
                 count: Optional[int] = None,
                 on_ms: Optional[int] = None,
                 off_ms: Optional[int] = None) -> str:
    """控制蜂鸣器。action：on(持续)/off(停)/beep(间歇，count 次数/on_ms 响时/off_ms 停时)。"""
    return await asyncio.to_thread(HOME.handle_buzzer, action, count, on_ms, off_ms)


@mcp.tool()
async def oled(action: Literal["show_text", "clear"],
               line: Optional[int] = None,
               text: Optional[str] = None) -> str:
    """OLED 显示。action：show_text(需 line 0-7 与 text)/clear(清屏)。"""
    return await asyncio.to_thread(HOME.handle_oled, action, line, text)


@mcp.tool()
async def display(action: Literal["show_time", "show_number", "clear"],
                  hour: Optional[int] = None,
                  minute: Optional[int] = None,
                  value: Optional[int] = None) -> str:
    """数码管显示。action：show_time(需 hour 0-23/minute 0-59)/show_number(需 value)/clear。"""
    return await asyncio.to_thread(HOME.handle_display, action, hour, minute, value)


@mcp.tool()
async def get_sensor_status() -> str:
    """查询当前传感器状态：温度、湿度、光照、烟雾、雨、距离、人体运动、土壤湿度等 + 最近事件。"""
    return await asyncio.to_thread(HOME.handle_get_sensor_status)


# ==================== 入口 ====================

def main():
    global HOME
    p = argparse.ArgumentParser(description="智能家居 MCP server (stdio)")
    p.add_argument("--port-a", help="Module A 串口（auto=探测）")
    p.add_argument("--port-b", help="Module B 串口（auto=探测）")
    p.add_argument("--no-serial", action="store_true",
                   help="不连接串口（仅暴露工具 schema，工具会返回错误）")
    args = p.parse_args()

    ser_a = ser_b = None
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

    HOME = HomeController(ser_a=ser_a, ser_b=ser_b)
    print(f"[MCP] 暴露 8 个工具：light/door/window/fan/buzzer/oled/display/get_sensor_status",
          file=sys.stderr)
    print("[MCP] stdio 传输已就绪，等待 client。", file=sys.stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
