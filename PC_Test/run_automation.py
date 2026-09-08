"""自动化 DSL 运行器 —— 把 AST 引擎接到真实串口。

用法:
    python run_automation.py <脚本.auto> [--port-a COM3] [--port-b COM4] [--interval 2]
    python run_automation.py examples/smoke_alarm.auto   # 自动探测串口

脚本写好后，本程序会:
    1. 解析脚本为 AST
    2. 连接 A/B 板
    3. 周期性读取 A 板数据 -> 更新运行时状态 -> 重新执行脚本
    4. 把脚本里"执行"的动作映射成 B 板命令发送

依赖: pip install pyserial
"""

import argparse
import json
import sys
import threading
import time

import serial
import serial.tools.list_ports

from automation.parser import parse, ParseError
from automation.runtime import Runtime
from oled_carousel import OledCarousel, DEFAULT_PAGES

BAUD = 115200


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
    for dev, desc in list_ports():
        if not any(k in desc.lower() for k in ("arduino", "ch340", "ch9102", "usb-serial", "uno")):
            continue
        print(f"  [探测] {dev} ({desc})...", end="", flush=True)
        try:
            ser = serial.Serial(dev, BAUD, timeout=0.3)
            time.sleep(0.1)
            ser.reset_input_buffer()
            ser.write(b'{"cmd":"system","action":"who"}\n')
            ser.write(b"WHO\n")
            deadline = time.time() + 0.6
            found = False
            while time.time() < deadline:
                line = ser.readline().decode("utf-8", "replace")
                if expect_substr in line:
                    found = True
                    break
            ser.close()
            print(" 命中!" if found else " 无响应")
            if found:
                return dev
        except Exception as e:
            print(f" 跳过 ({e})")
    return None


def main():
    parser = argparse.ArgumentParser(description="自动化 DSL 运行器")
    parser.add_argument("script", help="自动化脚本文件 (.auto)")
    parser.add_argument("--port-a", help="Module A 串口")
    parser.add_argument("--port-b", help="Module B 串口")
    parser.add_argument("--interval", type=float, default=2.0, help="轮询间隔(秒)")
    parser.add_argument("--once", action="store_true", help="只跑一轮就退出")
    parser.add_argument("--carousel", action="store_true",
                        help="启用 OLED 多行轮播显示传感器/执行器状态")
    parser.add_argument("--carousel-interval", type=float, default=3.0,
                        help="OLED 轮播每页停留秒数(默认3秒)")
    args = parser.parse_args()

    # 1. 解析脚本
    with open(args.script, encoding="utf-8") as f:
        text = f.read()
    try:
        program = parse(text)
    except ParseError as e:
        print(f"[解析错误] {e}")
        sys.exit(1)
    print(f"[脚本] 已解析 {len(program.rules)} 条规则")

    # 2. 连接串口
    port_a = args.port_a
    port_b = args.port_b
    if not port_a and not port_b:
        print("\n[探测] 寻找 Module_A...")
        port_a = detect_board('"board":"MODULE_A"')
        print("[探测] 寻找 Module_B...")
        port_b = detect_board('"board":"MODULE_B"')

    ser_a = connect(port_a, "A") if port_a else None
    ser_b = connect(port_b, "B") if port_b else None

    # 3. 构建运行时：操作 -> 发 B 板文本命令
    def emit(cmd):
        # cmd 现在是文本命令字符串（如 "B:LIGHT:RED"）
        if ser_b:
            ser_b.write((cmd + "\n").encode())
        else:
            print(f"  [无B板] {cmd}")

    rt = Runtime(emitter=emit, on_log=print)

    # 4. OLED 轮播（可选）
    carousel = None
    if args.carousel and ser_b:
        def emit_oled(line_no, text):
            emit(f"B:OLED:SHOW:{line_no}:{text}")
        carousel = OledCarousel(
            emitter=emit_oled,
            interval=args.carousel_interval,
            on_log=print,
        )
        print("[OLED] 已启用多行轮播显示")

    b_state = {}  # B 板最新状态
    last_status_poll = 0.0  # 上次查询 B 板状态的时间

    # 5. 主循环：读 A 数据 / B 状态 -> 更新运行时与轮播 -> 执行脚本
    print("\n运行中... Ctrl+C 退出\n")
    try:
        while True:
            # 读 A 板
            if ser_a and ser_a.in_waiting:
                raw = ser_a.readline()
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == "data":
                        rt.update_data(msg.get("data", {}))
                        if carousel:
                            carousel.set_data(rt.data, b_state)
                    elif msg.get("type") == "event":
                        rt.update_event(msg)
                        rt.run(program)
                        continue

            # 读 B 板（状态回显）
            if ser_b and ser_b.in_waiting:
                raw = ser_b.readline()
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    try:
                        bmsg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if bmsg.get("type") == "state":
                        b_state = bmsg
                        if carousel:
                            carousel.set_data(rt.data, b_state)

            # 周期性查询 B 板状态（供轮播/脚本使用）
            now = time.time()
            if carousel and ser_b and now - last_status_poll >= args.interval:
                last_status_poll = now
                emit("B:STATUS")

            # 执行脚本
            rt.run(program)

            # 轮播
            if carousel:
                carousel.tick()

            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n退出。")
    finally:
        for s in (ser_a, ser_b):
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        print("串口已关闭。")


if __name__ == "__main__":
    main()
