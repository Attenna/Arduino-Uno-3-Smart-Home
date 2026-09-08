"""
PC 端测试控制台 — Arduino 智能家居双板统一测试工具 v2.0
=========================================================
通过 USB 串口同时问讯 Module_A (传感器板) 和控制 Module_B (执行板)。
支持单板模式、CSV 数据日志、自动恢复连接。

用法:
    python test_serial.py                              # 自动检测 COM 口
    python test_serial.py --port-a COM3 --port-b COM4  # 手动指定
    python test_serial.py --port-a COM3                # 仅连接 A 板
    python test_serial.py --auto-test                  # 自动跑一轮测试后退出
    python test_serial.py --demo                       # 运行交互演示
    python test_serial.py --log sensor_log.csv         # 记录传感器数据到 CSV

依赖: pip install pyserial
"""

import serial
import serial.tools.list_ports
import time
import sys
import os
import json
import argparse
import threading
from datetime import datetime


# ==================== 配置 ====================
BAUD_A = 115200
BAUD_B = 115200
TIMEOUT = 1.0
AUTO_DETECT_TIMEOUT = 2.0


# ==================== CSV 日志 ====================

class CsvLogger:
    """传感器数据 CSV 记录器"""

    def __init__(self, filepath):
        self.filepath = filepath
        self._file = None
        self._header_written = False
        self._lock = threading.Lock()

    def open(self):
        if self._file:
            return
        exists = os.path.exists(self.filepath)
        self._file = open(self.filepath, "a", encoding="utf-8", newline="")
        if not exists:
            self._write_header()
            self._header_written = True

    def _write_header(self):
        self._file.write("timestamp,source,type,value\n")
        self._file.flush()

    def log(self, source, msg_type, value):
        """source: 'A'|'B', msg_type: e.g. 'EVENT-PIR', value: e.g. 'MOTION'"""
        with self._lock:
            if not self._file:
                return
            ts = datetime.now().isoformat(timespec="seconds")
            # 转义 CSV 特殊字符
            value_safe = value.replace('"', '""')
            self._file.write(f'{ts},{source},{msg_type},"{value_safe}"\n')
            self._file.flush()

    def close(self):
        if self._file:
            self._file.close()
            self._file = None


# ==================== 串口工具 ====================

def list_ports():
    """列出所有可用串口"""
    ports = serial.tools.list_ports.comports()
    return [(p.device, p.description, p.hwid) for p in ports]


def _open_serial(dev, baud, timeout=0.3):
    """打开串口；失败时抛出带原因的异常，供上层提示用户（通常是串口被占用）。"""
    return serial.Serial(dev, baud, timeout=timeout)


def _read_lines_until(ser, needles, timeout=1.2):
    """
    读取串口数据，直到命中任意一个"识别特征串"或超时。
    needles: list[bytes] —— 命中任一即成功。
    返回命中的 needle 或 None。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ser.in_waiting:
            line = ser.readline()
            for n in needles:
                if n in line:
                    return n
    return None


def find_board(baud, identify_cmd, identify_response, timeout=1.2):
    """
    在所有可用串口上发送识别命令，返回匹配的端口。
    优先只对描述含 Arduino/CH340/CH9102/USB-SERIAL 的串口做识别，跳过蓝牙等无关串口。
    打开失败会明确提示（串口被占用是常见原因）。
    """
    ports = list_ports()
    candidates = []
    for dev, desc, hwid in ports:
        d = desc.lower()
        if any(k in d for k in ("arduino", "ch340", "ch9102", "usb-serial", "usb serial", "uno")):
            candidates.append((dev, desc))
        else:
            print(f"  [跳过] {dev} ({desc})  —— 非 Arduino 类设备")
    if not candidates:
        candidates = [(p[0], p[1]) for p in ports]

    for dev, desc in candidates:
        print(f"  [探测] {dev} ({desc}) ...", end="", flush=True)
        try:
            ser = _open_serial(dev, baud)
            time.sleep(0.1)
            ser.reset_input_buffer()
            ser.write(identify_cmd)
            hit = _read_lines_until(ser, [identify_response], timeout)
            ser.close()
            if hit:
                print(" 命中!")
                return dev
            print(" 无响应")
        except serial.SerialException as e:
            print(f" 占用/无法打开 ({e})")
            continue
        except Exception as e:
            print(f" 跳过 ({e})")
            continue
    return None


def identify_a_port(baud, timeout=1.5):
    """
    识别 Module A：发送 WHO（文本），等待 JSON {"board":"MODULE_A"}。
    兜底：A 板每 2 秒主动上报 type:data，也可仅凭被动数据识别。
    """
    for dev, desc, _hwid in [p for p in list_ports() if any(
            k in p[1].lower() for k in ("arduino", "ch340", "ch9102", "usb-serial", "usb serial", "uno"))]:
        print(f"  [探测] {dev} ({desc}) ...", end="", flush=True)
        try:
            ser = _open_serial(dev, baud)
            time.sleep(0.1)
            ser.reset_input_buffer()
            ser.write(b"WHO\n")
            # 特征 1: WHO 响应含 MODULE_A；特征 2: 主动上报 type:data（兜底）
            hit = _read_lines_until(ser, [b'"board":"MODULE_A"', b'"type":"data"'], timeout)
            ser.close()
            if hit:
                print(f" 命中! ({'WHO' if b'board' in hit else 'data'})")
                return dev
            print(" 无响应")
        except serial.SerialException as e:
            print(f" 占用/无法打开 ({e})")
            continue
        except Exception as e:
            print(f" 跳过 ({e})")
            continue
    return None


def identify_b_port(baud, timeout=1.5):
    """
    识别 Module B：发送 JSON {"cmd":"system","action":"who"}，
    等待 JSON {"board":"MODULE_B"}。
    """
    for dev, desc, _hwid in [p for p in list_ports() if any(
            k in p[1].lower() for k in ("arduino", "ch340", "ch9102", "usb-serial", "usb serial", "uno"))]:
        print(f"  [探测] {dev} ({desc}) ...", end="", flush=True)
        try:
            ser = _open_serial(dev, baud)
            time.sleep(0.1)
            ser.reset_input_buffer()
            ser.write(b'{"cmd":"system","action":"who"}\n')
            hit = _read_lines_until(ser, [b'"board":"MODULE_B"'], timeout)
            ser.close()
            if hit:
                print(" 命中!")
                return dev
            print(" 无响应")
        except serial.SerialException as e:
            print(f" 占用/无法打开 ({e})")
            continue
        except Exception as e:
            print(f" 跳过 ({e})")
            continue
    return None


def connect_board(port, baud, label):
    """连接指定端口"""
    try:
        ser = serial.Serial(port, baud, timeout=TIMEOUT)
        time.sleep(0.2)
        ser.reset_input_buffer()
        print(f"  [{label}] 已连接 {port} @ {baud} baud")
        return ser
    except Exception as e:
        print(f"  [{label}] 连接 {port} 失败: {e}")
        return None


def send_cmd(ser, cmd, drain=True, wait=0.6):
    """发送命令并返回响应行列表。ser 可为 None（静默跳过）。"""
    if ser is None:
        return []
    if isinstance(cmd, str):
        cmd = (cmd + "\n").encode()
    # 暂停后台事件监听线程，避免其抢占串口数据
    _pause_listener.set()
    try:
        if drain:
            ser.reset_input_buffer()
        ser.write(cmd)
        # 持续读取直到 wait 超时或读到非空响应，兼容 A/B 板响应较慢的情况
        lines = []
        deadline = time.time() + wait
        got_any = False
        while time.time() < deadline:
            if ser.in_waiting:
                chunk = ser.read(ser.in_waiting)
                for raw in chunk.split(b"\n"):
                    line = raw.decode("utf-8", errors="replace").strip()
                    if line:
                        lines.append(line)
                        got_any = True
            if got_any and ser.in_waiting == 0:
                # 读到过数据且当前无更多数据，可提前结束
                time.sleep(0.02)
                if ser.in_waiting == 0:
                    break
            else:
                time.sleep(0.02)
        return lines
    except (serial.SerialException, OSError) as e:
        print(f"  [ERR] 串口通信失败: {e}")
        return []
    finally:
        _pause_listener.clear()


def send_and_print(ser, cmd, prefix="  <- "):
    """发送命令并打印响应。ser 可为 None。"""
    if ser is None:
        print(f"  [SKIP] {cmd} (未连接)")
        return []
    with _print_lock:
        print(f"\r\033[2K  -> {cmd}")
    lines = send_cmd(ser, cmd)
    with _print_lock:
        for line in lines:
            print(f"  {prefix} {line}")
    return lines


# ==================== 事件监听（后台线程） ====================

_event_stop = False
_csv_logger = None  # 可选的 CSV 记录器引用
_print_lock = threading.Lock()  # 保护事件线程与主线程的打印，避免输入错乱
_pause_listener = threading.Event()  # 置位时事件线程暂停读取，让 send_cmd 独占串口


def event_listener(ser_a, csv_logger=None):
    """
    后台守护线程 — 持续监听 Module_A 的主动推送（JSON 事件）。
    新固件 A 板主动推送：
      数据  {"module":"sensor","type":"data","data":{...}}
      事件  {"module":"sensor","type":"event","event":"rfid","uid":...}
    收到事件时打印并可选地记录到 CSV。
    """
    global _event_stop
    if ser_a is None:
        return
    buf = b""
    ser_a.timeout = 0.05
    _last_data_print = 0.0   # 限频：周期数据默认不打印，仅在明确请求时才打印
    _last_data_hash = None   # 数据变化去重
    while not _event_stop:
        try:
            if _pause_listener.is_set():
                time.sleep(0.01)
                continue
            if ser_a.in_waiting:
                chunk = ser_a.read(ser_a.in_waiting)
                buf += chunk
                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("module") != "sensor":
                        continue
                    mtype = msg.get("type")
                    if mtype == "event":
                        ev = msg.get("event", "")
                        detail = ", ".join(f"{k}={v}" for k, v in msg.items()
                                           if k not in ("module", "type", "event"))
                        text = f"{ev}" + (f" ({detail})" if detail else "")
                        with _print_lock:
                            # 用 \r 清空当前输入行，避免污染 input() 缓冲
                            print(f"\r\033[2K  \033[1;33m[EVENT] {text}\033[0m")
                            print("> ", end="", flush=True)
                        if csv_logger:
                            csv_logger.log("A", f"EVENT-{ev}", detail or ev)
                    elif mtype == "data":
                        # 周期数据：静默记录到 CSV，不刷屏；
                        # 只有数据"有变化"时才在终端提示（限频，避免洪水）
                        data = msg.get("data", {})
                        if csv_logger:
                            csv_logger.log("A", "DATA", json.dumps(data, ensure_ascii=False))
                        h = hash(json.dumps(data, sort_keys=True))
                        if h != _last_data_hash:
                            _last_data_hash = h
                            now = time.time()
                            if now - _last_data_print >= 3.0:
                                _last_data_print = now
                                with _print_lock:
                                    print(f"\r\033[2K  [DATA] {json.dumps(data, ensure_ascii=False)}")
                                    print("> ", end="", flush=True)
            else:
                time.sleep(0.05)
        except (serial.SerialException, OSError):
            time.sleep(0.5)
        except Exception:
            time.sleep(0.1)


# ==================== 测试函数 ====================

def test_module_a(ser_a):
    """测试 Module_A 全部传感器。ser_a 可为 None。"""
    if ser_a is None:
        print("\n  [SKIP] Module_A 未连接")
        return

    print("\n" + "=" * 60)
    print("Module_A 传感器测试")
    print("=" * 60)

    print("\n--- 设备识别 ---")
    send_and_print(ser_a, "WHO")

    print("\n--- 立即上报一次完整状态 ---")
    send_and_print(ser_a, "REPORT")

    print("\n  [OK] Module_A 测试完成（其余传感器数据请查看下方主动推送 / 使用交互菜单）")


def test_module_b(ser_b):
    """测试 Module_B 执行器。ser_b 可为 None。"""
    if ser_b is None:
        print("\n  [SKIP] Module_B 未连接")
        return

    print("\n" + "=" * 60)
    print("Module_B 执行器测试")
    print("=" * 60)

    print("\n--- 状态查询 + 设备识别 ---")
    send_and_print(ser_b, "B:WHO")
    send_and_print(ser_b, "B:STATUS")
    time.sleep(0.3)

    print("\n--- 灯光测试 ---")
    colors = [
        ("B:LIGHT:RED", "红色"),
        ("B:LIGHT:GREEN", "绿色"),
        ("B:LIGHT:BLUE", "蓝色"),
        ("B:LIGHT:YELLOW", "黄色"),
        ("B:LIGHT:PURPLE", "紫色"),
        ("B:LIGHT:CYAN", "青色"),
        ("B:LIGHT:WHITE", "白色"),
        ("B:LIGHT:OFF", "关闭"),
    ]
    for cmd, desc in colors:
        print(f"  {desc}...")
        send_and_print(ser_b, cmd)
        time.sleep(0.3)

    print("\n--- 风扇测试 ---")
    for spd in [80, 160, 255]:
        send_and_print(ser_b, f"B:FAN:{spd}")
        time.sleep(0.5)
    send_and_print(ser_b, "B:FAN:OFF")

    print("\n--- 蜂鸣器测试 ---")
    send_and_print(ser_b, "B:BUZZER:BEEP:2:100:100")

    print("\n--- 门测试 ---")
    send_and_print(ser_b, "B:DOOR:OPEN")
    time.sleep(1.0)
    send_and_print(ser_b, "B:DOOR:CLOSE")

    print("\n--- 窗测试 ---")
    send_and_print(ser_b, "B:WINDOW:OPEN")
    time.sleep(0.5)
    send_and_print(ser_b, "B:WINDOW:NORMAL")
    time.sleep(0.5)
    send_and_print(ser_b, "B:WINDOW:CLOSE")
    time.sleep(0.5)
    send_and_print(ser_b, "B:WINDOW:NORMAL")

    print("\n--- 警报场景测试 ---")
    send_and_print(ser_b, "B:ALARM:SMOKE")
    time.sleep(1.0)
    send_and_print(ser_b, "B:ALARM:OFF")
    time.sleep(0.5)
    send_and_print(ser_b, "B:ALARM:RAIN")
    time.sleep(1.0)
    send_and_print(ser_b, "B:ALARM:OFF")

    print("\n--- 最终状态 ---")
    send_and_print(ser_b, "B:STATUS")
    print("\n  [OK] Module_B 执行器测试完成")


def test_all(ser_a, ser_b):
    """全部测试。支持单板模式。"""
    if ser_a is None and ser_b is None:
        print("\n  [ERROR] 没有连接任何模块!")
        return

    test_module_a(ser_a)
    time.sleep(0.5)
    test_module_b(ser_b)
    print("\n" + "=" * 60)
    print("  全部测试完成!")
    print("=" * 60)


# ==================== 集成场景测试 ====================

def _read_a_data(ser_a, tries=3):
    """向 A 板发 REPORT，解析并返回 data 字典；失败返回 {}。"""
    lines = send_cmd(ser_a, "REPORT")
    for line in lines:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "data":
            return msg.get("data", {})
    return {}


def scenario_smoke_response(ser_a, ser_b):
    """
    场景: 检测到烟雾 → 自动告警（演示，业务决策在 PC 端完成）
    """
    if ser_a is None:
        print("  [SKIP] 烟雾联动需要 Module_A")
        return
    if ser_b is None:
        print("  [SKIP] 烟雾联动需要 Module_B")
        return

    print("\n--- 烟雾联动场景 ---")
    data = _read_a_data(ser_a)
    print(f"  A板数据: {data}")
    smoke = data.get("smoke", False)
    if smoke:
        print("  [WARN] 检测到烟雾! 触发告警...")
        send_and_print(ser_b, '{"cmd":"buzzer","action":"on"}')
        send_and_print(ser_b, '{"cmd":"light","action":"red"}')
        time.sleep(2)
        send_and_print(ser_b, '{"cmd":"buzzer","action":"off"}')
    else:
        print("  [OK] 烟雾正常")


def scenario_env_monitor(ser_a, ser_b, csv_logger=None):
    """
    场景: 环境监控 — 读取温度/湿度，可选推送 OLED，记录到 CSV
    """
    if ser_a is None:
        print("  [SKIP] 环境监控需要 Module_A")
        return

    print("\n--- 环境监控场景 ---")
    for _ in range(3):
        data = _read_a_data(ser_a)
        temp = data.get("temperature")
        humid = data.get("humidity")
        print(f"  温度={temp} 湿度={humid}  完整={data}")
        if csv_logger:
            csv_logger.log("A", "ENV", f"T={temp},H={humid}")

        if ser_b and temp is not None:
            # 推送到 B 板 OLED（第 2 行显示温度）
            send_and_print(ser_b, json.dumps(
                {"cmd": "oled", "action": "show_text", "line": 2,
                 "text": f"T: {temp} C"}))
        time.sleep(2)


def scenario_auto_home(ser_a, ser_b):
    """
    场景: 离家模式 — 根据 PIR 传感器自动开关灯（演示）
    """
    if ser_a is None:
        print("  [SKIP] 离家模式需要 Module_A")
        return
    if ser_b is None:
        print("  [SKIP] 离家模式需要 Module_B")
        return

    print("\n--- 离家自动模式场景 ---")
    print("  监测人体红外 (motion) 10 秒...")
    for i in range(5):
        data = _read_a_data(ser_a)
        motion = data.get("motion", False)
        if motion:
            print(f"  [第{i+1}次] 检测到人体 → 开灯")
            send_and_print(ser_b, '{"cmd":"light","action":"white","value":255}')
        else:
            print(f"  [第{i+1}次] 无人 → 关灯")
            send_and_print(ser_b, '{"cmd":"light","action":"off"}')
        time.sleep(2)
    print("  [OK] 离家模式场景结束")


# ==================== 交互式菜单 ====================

def interactive_menu(ser_a, ser_b, csv_logger=None):
    """交互式命令菜单。支持单板模式。"""
    global _event_stop
    _event_stop = False

    # 启动后台事件监听器
    listener_thread = threading.Thread(
        target=event_listener, args=(ser_a, csv_logger), daemon=True
    )
    listener_thread.start()

    has_a = ser_a is not None
    has_b = ser_b is not None

    menu = """
╔══════════════════════════════════════════════════╗
║         Arduino 智能家居 双板控制台 v2.0         ║
╠══════════════════════════════════════════════════╣"""

    if has_a:
        menu += """
║  Module_A (传感器) - 已连接                      ║
║  ─────────────────                              ║
║  a1  立即上报状态 REPORT                          ║
║  a2  设备识别 WHO                                ║
║  a3  设置上报间隔 INTERVAL                       ║
║  (传感器数据/事件会自动推送，见下方 [EVENT])      ║"""

    if has_b:
        menu += """
║  Module_B (执行器) - 已连接                      ║
║  ─────────────────                              ║
║  b1  查询状态 STATUS      b11 灯光颜色切换       ║
║  b2  开门 DOOR:OPEN       b12 蜂鸣器 BUZZER      ║
║  b3  关门 DOOR:CLOSE      b13 蜂鸣器 持续响      ║
║  b4  窗正常 WINDOW        b14 蜂鸣器 间歇响      ║
║  b5  关窗 WINDOW:CLOSE    b15 蜂鸣器 停止        ║
║  b6  开窗 WINDOW:OPEN     b16 帮助 HELP          ║
║  b7  开风扇 FAN:ON        b17 查询状态(JSON)     ║
║  b8  关风扇 FAN:OFF       b18 设备识别(JSON)     ║
║  b9  灯开 LIGHT:ON                               ║
║  b10 灯关 LIGHT:OFF                              ║"""

    if has_a and has_b:
        menu += """
╠══════════════════════════════════════════════════╣
║  场景 (需双板)                                   ║
║  s1  烟雾联动            s3  离家自动模式        ║
║  s2  环境监控            s4  跑全部测试          ║
║                          s5  TIME 设时钟         ║"""

    menu += """
╠══════════════════════════════════════════════════╣
║  q   退出                                        ║
╚══════════════════════════════════════════════════╝
"""
    print(menu)

    if not has_a and not has_b:
        print("  [ERROR] 没有连接任何模块!")
        return

    while True:
        try:
            with _print_lock:
                choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  退出.")
            _event_stop = True
            break

        if choice == "q":
            print("  退出.")
            _event_stop = True
            break

        # Module_A 命令（新固件：只认 WHO / REPORT / INTERVAL）
        elif choice == "a1":  send_and_print(ser_a, "REPORT")   # 立即上报完整状态
        elif choice == "a2":  send_and_print(ser_a, "WHO")      # 设备识别
        elif choice == "a3":
            iv = input("  输入上报间隔(毫秒, 200~60000，如 1000): ").strip()
            if iv.isdigit():
                send_and_print(ser_a, f"INTERVAL:{iv}")

        # Module_B 命令
        elif choice == "b1":  send_and_print(ser_b, "B:STATUS")
        elif choice == "b2":  send_and_print(ser_b, "B:DOOR:OPEN")
        elif choice == "b3":  send_and_print(ser_b, "B:DOOR:CLOSE")
        elif choice == "b4":  send_and_print(ser_b, "B:WINDOW:NORMAL")
        elif choice == "b5":  send_and_print(ser_b, "B:WINDOW:CLOSE")
        elif choice == "b6":  send_and_print(ser_b, "B:WINDOW:OPEN")
        elif choice == "b7":  send_and_print(ser_b, "B:FAN:255")
        elif choice == "b8":  send_and_print(ser_b, "B:FAN:OFF")
        elif choice == "b9":  send_and_print(ser_b, "B:LIGHT:ON")
        elif choice == "b10": send_and_print(ser_b, "B:LIGHT:OFF")
        elif choice == "b11":
            print("  颜色: 1-RED 2-GREEN 3-BLUE 4-YELLOW 5-PURPLE 6-CYAN 7-WHITE 8-OFF")
            c = input("  选择颜色 (1-8): ").strip()
            color_map = {
                "1": "B:LIGHT:RED", "2": "B:LIGHT:GREEN",
                "3": "B:LIGHT:BLUE", "4": "B:LIGHT:YELLOW",
                "5": "B:LIGHT:PURPLE", "6": "B:LIGHT:CYAN",
                "7": "B:LIGHT:ON", "8": "B:LIGHT:OFF"
            }
            cmd = color_map.get(c, "B:LIGHT:ON")
            send_and_print(ser_b, cmd)
        elif choice == "b12":
            print("  蜂鸣器: 1-短鸣 2-长鸣 3-停止")
            bz = input("  (1/2/3): ").strip()
            if bz == "1":   send_and_print(ser_b, "B:BUZZER:BEEP:2:100:100")
            elif bz == "2": send_and_print(ser_b, "B:BUZZER:BEEP:5:200:200")
            else:           send_and_print(ser_b, "B:BUZZER:OFF")
        elif choice == "b13": send_and_print(ser_b, '{"cmd":"buzzer","action":"on"}')
        elif choice == "b14": send_and_print(ser_b, '{"cmd":"buzzer","action":"beep","count":5,"on_ms":200,"off_ms":200}')
        elif choice == "b15": send_and_print(ser_b, '{"cmd":"buzzer","action":"off"}')
        elif choice == "b16": send_and_print(ser_b, "B:HELP")
        elif choice == "b17": send_and_print(ser_b, '{"cmd":"system","action":"status"}')
        elif choice == "b18": send_and_print(ser_b, '{"cmd":"system","action":"who"}')

        # 场景
        elif choice == "s1": scenario_smoke_response(ser_a, ser_b)
        elif choice == "s2": scenario_env_monitor(ser_a, ser_b, csv_logger)
        elif choice == "s3": scenario_auto_home(ser_a, ser_b)
        elif choice == "s4": test_all(ser_a, ser_b)
        elif choice == "s5":
            t = input("  输入时间 (HHMM, 如 1430): ").strip()
            if len(t) == 4 and t.isdigit():
                send_and_print(ser_b, f"B:TIME:{t}")

        elif choice == "":
            continue
        else:
            print(f"  未知命令: {choice}")


# ==================== 主入口 ====================

def main():
    global _csv_logger

    parser = argparse.ArgumentParser(description="Arduino 智能家居双板测试工具 v2.0")
    parser.add_argument("--port-a", help="Module_A COM 口")
    parser.add_argument("--port-b", help="Module_B COM 口")
    parser.add_argument("--auto-test", action="store_true", help="自动运行测试后退出")
    parser.add_argument("--demo", action="store_true", help="运行交互演示模式")
    parser.add_argument("--log", help="CSV 日志文件路径 (如 sensor_log.csv)")
    args = parser.parse_args()

    print("=" * 60)
    print("  Arduino 智能家居双板测试工具 v2.0")
    print("=" * 60)

    # 初始化 CSV 日志
    csv_logger = None
    if args.log:
        csv_logger = CsvLogger(args.log)
        csv_logger.open()
        print(f"\n[日志] 传感器数据将记录到: {args.log}")

    # 检测/连接端口
    print("\n[扫描] 正在查找串口设备...")
    available = list_ports()
    if not available:
        print("  [ERROR] 未找到任何串口设备!")
        sys.exit(1)

    for dev, desc, hwid in available:
        print(f"  {dev}  {desc}")

    # 确定端口
    port_a = args.port_a
    port_b = args.port_b

    # 智能判断: 如果用户只指定了一个端口，不要自动去寻找另一个
    user_specified_a = bool(args.port_a)
    user_specified_b = bool(args.port_b)
    both_specified = user_specified_a and user_specified_b

    if not port_a and not port_b:
        # 用户未指定任何端口 → 尝试全部自动发现
        print("\n[扫描] 正在自动识别模块...")

        print("  寻找 Module_A (传感器板)...")
        port_a = identify_a_port(BAUD_A, AUTO_DETECT_TIMEOUT)
        if port_a:
            print(f"  找到 Module_A: {port_a}")
        else:
            print("  [WARN] 未找到 Module_A，将仅使用 B 板")

        print("  寻找 Module_B (执行板)...")
        port_b = identify_b_port(BAUD_B, AUTO_DETECT_TIMEOUT)
        if port_b:
            print(f"  找到 Module_B: {port_b}")
        else:
            print("  [WARN] 未找到 Module_B，将仅使用 A 板")
    elif not both_specified:
        # 用户仅指定了一个端口 → 不自动探索另一个
        if not port_a:
            print(f"\n[提示] 仅连接了 Module_B ({port_b})，Module_A 不可用")
        else:
            print(f"\n[提示] 仅连接了 Module_A ({port_a})，Module_B 不可用")

    # 连接
    ser_a = None
    ser_b = None

    if port_a:
        ser_a = connect_board(port_a, BAUD_A, "A")
    if port_b:
        ser_b = connect_board(port_b, BAUD_B, "B")

    if not ser_a and not ser_b:
        print("\n  [ERROR] 没有成功连接任何模块!")
        if csv_logger:
            csv_logger.close()
        sys.exit(1)

    try:
        if args.auto_test:
            test_all(ser_a, ser_b)
        else:
            interactive_menu(ser_a, ser_b, csv_logger)
    except KeyboardInterrupt:
        print("\n\n  用户中断。")
    finally:
        if ser_a:
            try:
                ser_a.close()
            except Exception:
                pass
        if ser_b:
            try:
                ser_b.close()
            except Exception:
                pass
        if csv_logger:
            csv_logger.close()
            print(f"  日志已保存到: {args.log}")
        print("  串口已关闭。")


if __name__ == "__main__":
    main()
