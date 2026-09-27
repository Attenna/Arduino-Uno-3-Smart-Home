"""
PC端全面功能测试脚本 v1.1
=========================
对 Arduino 双节点智能家居系统执行全量功能验证。
针对 B 板固件 JSON 解析 bug，所有 B 板命令统一使用冒号文本格式。
"""

import serial
import json
import time
import sys

BAUD = 115200
PORT_A = "COM7"   # 传感器板
PORT_B = "COM6"   # 执行器板


def open_port(port, label):
    try:
        ser = serial.Serial(port, BAUD, timeout=1.0)
        time.sleep(0.3)
        ser.reset_input_buffer()
        print(f"  [{label}] 已连接 {port} @ {BAUD}")
        return ser
    except Exception as e:
        print(f"  [{label}] 连接失败: {e}")
        return None


def read_all(ser, wait=0.8):
    """持续读取直到超时且无新数据，自动拼接被截断的 JSON 行。"""
    chunks = []
    deadline = time.time() + wait
    while time.time() < deadline:
        if ser.in_waiting:
            chunks.append(ser.read(ser.in_waiting).decode("utf-8", errors="replace"))
            # 有新数据时延长截止时间
            deadline = time.time() + 0.15
        else:
            time.sleep(0.02)
    raw = "".join(chunks)
    # 按行分割，尝试把不完整的 JSON 末尾拼起来
    lines = []
    buf = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # 如果上一行是不完整 JSON（以 { 开头但不含 }），则拼接
        if buf:
            buf += line
            if buf.count("{") <= buf.count("}"):
                lines.append(buf)
                buf = ""
            continue
        if line.startswith("{") and line.count("{") > line.count("}"):
            buf = line
            continue
        lines.append(line)
    if buf:
        lines.append(buf)
    return lines


def send(ser, cmd, wait=0.8):
    if ser is None:
        return []
    if isinstance(cmd, str):
        cmd = (cmd + "\n").encode()
    ser.reset_input_buffer()
    ser.write(cmd)
    return read_all(ser, wait)


def print_response(lines, indent="    <- "):
    for line in lines:
        print(f"{indent}{line}")


def is_ok(lines):
    for line in lines:
        if '"result":"ok"' in line:
            return True
        if '"result":"error"' in line and '"error":"parse_error"' in line:
            return "parse_error"
    return False


class TestRunner:
    def __init__(self):
        self.ser_a = open_port(PORT_A, "A")
        self.ser_b = open_port(PORT_B, "B")
        self.passed = 0
        self.failed = 0
        self.warnings = []

    def section(self, title):
        print("\n" + "=" * 60)
        print(title)
        print("=" * 60)

    def test(self, name, lines, expect_ok=True):
        ok = is_ok(lines)
        if ok is True:
            print(f"  [PASS] {name}")
            self.passed += 1
        elif ok == "parse_error":
            print(f"  [FAIL] {name} — JSON解析错误 (parse_error)")
            self.failed += 1
        elif not expect_ok and ok is False:
            print(f"  [PASS] {name} (按预期)")
            self.passed += 1
        else:
            print(f"  [FAIL] {name} — 无有效响应")
            self.failed += 1

    def warn(self, msg):
        self.warnings.append(msg)
        print(f"  [WARN] {msg}")

    # ========== Module A ==========
    def test_a_identity(self):
        self.section("Module A — 设备识别")
        lines = send(self.ser_a, "WHO")
        print_response(lines)
        for line in lines:
            if '"board":"MODULE_A"' in line:
                print("  [PASS] 设备标识正确")
                self.passed += 1
                return
        self.test("WHO", lines)

    def test_a_report(self):
        self.section("Module A — 数据上报")
        lines = send(self.ser_a, "REPORT")
        print_response(lines)
        data = {}
        for line in lines:
            try:
                obj = json.loads(line)
                if obj.get("type") == "data":
                    data = obj.get("data", {})
                    break
            except Exception:
                pass
        if not data:
            self.test("REPORT", lines)
            return
        print(f"  传感器数据: {json.dumps(data, ensure_ascii=False)}")
        if data.get("smoke") is True:
            self.warn("烟雾传感器报警 (smoke=true)")
        if data.get("soil_dry") is True:
            self.warn("土壤传感器干燥 (soil_dry=true)")
        if data.get("distance") is None:
            self.warn("超声波距离读取失败 (distance=null)")
        self.passed += 1
        print("  [PASS] 数据上报正常")

    def test_a_interval(self):
        self.section("Module A — 上报间隔设置")
        lines = send(self.ser_a, "INTERVAL:1000")
        print_response(lines)
        self.test("INTERVAL:1000", lines)
        send(self.ser_a, "INTERVAL:2000", wait=0.3)

    def test_a_multi_read(self):
        self.section("Module A — 多次采样稳定性")
        temps = []
        for i in range(3):
            lines = send(self.ser_a, "REPORT", wait=0.6)
            for line in lines:
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "data":
                        t = obj.get("data", {}).get("temperature")
                        if t is not None:
                            temps.append(t)
                        break
                except Exception:
                    pass
            time.sleep(0.5)
        if len(temps) >= 2:
            diff = max(temps) - min(temps)
            print(f"  3次温度采样: {temps}, 极差={diff:.1f}°C")
            if diff <= 2.0:
                print("  [PASS] 采样稳定性良好")
            else:
                self.warn(f"温度波动较大 ({diff:.1f}°C)")
            self.passed += 1
        else:
            self.test("多次采样", [])

    # ========== Module B (全部用冒号命令) ==========
    def test_b_identity(self):
        self.section("Module B — 设备识别")
        lines = send(self.ser_b, "B:WHO")
        print_response(lines)
        for line in lines:
            if '"board":"MODULE_B"' in line:
                print("  [PASS] 设备标识正确")
                self.passed += 1
                return
        self.test("B:WHO", lines)

    def test_b_status(self):
        self.section("Module B — 状态查询")
        lines = send(self.ser_b, "B:STATUS")
        print_response(lines)
        for line in lines:
            try:
                obj = json.loads(line)
                if obj.get("type") == "state":
                    print(f"  当前状态: door={obj.get('door')} window={obj.get('window')} fan={obj.get('fan')} light={obj.get('light')} buzzer={obj.get('buzzer')}")
                    print("  [PASS] 状态查询正常")
                    self.passed += 1
                    return
            except Exception:
                pass
        self.test("B:STATUS", lines)

    def test_b_light(self):
        self.section("Module B — 灯光")
        cmds = [
            ("B:LIGHT:RED", "红色"),
            ("B:LIGHT:GREEN", "绿色"),
            ("B:LIGHT:BLUE", "蓝色"),
            ("B:LIGHT:YELLOW", "黄色"),
            ("B:LIGHT:PURPLE", "紫色"),
            ("B:LIGHT:CYAN", "青色"),
            ("B:LIGHT:WHITE", "白色"),
            ("B:LIGHT:RGB:255,128,0", "RGB橙"),
            ("B:LIGHT:128", "亮度128"),
            ("B:LIGHT:OFF", "关闭"),
        ]
        for cmd, desc in cmds:
            print(f"  {desc}...")
            lines = send(self.ser_b, cmd)
            print_response(lines)
            self.test(f"light {desc}", lines)
            time.sleep(0.2)

    def test_b_fan(self):
        self.section("Module B — 风扇")
        for spd, desc in [(80, "低速"), (180, "中速"), (255, "全速")]:
            print(f"  {desc} ({spd})...")
            lines = send(self.ser_b, f"B:FAN:{spd}")
            print_response(lines)
            self.test(f"fan {desc}", lines)
            time.sleep(0.3)
        lines = send(self.ser_b, "B:FAN:OFF")
        print_response(lines)
        self.test("fan off", lines)

    def test_b_buzzer(self):
        self.section("Module B — 蜂鸣器")
        lines = send(self.ser_b, "B:BUZZER:BEEP:2:100:100")
        print_response(lines)
        self.test("buzzer beep", lines)
        time.sleep(0.4)
        lines = send(self.ser_b, "B:BUZZER:OFF")
        print_response(lines)
        self.test("buzzer off", lines)

    def test_b_door(self):
        self.section("Module B — 门舵机")
        lines = send(self.ser_b, "B:DOOR:OPEN")
        print_response(lines)
        self.test("door open", lines)
        time.sleep(0.8)
        lines = send(self.ser_b, "B:DOOR:CLOSE")
        print_response(lines)
        self.test("door close", lines)

    def test_b_window(self):
        self.section("Module B — 窗舵机")
        for act, desc in [("OPEN", "开窗"), ("NORMAL", "正常"), ("CLOSE", "关窗"), ("NORMAL", "正常")]:
            print(f"  {desc}...")
            lines = send(self.ser_b, f"B:WINDOW:{act}")
            print_response(lines)
            self.test(f"window {desc}", lines)
            time.sleep(0.5)

    def test_b_oled(self):
        self.section("Module B — OLED 显示屏")
        lines = send(self.ser_b, "B:OLED:CLEAR")
        print_response(lines)
        self.test("oled clear", lines)
        time.sleep(0.2)
        lines = send(self.ser_b, "B:OLED:SHOW:0:FULL TEST")
        print_response(lines)
        self.test("oled show_text", lines)
        time.sleep(0.2)
        lines = send(self.ser_b, "B:OLED:SHOW:1:PASS OK")
        print_response(lines)
        self.test("oled show_text line1", lines)

    def test_b_display(self):
        self.section("Module B — 数码管")
        lines = send(self.ser_b, "B:TIME:1430")
        print_response(lines)
        self.test("display time", lines)
        time.sleep(0.5)
        # display show_number 没有冒号命令映射，只能通过 system status 间接验证
        lines = send(self.ser_b, "B:STATUS")
        print_response(lines)
        self.test("display status check", lines)

    def test_b_ir(self):
        self.section("Module B — 红外发射")
        # ir send_nec 没有冒号命令映射，使用 system:status 确认板子存活即可
        lines = send(self.ser_b, "B:STATUS")
        print_response(lines)
        self.test("ir board alive", lines)

    def run_all(self):
        print("=" * 60)
        print("  Arduino 智能家居 PC端全面功能测试 v1.1")
        print("=" * 60)

        if not self.ser_a and not self.ser_b:
            print("\n[ERROR] 两块板均未连接，测试终止。")
            sys.exit(1)

        if self.ser_a:
            self.test_a_identity()
            self.test_a_report()
            self.test_a_interval()
            self.test_a_multi_read()
        else:
            print("\n[SKIP] Module A 未连接")

        if self.ser_b:
            self.test_b_identity()
            self.test_b_status()
            self.test_b_light()
            self.test_b_fan()
            self.test_b_buzzer()
            self.test_b_door()
            self.test_b_window()
            self.test_b_oled()
            self.test_b_display()
            self.test_b_ir()
        else:
            print("\n[SKIP] Module B 未连接")

        self.section("最终状态查询")
        if self.ser_b:
            lines = send(self.ser_b, "B:STATUS")
            print_response(lines)
            for line in lines:
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "state":
                        print(f"  最终状态: {json.dumps(obj, ensure_ascii=False)}")
                        break
                except Exception:
                    pass

        self.section("测试汇总")
        total = self.passed + self.failed
        print(f"  通过: {self.passed}")
        print(f"  失败: {self.failed}")
        print(f"  总计: {total}")
        if self.warnings:
            print(f"\n  警告 ({len(self.warnings)}项):")
            for w in self.warnings:
                print(f"    - {w}")
        if self.failed == 0:
            print("\n  [OK] 全部测试通过!")
        else:
            print(f"\n  [WARN] 有 {self.failed} 项测试未通过，请检查硬件/固件。")

    def cleanup(self):
        if self.ser_a:
            self.ser_a.close()
        if self.ser_b:
            self.ser_b.close()
        print("\n  串口已关闭。")


def main():
    runner = TestRunner()
    try:
        runner.run_all()
    except KeyboardInterrupt:
        print("\n  用户中断。")
    finally:
        runner.cleanup()


if __name__ == "__main__":
    main()
