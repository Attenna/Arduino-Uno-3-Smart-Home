"""ASRPRO UART -> authenticated Web gateway. Never opens A/B board ports.

Wire format (ASCII, LF): SH1 <request-id> <command-id>
Reply: SH1 <request-id> <command-id> <OK|ERR|TEMP|HUM|TIME> <a> <b>
Temperature/humidity use hundredths; time is hour/minute in UTC+8.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
import re
import time
from urllib.request import Request, build_opener, ProxyHandler

LOG = logging.getLogger("asrpro")
COMMANDS = {
    1: ("light", {"action": "white", "value": 255}),
    2: ("light", {"action": "off"}),
    3: ("door", {"action": "open"}),
    4: ("window", {"action": "open"}),
    5: ("fan", {"action": "on"}),
    6: ("fan", {"action": "off"}),
}
REQUEST = re.compile(rb"SH1 ([1-9][0-9]{0,8}) ([1-9])\r?\n")
# USB IDs of the ASRPRO development board's onboard CH340 adapter. Discovery is
# restricted to these IDs, so the bridge can never open an A/B Arduino port.
ASRPRO_USB_IDS = frozenset({(0x1A86, 0x7522), (0x1A86, 0x7523)})


def find_asrpro_port(comports=None):
    """Device path of the ASRPRO USB adapter, or None while it is unplugged."""
    if comports is None:
        from serial.tools import list_ports
        comports = list_ports.comports()
    for info in comports:
        if (info.vid, info.pid) in ASRPRO_USB_IDS and info.device:
            return info.device
    return None


def resolve_port(configured, comports=None, exists=os.path.exists):
    """Use the configured device while present, else hot-plug the discovered adapter."""
    if configured and exists(configured):
        return configured
    return find_asrpro_port(comports)


class Gateway:
    def __init__(self, url, token):
        if not token or len(token) < 32:
            raise ValueError("SMART_HOME_SERVICE_TOKEN must contain at least 32 characters")
        self.url, self.token = url.rstrip("/"), token
        # A local service must not pass credentials to an environment HTTP proxy.
        self.opener = build_opener(ProxyHandler({}))

    def request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(self.url + path, data=data, headers={
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json"})
        # No retries: an HTTP timeout may occur after the actuator has moved.
        with self.opener.open(req, timeout=8) as response:
            return json.load(response)


class Bridge:
    def __init__(self, gateway, now=None):
        self.gateway = gateway
        self.now = now or (lambda: datetime.now(timezone(timedelta(hours=8))))

    def handle(self, line):
        match = REQUEST.fullmatch(line)
        if not match:
            return None
        rid, cmd = map(int, match.groups())
        kind, a, b = "ERR", 0, 0
        try:
            if cmd in COMMANDS:
                name, arguments = COMMANDS[cmd]
                result = self.gateway.request("/api/hardware/tool", {
                    "name": name, "arguments": arguments, "source": "voice", "timeout": 5})
                if result.get("ok") is True:
                    kind = "OK"
            elif cmd in (7, 8):
                status = self.gateway.request("/api/status")
                field = "temperature" if cmd == 7 else "humidity"
                value = status.get(field)
                low, high = (-40, 80) if cmd == 7 else (0, 100)
                if (status.get("sensor_online") is True
                        and type(value) in (int, float) and math.isfinite(value)
                        and low <= value <= high):
                    kind = "TEMP" if cmd == 7 else "HUM"
                    a = round(value * 100)
            else:
                now = self.now()
                kind, a, b = "TIME", now.hour, now.minute
        except Exception as exc:
            # Don't log URL/HTTP exception details, credentials or response bodies.
            LOG.warning("Command %d failed (%s); not retried", cmd, type(exc).__name__)
        return f"SH1 {rid} {cmd} {kind} {a} {b}\n".encode("ascii")


class Lines:
    """Keep partial lines across read timeouts; discard entire oversized frames."""
    def __init__(self):
        self.buffer = bytearray()
        self.dropping = False

    def feed(self, data):
        result = []
        for byte in data:
            if byte == 10:
                if not self.dropping:
                    result.append(bytes(self.buffer) + b"\n")
                self.buffer.clear()
                self.dropping = False
            elif not self.dropping:
                if len(self.buffer) >= 63:
                    self.buffer.clear()
                    self.dropping = True
                else:
                    self.buffer.append(byte)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=os.environ.get("ASRPRO_PORT"),
                        help="ASRPRO serial device; auto-detected by USB ID when unset")
    parser.add_argument("--gateway", default="http://127.0.0.1:5000")
    args = parser.parse_args()
    bridge = Bridge(Gateway(args.gateway, os.environ.get("SMART_HOME_SERVICE_TOKEN", "")))
    import serial
    logging.basicConfig(level=logging.INFO)
    waiting = False
    while True:
        device = resolve_port(args.port)
        if device is None:
            if not waiting:
                LOG.info("ASRPRO adapter not present; waiting for hot-plug")
                waiting = True
            time.sleep(2)
            continue
        waiting = False
        try:
            with serial.Serial(device, 115200, timeout=0.1,
                               write_timeout=1, exclusive=True) as port:
                port.reset_input_buffer()
                lines = Lines()
                LOG.info("ASRPRO connected (%s)", device)
                while True:
                    frames = lines.feed(port.read(port.in_waiting or 1))
                    # Firmware permits one in-flight command. Never execute a backlog.
                    if len(frames) != 1:
                        continue
                    reply = bridge.handle(frames[0])
                    if reply is not None:
                        port.write(reply)
        except (serial.SerialException, OSError) as exc:
            LOG.warning("ASRPRO disconnected (%s); waiting for hot-plug", type(exc).__name__)
            time.sleep(2)


if __name__ == "__main__":
    main()
