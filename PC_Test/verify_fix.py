"""固件修复验证：JSON 命令 + 状态截断 + 冒号命令回归"""
import serial, json, time, sys

PORT_B = "COM6"
BAUD = 115200

passed = failed = 0

def send(ser, cmd, wait=0.8):
    ser.reset_input_buffer()
    ser.write((cmd + "\n").encode())
    chunks, deadline = [], time.time() + wait
    while time.time() < deadline:
        if ser.in_waiting:
            chunks.append(ser.read(ser.in_waiting).decode("utf-8", errors="replace"))
            deadline = time.time() + 0.15
        else:
            time.sleep(0.02)
    raw = "".join(chunks)
    lines, buf = [], ""
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if buf:
            buf += line
            if buf.count("{") <= buf.count("}"):
                lines.append(buf); buf = ""
            continue
        if line.startswith("{") and line.count("{") > line.count("}"):
            buf = line; continue
        lines.append(line)
    if buf:
        lines.append(buf)
    return lines

def test(name, lines, expect="ok"):
    global passed, failed
    for line in lines:
        print(f"    <- {line}")
    ok = any('"result":"ok"' in l for l in lines)
    if expect == "ok" and ok:
        print(f"  [PASS] {name}"); passed += 1
    elif expect == "state":
        for l in lines:
            try:
                obj = json.loads(l)
                if obj.get("type") == "state" and "buzzer" in obj:
                    print(f"  [PASS] {name} (完整状态: {l})"); passed += 1; return
            except Exception:
                pass
        print(f"  [FAIL] {name} — 状态JSON不完整"); failed += 1
    elif expect == "ok" and not ok:
        print(f"  [FAIL] {name}"); failed += 1

ser = serial.Serial(PORT_B, BAUD, timeout=1.0)
time.sleep(2)  # 等待复位后 ready
ser.reset_input_buffer()

print("=" * 60)
print("  B板固件修复验证")
print("=" * 60)

print("\n--- JSON 系统命令 ---")
test("system who (JSON)", send(ser, '{"cmd":"system","action":"who"}'))
test("system status (JSON, 验证不截断)", send(ser, '{"cmd":"system","action":"status"}'), expect="state")

print("\n--- JSON 执行器命令 ---")
test("light rgb (JSON)", send(ser, '{"cmd":"light","action":"rgb","r":255,"g":128,"b":0}'))
test("light off (JSON)", send(ser, '{"cmd":"light","action":"off"}'))
test("fan set_speed (JSON)", send(ser, '{"cmd":"fan","action":"set_speed","value":120}'))
test("fan off (JSON)", send(ser, '{"cmd":"fan","action":"off"}'))
test("buzzer beep 缺省参数 (JSON)", send(ser, '{"cmd":"buzzer","action":"beep"}'))
test("door open (JSON)", send(ser, '{"cmd":"door","action":"open"}'))
time.sleep(0.6)
test("door close (JSON)", send(ser, '{"cmd":"door","action":"close"}'))
test("window open (JSON)", send(ser, '{"cmd":"window","action":"open"}'))
time.sleep(0.4)
test("window normal (JSON)", send(ser, '{"cmd":"window","action":"normal"}'))
test("oled show_text (JSON)", send(ser, '{"cmd":"oled","action":"show_text","line":0,"text":"JSON OK"}'))
test("display show_number (JSON)", send(ser, '{"cmd":"display","action":"show_number","value":1234}'))
time.sleep(0.4)
test("display clear (JSON)", send(ser, '{"cmd":"display","action":"clear"}'))
test("ir send_nec (JSON)", send(ser, '{"cmd":"ir","action":"send_nec","code":16712445}'))

print("\n--- 边界兼容 ---")
test("带空格的 JSON", send(ser, '{ "cmd" : "light" , "action" : "blue" }'))
test("light off (JSON)", send(ser, '{"cmd":"light","action":"off"}'))
test("全角标点 JSON", send(ser, '{“cmd”：“light”，“action”：“red”}'))
test("light off", send(ser, '{"cmd":"light","action":"off"}'))

print("\n--- 冒号命令回归 ---")
test("B:WHO", send(ser, "B:WHO"))
test("B:STATUS (验证不截断)", send(ser, "B:STATUS"), expect="state")
test("B:LIGHT:GREEN", send(ser, "B:LIGHT:GREEN"))
test("B:LIGHT:OFF", send(ser, "B:LIGHT:OFF"))
test("B:FAN:OFF", send(ser, "B:FAN:OFF"))

print("\n" + "=" * 60)
print(f"  通过: {passed}  失败: {failed}")
print("  [OK] 修复验证通过!" if failed == 0 else "  [WARN] 仍有失败项")
ser.close()
