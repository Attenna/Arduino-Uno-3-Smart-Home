"""
PC_Test 本地联动服务端 — 让 Module A 与 Module B 相互联系（不走 Home Assistant）
================================================================================
角色：串口 ↔ 串口的"协议转换 + 规则联动"，运行在你的 PC 上。

⚠️ DEPRECATED（已过时）：
    本脚本用硬编码的 RULES 列表实现联动，改规则需改 Python 代码。
    请改用 run_automation.py + .auto 脚本（AST 自动化引擎），
    规则与代码解耦，更易读易维护。详见 PC_Test/README.md。

数据流：
    Module A (USB) ──传感器JSON──▶ 本服务 ──规则映射──▶ 命令JSON ──▶ Module B (USB)
                                         │
                                         └──▶ 控制台实时打印两边状态

用法：
    python link_server.py                       # 自动探测串口
    python link_server.py --port-a COM3 --port-b COM4
    python link_server.py --rules none          # 只看不联动（仅打印）

依赖：pip install pyserial
"""
import argparse
import json
import sys
import time

import serial
import serial.tools.list_ports

BAUD = 115200


# ==================== 规则映射（业务联动，全部集中在这里） ====================
#
# 每一条规则：当 A 板的某字段满足条件时，向 B 板发送一条或多条命令。
# 想改联动逻辑，只改这个 RULES 列表即可，无需动其它代码。

RULES = [
    # 1. 烟雾报警 → 蜂鸣器连响 + 红灯 + 开窗
    {
        "name": "烟雾报警",
        "when": {"data.smoke": True},
        "then": [
            {"cmd": "buzzer", "action": "on"},
            {"cmd": "light", "action": "red"},
            {"cmd": "window", "action": "open"},
        ],
    },
    # 2. 烟雾解除 → 关蜂鸣 + 关灯 + 窗恢复
    {
        "name": "烟雾解除",
        "when": {"data.smoke": False},
        "then": [
            {"cmd": "buzzer", "action": "off"},
            {"cmd": "light", "action": "off"},
            {"cmd": "window", "action": "normal"},
        ],
    },
    # 3. 温度过高 → 开风扇
    {
        "name": "温度过高开风扇",
        "when": {"data.temperature": lambda v: v is not None and v > 30},
        "then": [
            {"cmd": "fan", "action": "on"},
        ],
    },
    # 4. 温度回落 → 关风扇
    {
        "name": "温度正常关风扇",
        "when": {"data.temperature": lambda v: v is not None and v <= 30},
        "then": [
            {"cmd": "fan", "action": "off"},
        ],
    },
    # 5. 下雨 → 关窗
    {
        "name": "下雨关窗",
        "when": {"data.rain": True},
        "then": [
            {"cmd": "window", "action": "close"},
        ],
    },
    # 6. 雨停 → 窗恢复
    {
        "name": "雨停开窗",
        "when": {"data.rain": False},
        "then": [
            {"cmd": "window", "action": "normal"},
        ],
    },
    # 7. 检测到人体运动 → 开灯
    {
        "name": "有人开灯",
        "when": {"data.motion": True},
        "then": [
            {"cmd": "light", "action": "white", "value": 255},
        ],
    },
    # 8. 无人 → 关灯
    {
        "name": "无人关灯",
        "when": {"data.motion": False},
        "then": [
            {"cmd": "light", "action": "off"},
        ],
    },
    # 9. RFID 刷卡 → 开门（事件型，只触发一次，不反向）
    {
        "name": "刷卡开门",
        "when": {"event": "rfid"},
        "then": [
            {"cmd": "door", "action": "open"},
        ],
    },
    # 10. 触摸按下 → 蜂鸣一声提示（事件型）
    {
        "name": "触摸提示",
        "when": {"event": "touch", "state": True},
        "then": [
            {"cmd": "buzzer", "action": "beep", "count": 1, "on_ms": 100, "off_ms": 100},
        ],
    },
]


# ==================== 串口工具 ====================

def list_ports():
    return [(p.device, p.description) for p in serial.tools.list_ports.comports()]


def connect(port, label):
    try:
        ser = serial.Serial(port, BAUD, timeout=1)
        time.sleep(0.2)
        ser.reset_input_buffer()
        print(f"  [{label}] 已连接 {port} @ {BAUD}")
        return ser
    except Exception as e:
        print(f"  [{label}] 连接 {port} 失败: {e}")
        return None


def detect_board(expect_substr):
    """在所有串口上发 WHO，返回匹配的端口名（带进度打印，便于定位卡住的串口）。"""
    ports = list_ports()
    for dev, desc in ports:
        print(f"  [探测] 尝试 {dev} ({desc})...", end="", flush=True)
        try:
            ser = serial.Serial(dev, BAUD, timeout=0.3)
            time.sleep(0.1)
            ser.reset_input_buffer()
            ser.write(b'{"cmd":"system","action":"who"}\n')   # B 板
            ser.write(b"WHO\n")                                # A 板
            deadline = time.time() + 0.6
            found = False
            while time.time() < deadline:
                line = ser.readline().decode("utf-8", "replace")
                if expect_substr in line:
                    found = True
                    break
            ser.close()
            if found:
                print(f" 命中!")
                return dev
            print(" 无响应")
        except Exception as e:
            print(f" 跳过 ({e})")
    return None


# ==================== 规则匹配 ====================

def _get(data, path):
    """按 a.b 路径取值；data 可为 dict（data 上报）或扁平 dict（event）。"""
    cur = data
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


def match_rule(rule, msg):
    """判断某条消息是否触发规则。"""
    for path, expect in rule["when"].items():
        actual = _get(msg, path)
        if callable(expect):
            if not expect(actual):
                return False
        else:
            if actual != expect:
                return False
    return True


def send_commands(ser_b, commands, rule_name):
    if ser_b is None:
        print(f"  [联动] {rule_name} 需要 Module_B（未连接），跳过")
        return
    for c in commands:
        line = json.dumps(c) + "\n"
        ser_b.write(line.encode("utf-8"))
        print(f"  [联动] {rule_name} -> {json.dumps(c)}")


# ==================== 主循环 ====================

def main():
    parser = argparse.ArgumentParser(description="Module A <-> Module B 本地联动服务端")
    parser.add_argument("--port-a", help="Module A 串口")
    parser.add_argument("--port-b", help="Module B 串口")
    parser.add_argument("--rules", choices=["on", "none"], default="on",
                        help="on=启用联动规则；none=只打印不联动")
    args = parser.parse_args()

    print("=" * 60)
    print("  Module A <-> Module B 本地联动服务端")
    print("=" * 60)

    port_a = args.port_a
    port_b = args.port_b

    if not port_a and not port_b:
        print("\n[探测] 正在识别模块（请确保串口未被其它程序占用）...")
        print("\n[探测] 寻找 Module_A ...")
        port_a = detect_board('"board":"MODULE_A"')
        if port_a:
            print(f"  => 找到 Module_A: {port_a}\n")
        else:
            print("  => 未找到 Module_A（可手动 --port-a 指定）\n")
        print("[探测] 寻找 Module_B ...")
        port_b = detect_board('"board":"MODULE_B"')
        if port_b:
            print(f"  => 找到 Module_B: {port_b}\n")
        else:
            print("  => 未找到 Module_B（可手动 --port-b 指定）\n")

    ser_a = connect(port_a, "A") if port_a else None
    ser_b = connect(port_b, "B") if port_b else None

    if not ser_a and not ser_b:
        print("[ERROR] 未连接任何模块")
        sys.exit(1)

    print(f"\n[规则] 联动规则: {'启用' if args.rules == 'on' else '关闭（仅打印）'}")
    print(f"[规则] 共 {len(RULES)} 条")
    print("\n监听中... Ctrl+C 退出\n")

    # 边沿去重：对 bool 型周期状态，只在"变化"时触发，避免每 2 秒重复发命令
    last_snapshot = {}

    try:
        while True:
            # 读 A 板
            if ser_a and ser_a.in_waiting:
                raw = ser_a.readline()
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    print(f"[A] (非JSON) {line}")
                    continue

                mtype = msg.get("type")
                if mtype == "ready":
                    print(f"[A] 就绪: {msg.get('board')} {msg.get('version')}")
                elif mtype == "data":
                    data = msg.get("data", {})
                    print(f"[A] 数据 {data}")
                    if args.rules == "on":
                        # 以 data 快照判断每条周期型规则，且只在状态变化时触发
                        for rule in RULES:
                            if "event" in rule["when"]:
                                continue  # 事件型规则跳过
                            if not match_rule(rule, msg):
                                continue
                            name = rule["name"]
                            # 用整条 when 的结果作为去重键
                            if last_snapshot.get(name) is True:
                                continue
                            last_snapshot[name] = True
                            # 对应"反向"规则要复位，便于下次变化再触发
                            send_commands(ser_b, rule["then"], name)
                    # 复位那些已不再满足的规则，使下次变化能再次触发
                    if args.rules == "on":
                        for rule in RULES:
                            if "event" in rule["when"]:
                                continue
                            if not match_rule(rule, msg):
                                last_snapshot[rule["name"]] = False
                elif mtype == "event":
                    print(f"[A] 事件 {msg}")
                    if args.rules == "on":
                        for rule in RULES:
                            if "event" not in rule["when"]:
                                continue
                            if match_rule(rule, msg):
                                send_commands(ser_b, rule["then"], rule["name"])
                else:
                    print(f"[A] {msg}")

            # 读 B 板（响应/状态回显）
            if ser_b and ser_b.in_waiting:
                raw = ser_b.readline()
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    print(f"[B] {line}")

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n退出。")
    finally:
        if ser_a:
            ser_a.close()
        if ser_b:
            ser_b.close()
        print("串口已关闭。")


if __name__ == "__main__":
    main()
