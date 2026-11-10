"""Mock smart-home devices and the tool schemas exposed to the LLM.

The real repository talks to an Arduino gateway.  The lab intentionally keeps
the same *semantic* tool surface but executes against an in-memory model, so
every accuracy/latency number is reproducible on a laptop without a serial
port or an Orange Pi.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from .schemas import ToolCall, ToolResult

ROOMS = {
    "living_room": "客厅",
    "bedroom": "卧室",
    "kitchen": "厨房",
}
COLORS = {
    "red": "红色", "blue": "蓝色", "green": "绿色", "white": "白色",
    "yellow": "黄色", "purple": "紫色", "orange": "橙色", "pink": "粉色",
}
SCENES = {
    "home": "回家模式", "away": "离家模式",
    "sleep": "睡觉模式", "movie": "观影模式",
}
AC_MODES = {"cool": "制冷", "heat": "制热", "auto": "自动"}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "control_light",
            "description": "控制灯：开灯、关灯、设置颜色或亮度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off", "set"]},
                    "room": {"type": "string", "enum": list(ROOMS)},
                    "color": {"type": "string", "enum": list(COLORS)},
                    "brightness": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": ["action", "room"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_fan",
            "description": "控制风扇：开关或设置 1-3 档风速。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off", "set"]},
                    "speed": {"type": "integer", "minimum": 0, "maximum": 3},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_door",
            "description": "控制门：打开、关闭、上锁或解锁。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["open", "close", "lock", "unlock"]},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_ac",
            "description": "控制空调：开关、设定温度或模式。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off", "set"]},
                    "temperature": {"type": "integer", "minimum": 16, "maximum": 30},
                    "mode": {"type": "string", "enum": list(AC_MODES)},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_scene",
            "description": "切换全屋场景模式：回家、离家、睡觉、观影。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene": {"type": "string", "enum": list(SCENES)},
                },
                "required": ["scene"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_sensor",
            "description": "查询室内温度、湿度、是否有人或全部传感器。",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string", "enum": ["temperature", "humidity", "motion", "all"]},
                },
                "required": ["metric"],
                "additionalProperties": False,
            },
        },
    },
]

_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def schema_errors(name: str, arguments: dict[str, Any]) -> list[str]:
    """Validate the small JSON-Schema subset used by the six tools."""
    tool = next((t for t in TOOLS if t["function"]["name"] == name), None)
    if tool is None:
        return [f"未知工具 {name}"]
    if not isinstance(arguments, dict):
        return ["工具参数必须是 JSON 对象"]
    schema = tool["function"]["parameters"]
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    errors: list[str] = []
    for key in required:
        if key not in arguments or arguments[key] is None:
            errors.append(f"缺少必填参数 {key}")
    if schema.get("additionalProperties") is False:
        extra = sorted(set(arguments) - set(properties))
        if extra:
            errors.append("未知参数 " + ", ".join(extra))
    for key, value in arguments.items():
        rule = properties.get(key)
        if not isinstance(rule, dict) or value is None:
            continue
        expected = rule.get("type")
        py_type = _TYPE_MAP.get(expected)
        if py_type and (not isinstance(value, py_type)
                        or (expected in ("integer", "number") and isinstance(value, bool))):
            errors.append(f"参数 {key} 类型应为 {expected}")
            continue
        if "enum" in rule and value not in rule["enum"]:
            errors.append(f"参数 {key} 不在允许值中")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in rule and value < rule["minimum"]:
                errors.append(f"参数 {key} 小于最小值 {rule['minimum']}")
            if "maximum" in rule and value > rule["maximum"]:
                errors.append(f"参数 {key} 大于最大值 {rule['maximum']}")
    return errors


class MockHome:
    """Thread-safe in-memory home used by the dialogue demo and the evaluator."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = self._fresh_state()

    @staticmethod
    def _fresh_state() -> dict[str, Any]:
        return {
            "light": {
                "living_room": {"on": False, "color": "white", "brightness": 100},
                "bedroom": {"on": False, "color": "white", "brightness": 100},
                "kitchen": {"on": False, "color": "white", "brightness": 100},
            },
            "fan": {"on": False, "speed": 0},
            "door": {"open": False, "locked": True},
            "ac": {"on": False, "temperature": 26, "mode": "cool"},
            "scene": "home",
            "sensors": {"temperature": 24.5, "humidity": 56.0, "motion": True},
        }

    def reset(self) -> None:
        with self._lock:
            self._state = self._fresh_state()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            import copy
            return copy.deepcopy(self._state)

    def summary(self) -> str:
        """One-line human-readable state for the final answer prompt."""
        s = self.snapshot()
        lights = []
        for room, name in ROOMS.items():
            light = s["light"][room]
            if light["on"]:
                lights.append(f"{name}灯({COLORS.get(light['color'], light['color'])}/{light['brightness']}%)")
        light_text = "、".join(lights) if lights else "全部关闭"
        fan = s["fan"]
        fan_text = f"{fan['speed']}档" if fan["on"] else "关闭"
        door = "开" if s["door"]["open"] else "关"
        door_text = door + ("/已上锁" if s["door"]["locked"] else "/未上锁")
        ac = s["ac"]
        ac_text = (f"{ac['temperature']}℃/{AC_MODES.get(ac['mode'], ac['mode'])}"
                   if ac["on"] else "关闭")
        return (f"灯：{light_text}；风扇：{fan_text}；门：{door_text}；"
                f"空调：{ac_text}；场景：{SCENES.get(s['scene'], s['scene'])}")

    def execute(self, call: ToolCall) -> ToolResult:
        started = time.perf_counter()
        with self._lock:
            errors = schema_errors(call.name, call.arguments)
            if errors:
                return ToolResult(call.name, call.arguments, False, "；".join(errors),
                                  latency_ms=(time.perf_counter() - started) * 1000)
            handler = getattr(self, f"_do_{call.name}", None)
            if handler is None:
                return ToolResult(call.name, call.arguments, False, f"未实现工具 {call.name}",
                                  latency_ms=(time.perf_counter() - started) * 1000)
            ok, text, data = handler(**call.arguments)
            result = ToolResult(call.name, call.arguments, ok, text, data,
                                latency_ms=(time.perf_counter() - started) * 1000)
            return result

    # ── handlers ─────────────────────────────────────────────────────
    def _do_control_light(self, action: str, room: str, color: str | None = None,
                          brightness: int | None = None) -> tuple[bool, str, dict]:
        light = self._state["light"][room]
        name = ROOMS[room]
        if action == "on":
            light["on"] = True
            return True, f"{name}灯已打开", {"room": room, "on": True}
        if action == "off":
            light["on"] = False
            return True, f"{name}灯已关闭", {"room": room, "on": False}
        if color is not None:
            light["on"] = True
            light["color"] = color
        if brightness is not None:
            light["on"] = brightness > 0
            light["brightness"] = brightness
        bits = []
        if color is not None:
            bits.append(COLORS.get(color, color))
        if brightness is not None:
            bits.append(f"{brightness}%")
        if not bits:
            light["on"] = True
            bits.append("打开")
        return True, f"{name}灯已设为" + "、".join(bits), {"room": room, **light}

    def _do_control_fan(self, action: str, speed: int | None = None) -> tuple[bool, str, dict]:
        fan = self._state["fan"]
        if action == "off":
            fan["on"], fan["speed"] = False, 0
            return True, "风扇已关闭", dict(fan)
        if action == "on":
            fan["on"] = True
            fan["speed"] = fan["speed"] or 1
            return True, f"风扇已打开，{fan['speed']}档", dict(fan)
        if speed is None:
            fan["on"] = True
            return True, "风扇已打开", dict(fan)
        fan["speed"] = speed
        fan["on"] = speed > 0
        return True, ("风扇已关闭" if speed == 0 else f"风扇已调到{speed}档"), dict(fan)

    def _do_control_door(self, action: str) -> tuple[bool, str, dict]:
        door = self._state["door"]
        if action == "open":
            if door["locked"]:
                return False, "门已上锁，请先解锁", dict(door)
            door["open"] = True
            return True, "门已打开", dict(door)
        if action == "close":
            door["open"] = False
            return True, "门已关闭", dict(door)
        if action == "lock":
            door["open"] = False
            door["locked"] = True
            return True, "门已上锁", dict(door)
        door["locked"] = False
        return True, "门已解锁", dict(door)

    def _do_control_ac(self, action: str, temperature: int | None = None,
                       mode: str | None = None) -> tuple[bool, str, dict]:
        ac = self._state["ac"]
        if action == "off":
            ac["on"] = False
            return True, "空调已关闭", dict(ac)
        ac["on"] = True
        if temperature is not None:
            ac["temperature"] = temperature
        if mode is not None:
            ac["mode"] = mode
        bits = [f"{ac['temperature']}℃", AC_MODES.get(ac["mode"], ac["mode"])]
        return True, "空调已打开，" + "/".join(bits), dict(ac)

    def _do_set_scene(self, scene: str) -> tuple[bool, str, dict]:
        self._state["scene"] = scene
        if scene == "away":
            for light in self._state["light"].values():
                light["on"] = False
            self._state["fan"].update(on=False, speed=0)
            self._state["ac"]["on"] = False
            self._state["door"].update(open=False, locked=True)
        elif scene == "sleep":
            for room, light in self._state["light"].items():
                light["on"] = room == "bedroom"
                if light["on"]:
                    light["brightness"] = 20
                    light["color"] = "yellow"
            self._state["fan"].update(on=True, speed=1)
            self._state["ac"].update(on=True, temperature=26, mode="cool")
        elif scene == "movie":
            self._state["light"]["living_room"].update(on=True, color="purple", brightness=15)
            self._state["ac"].update(on=True, temperature=24, mode="cool")
        elif scene == "home":
            self._state["light"]["living_room"].update(on=True, color="white", brightness=80)
            self._state["door"].update(open=False, locked=False)
        return True, f"已切换到{SCENES[scene]}", {"scene": scene}

    def _do_query_sensor(self, metric: str) -> tuple[bool, str, dict]:
        sensors = self._state["sensors"]
        if metric == "temperature":
            return True, f"室内温度 {sensors['temperature']}℃", {"temperature": sensors["temperature"]}
        if metric == "humidity":
            return True, f"室内湿度 {sensors['humidity']:.0f}%", {"humidity": sensors["humidity"]}
        if metric == "motion":
            return (True, ("检测到有人" if sensors["motion"] else "没有检测到人"),
                    {"motion": sensors["motion"]})
        return True, (f"温度 {sensors['temperature']}℃，湿度 {sensors['humidity']:.0f}%，"
                      + ("有人" if sensors["motion"] else "无人")), dict(sensors)


def tool_result_prompt(results: list[ToolResult]) -> str:
    """Compact tool results for the second LLM call (no tool definitions)."""
    lines = []
    for r in results:
        status = "成功" if r.ok else "失败"
        lines.append(f"- {r.name}({r.arguments}) -> {status}：{r.text}")
    return "\n".join(lines)
