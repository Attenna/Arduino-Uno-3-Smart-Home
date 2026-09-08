"""Sensor Gateway — 读取 Module A 串口 JSON，发布到 MQTT。

职责：协议转换（Serial -> MQTT），不做任何业务决策。
"""
import json
import os
import sys

import paho.mqtt.client as mqtt
import serial

SERIAL_PORT = os.environ.get("SENSOR_PORT", "/dev/ttyUSB0")
BAUD = int(os.environ.get("BAUD", "115200"))
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

TOPIC_DATA = "smarthome/sensor/data"
TOPIC_EVENT = "smarthome/sensor/event"


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD, timeout=1)
    except serial.SerialException as exc:
        print(f"[sensor_gateway] 无法打开串口 {SERIAL_PORT}: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[sensor_gateway] 监听 {SERIAL_PORT} @ {BAUD} -> MQTT {MQTT_HOST}:{MQTT_PORT}")

    try:
        while True:
            line = ser.readline()
            if not line:
                continue
            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"[sensor_gateway] 非 JSON 行，忽略: {line!r}", file=sys.stderr)
                continue

            msg_type = msg.get("type")
            if msg_type == "data":
                client.publish(TOPIC_DATA, line)
            elif msg_type == "event":
                client.publish(TOPIC_EVENT, line)
            else:
                print(f"[sensor_gateway] 其它消息: {line!r}")

    except KeyboardInterrupt:
        print("\n[sensor_gateway] 退出")
    finally:
        ser.close()
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
