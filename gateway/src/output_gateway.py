"""Output Gateway — 订阅 MQTT 命令下发到 Module B，并回传响应/状态。

职责：协议转换（MQTT <-> Serial），不做任何业务决策。
"""
import json
import os
import sys

import paho.mqtt.client as mqtt
import serial

SERIAL_PORT = os.environ.get("OUTPUT_PORT", "/dev/ttyUSB1")
BAUD = int(os.environ.get("BAUD", "115200"))
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

TOPIC_COMMAND = "smarthome/output/command"
TOPIC_RESPONSE = "smarthome/output/response"
TOPIC_STATE = "smarthome/output/state"

_ser = None
_client = None


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(TOPIC_COMMAND)
    print(f"[output_gateway] 已订阅 {TOPIC_COMMAND}")


def on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8", errors="replace").strip()
    if not payload:
        return
    # 确保以换行结束，Arduino 按行解析
    if not payload.endswith("\n"):
        payload += "\n"
    if _ser is not None:
        _ser.write(payload.encode("utf-8"))
        print(f"[output_gateway] -> B: {payload.strip()}")


def serial_reader():
    """读取 Module B 的响应/状态并发布到 MQTT。"""
    while True:
        line = _ser.readline()
        if not line:
            continue
        line = line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg_type = msg.get("type")
        if msg_type == "response":
            _client.publish(TOPIC_RESPONSE, line)
        elif msg_type == "state":
            _client.publish(TOPIC_STATE, line)
        else:
            print(f"[output_gateway] 其它消息: {line!r}")


def main():
    global _ser, _client

    _client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    _client.on_connect = on_connect
    _client.on_message = on_message
    _client.connect(MQTT_HOST, MQTT_PORT, 60)

    try:
        _ser = serial.Serial(SERIAL_PORT, BAUD, timeout=1)
    except serial.SerialException as exc:
        print(f"[output_gateway] 无法打开串口 {SERIAL_PORT}: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[output_gateway] MQTT {MQTT_HOST}:{MQTT_PORT} -> {SERIAL_PORT} @ {BAUD}")
    _client.loop_start()

    try:
        serial_reader()
    except KeyboardInterrupt:
        print("\n[output_gateway] 退出")
    finally:
        _client.loop_stop()
        _client.disconnect()
        _ser.close()


if __name__ == "__main__":
    main()
