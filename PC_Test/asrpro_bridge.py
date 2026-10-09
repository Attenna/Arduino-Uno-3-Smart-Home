"""ASRPRO UART -> authenticated Web gateway. Never opens A/B board ports.

Two wire dialects, ASCII with LF (CRLF tolerated); one request in flight:

  SH1 <request-id> <command-id>
      reply: SH1 <request-id> <command-id> <OK|ERR|TEMP|HUM|TIME> <a> <b>

  SH2 <request-id> <intent> [<name>=<value> ...]
      reply: SH2 <request-id> <intent> <OK|REJECTED|FAILED|TIMEOUT> [<name>=<value> ...]

SH2 intents come from an allow-list loaded at startup (JSON via ASRPRO_INTENTS_CONFIG,
falling back to built-ins). The serial side can never name an arbitrary tool, URL or raw
Arduino frame, nor register new intents; it can only discover them (list_intents). A
repeated request id replays the cached result instead of moving an actuator again.
Temperature/humidity use hundredths; time is hour/minute in UTC+8.
"""
import argparse
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
import re
import time
from typing import Optional
from urllib.request import Request, build_opener, ProxyHandler

LOG = logging.getLogger("asrpro")

# ---- SH1 (legacy numeric commands, kept for already-flashed models) ----
SH1_COMMANDS = {
    1: ("light", {"action": "white", "value": 255}),
    2: ("light", {"action": "off"}),
    3: ("door", {"action": "open"}),
    4: ("window", {"action": "open"}),
    5: ("fan", {"action": "on"}),
    6: ("fan", {"action": "off"}),
}
SH1_REQUEST = re.compile(rb"SH1 ([1-9][0-9]{0,8}) ([1-9])\r?\n")

# ---- SH2 (allow-listed intents) ----
INTENT_NAME = r"[a-z][a-z0-9_]{0,31}"
ARG_NAME = r"[a-z][a-z0-9_]{0,15}"
SH2_REQUEST = re.compile(
    rf"SH2 ([1-9][0-9]{{0,8}}) ({INTENT_NAME})((?: {ARG_NAME}=[A-Za-z0-9_]{{1,15}})*)\r?\n".encode()
)
MAX_FRAME = 127  # bytes, including the terminating LF


@dataclass(frozen=True)
class Arg:
    """Declared argument. Serial input may only carry these shapes, never free text."""
    kind: str                       # "int" | "enum" | "bool"
    required: bool = False
    choices: tuple = ()
    minimum: Optional[int] = None
    maximum: Optional[int] = None


@dataclass(frozen=True)
class Intent:
    tool: Optional[str]             # gateway tool name; None = built-in read-only handler
    arguments: Mapping[str, Arg]
    reader: Optional[str] = None    # built-in handler name when tool is None


def _enum(*choices, required=True):
    return Arg("enum", required=required, choices=choices)


# Built-in registry, used when no config file is given. Only the tools the hardware
# actually exposes (Module A/B); scenarios are added via config, not code.
DEFAULT_INTENTS = {
    "light": Intent("light", {
        "action": _enum("off", "white", "night", "temp", "red", "green", "blue",
                        "yellow", "purple", "cyan", "rgb", "pixels"),
        "value": Arg("int", minimum=0, maximum=255),
        "r": Arg("int", minimum=0, maximum=255),
        "g": Arg("int", minimum=0, maximum=255),
        "b": Arg("int", minimum=0, maximum=255),
        "temp": Arg("int", minimum=2700, maximum=6500),
        "count": Arg("int", minimum=1, maximum=8),
    }),
    "door": Intent("door", {"action": _enum("open", "close")}),
    "window": Intent("window", {"action": _enum("open", "close", "normal")}),
    "fan": Intent("fan", {
        "action": _enum("on", "off", "set_speed"),
        "value": Arg("int", minimum=0, maximum=255),
    }),
    "buzzer": Intent("buzzer", {
        "action": _enum("on", "off", "beep"),
        "count": Arg("int", minimum=1, maximum=100),
        "on_ms": Arg("int", minimum=1, maximum=60000),
        "off_ms": Arg("int", minimum=1, maximum=60000),
    }),
    "ac": Intent("ac", {
        "power": Arg("bool"),
        "mode": _enum("auto", "cool", "heat", "dry", "fan", required=False),
        "temperature": Arg("int", minimum=17, maximum=30),
        "fan": _enum("auto", "low", "mid", "high", required=False),
        "swing_ud": Arg("bool"),
        "swing_lr": Arg("bool"),
    }),
    "status": Intent(None, {}, "status"),                  # read-only /api/status snapshot
    "list_intents": Intent(None, {}, "list_intents"),      # read-only discovery
}

CONFIG_ENV = "ASRPRO_INTENTS_CONFIG"
READERS = ("status", "list_intents")


def load_intents(path=None):
    """Load the allow-list from JSON; any problem falls back to the built-in registry."""
    path = path or os.environ.get(CONFIG_ENV)
    if not path:
        return DEFAULT_INTENTS
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return _parse_intents(json.load(handle))
    except Exception as exc:
        # Never log file contents; the registry must stay an explicit allow-list.
        LOG.warning("Intent config %s unusable (%s); using built-in registry",
                    path, type(exc).__name__)
        return DEFAULT_INTENTS


def _parse_intents(document):
    entries = document["intents"]
    if not isinstance(entries, dict) or not entries:
        raise ValueError("intents must be a non-empty object")
    intents = {}
    for name, entry in entries.items():
        if not re.fullmatch(INTENT_NAME, name):
            raise ValueError("bad intent name")
        tool, reader = entry.get("tool"), entry.get("reader")
        if (tool is None) == (reader is None):
            raise ValueError("intent needs exactly one of tool/reader")
        if tool is not None and not re.fullmatch(ARG_NAME, tool):
            raise ValueError("bad tool name")
        if reader is not None and reader not in READERS:
            raise ValueError("bad reader")
        arguments = {}
        for arg_name, arg in entry.get("arguments", {}).items():
            if not re.fullmatch(ARG_NAME, arg_name):
                raise ValueError("bad argument name")
            declared = Arg(kind=arg["kind"], required=bool(arg.get("required", False)),
                           choices=tuple(arg.get("choices", ())),
                           minimum=arg.get("minimum"), maximum=arg.get("maximum"))
            if declared.kind not in ("int", "enum", "bool") \
                    or (declared.kind == "enum" and not declared.choices):
                raise ValueError("bad argument definition")
            arguments[arg_name] = declared
        intents[name] = Intent(tool, arguments, reader)
    return intents


CODE_OK = "OK"
CODE_REJECTED = "REJECTED"
CODE_FAILED = "FAILED"
CODE_TIMEOUT = "TIMEOUT"
# "BUSY" is reserved for a future asynchronous dispatcher; the synchronous serial loop
# already enforces one request in flight, so it is never emitted today.


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
    def __init__(self, gateway, now=None, cache_size=64, intents=None):
        self.gateway = gateway
        self.now = now or (lambda: datetime.now(timezone(timedelta(hours=8))))
        self.intents = dict(intents if intents is not None else DEFAULT_INTENTS)
        self._results = OrderedDict()   # request id -> (intent/command key, reply bytes)
        self._cache_size = cache_size

    def handle(self, line):
        if line.startswith(b"SH1 "):
            return self._handle_sh1(line)
        if line.startswith(b"SH2 "):
            return self._handle_sh2(line)
        return None

    # ---- SH1 legacy ----
    def _handle_sh1(self, line):
        match = SH1_REQUEST.fullmatch(line)
        if not match:
            return None
        rid, cmd = map(int, match.groups())
        kind, a, b = "ERR", 0, 0
        try:
            if cmd in SH1_COMMANDS:
                name, arguments = SH1_COMMANDS[cmd]
                if self._call_tool(name, arguments):
                    kind = "OK"
            elif cmd in (7, 8):
                field = "temperature" if cmd == 7 else "humidity"
                value = self._read_status().get(field)
                if value is not None:
                    kind = "TEMP" if cmd == 7 else "HUM"
                    a = value
            else:
                now = self.now()
                kind, a, b = "TIME", now.hour, now.minute
        except Exception as exc:
            # Don't log URL/HTTP exception details, credentials or response bodies.
            LOG.warning("Command %d failed (%s); not retried", cmd, type(exc).__name__)
        return f"SH1 {rid} {cmd} {kind} {a} {b}\n".encode("ascii")

    # ---- SH2 allow-listed intents ----
    def _handle_sh2(self, line):
        match = SH2_REQUEST.fullmatch(line)
        if not match:
            return None
        rid = int(match.group(1))
        intent = match.group(2).decode("ascii")
        cached = self._results.get(rid)
        if cached is not None:
            # A retransmit replays the result; a reused id with other content is refused.
            return cached[1] if cached[0] == intent else self._reply(rid, intent, CODE_REJECTED)
        spec = self.intents.get(intent)
        if spec is None:
            return self._remember(rid, intent, self._reply(rid, intent, CODE_REJECTED))
        arguments = self._validate(spec, match.group(3).decode("ascii"))
        if arguments is None:
            return self._remember(rid, intent, self._reply(rid, intent, CODE_REJECTED))
        code, params = self._execute(spec, arguments)
        return self._remember(rid, intent, self._reply_fitting(rid, intent, code, params))

    def _execute(self, spec, arguments):
        try:
            if spec.reader == "list_intents":
                return CODE_OK, {"count": len(self.intents),
                                 "intents": ",".join(sorted(self.intents))}
            if spec.tool is None:
                return CODE_OK, self._read_status()
            if self._call_tool(spec.tool, arguments):
                return CODE_OK, {}
            return CODE_FAILED, {}
        except TimeoutError:
            # Result unknown: the actuator may already have moved. Never auto-retry.
            return CODE_TIMEOUT, {}
        except Exception as exc:
            LOG.warning("Intent failed (%s); not retried", type(exc).__name__)
            return CODE_FAILED, {}

    def _call_tool(self, name, arguments):
        result = self.gateway.request("/api/hardware/tool", {
            "name": name, "arguments": arguments, "source": "voice", "timeout": 5})
        return isinstance(result, Mapping) and result.get("ok") is True

    def _read_status(self):
        """Read-only fields; invalid/offline samples are omitted rather than faked."""
        status = self.gateway.request("/api/status")
        fields = {}
        if not isinstance(status, Mapping):
            return fields
        fields["sensor_online"] = 1 if status.get("sensor_online") is True else 0
        for key, low, high in (("temperature", -40, 80), ("humidity", 0, 100)):
            value = status.get(key)
            if (status.get("sensor_online") is True
                    and type(value) in (int, float) and math.isfinite(value)
                    and low <= value <= high):
                fields[key] = round(value * 100)
        return fields

    @staticmethod
    def _validate(spec, raw):
        arguments, seen = {}, set()
        for token in raw.split():
            name, _, value = token.partition("=")
            if name in seen:
                return None             # duplicate parameter
            seen.add(name)
            arg = spec.arguments.get(name)
            if arg is None:
                return None             # unknown parameter
            parsed = Bridge._coerce(arg, value)
            if parsed is None:
                return None
            arguments[name] = parsed
        if any(arg.required and name not in arguments
               for name, arg in spec.arguments.items()):
            return None
        return arguments

    @staticmethod
    def _coerce(arg, value):
        if arg.kind == "enum":
            return value if value in arg.choices else None
        if arg.kind == "bool":
            if value in ("1", "true"):
                return True
            return False if value in ("0", "false") else None
        if arg.kind == "int" and re.fullmatch(r"-?[0-9]{1,6}", value):
            number = int(value)
            if arg.minimum is not None and number < arg.minimum:
                return None
            if arg.maximum is not None and number > arg.maximum:
                return None
            return number
        return None

    @staticmethod
    def _reply(rid, intent, code, params=None):
        frame = f"SH2 {rid} {intent} {code}"
        for name in sorted(params or {}):
            frame += f" {name}={params[name]}"
        return (frame + "\n").encode("ascii")

    @classmethod
    def _reply_fitting(cls, rid, intent, code, params):
        """A large registry can overflow one frame; keep the count, drop the name list."""
        reply = cls._reply(rid, intent, code, params)
        if len(reply) > MAX_FRAME and "intents" in params:
            dropped = {key: value for key, value in params.items() if key != "intents"}
            reply = cls._reply(rid, intent, code, dropped)
        return reply

    def _remember(self, rid, intent, reply):
        self._results[rid] = (intent, reply)
        self._results.move_to_end(rid)
        while len(self._results) > self._cache_size:
            self._results.popitem(last=False)
        return reply


class Lines:
    """Keep partial lines across read timeouts; discard whole oversized frames."""
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
                if len(self.buffer) >= MAX_FRAME:
                    self.buffer.clear()
                    self.dropping = True
                else:
                    self.buffer.append(byte)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=os.environ.get("ASRPRO_PORT"))
    parser.add_argument("--gateway", default="http://127.0.0.1:5000")
    parser.add_argument("--intents", default=os.environ.get(CONFIG_ENV))
    args = parser.parse_args()
    if not args.port:
        parser.error("Set ASRPRO_PORT to the dedicated ASRPRO USB serial device")
    bridge = Bridge(Gateway(args.gateway, os.environ.get("SMART_HOME_SERVICE_TOKEN", "")),
                    intents=load_intents(args.intents))
    import serial
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            with serial.Serial(args.port, 115200, timeout=0.1,
                               write_timeout=1, exclusive=True) as port:
                port.reset_input_buffer()
                lines = Lines()
                LOG.info("ASRPRO connected")
                while True:
                    frames = lines.feed(port.read(port.in_waiting or 1))
                    # Firmware permits one in-flight command. Never execute a backlog.
                    if len(frames) != 1:
                        continue
                    reply = bridge.handle(frames[0])
                    if reply is not None:
                        port.write(reply)
        except (serial.SerialException, OSError) as exc:
            LOG.warning("ASRPRO disconnected (%s)", type(exc).__name__)
            time.sleep(2)


if __name__ == "__main__":
    main()
