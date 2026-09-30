"""规则 JSON 模型与校验（前端 Blockly 积木 <-> 后端规则 JSON 的契约）。

规则结构::

    {
      "id": "a1b2c3d4",
      "name": "高温自动开风扇",
      "enabled": true,
      "trigger": { ... 触发块 ... },
      "match": "all",                 # 条件块组合方式：all=全部满足 / any=任一满足
      "conditions": [ ... 条件块 ... ],
      "actions": [ ... 满足时执行的动作块序列 ... ],
      "else_actions": [ ... 不满足时的状态切换动作 ... ],
      "cooldown": 5                   # 两次触发的最小间隔（秒）
    }
"""
from __future__ import annotations

from .capabilities import (
    ACTION_DEVICES, COMPARATORS, CONDITION_SOURCES, EVENT_TRIGGERS,
)

COMPARATOR_IDS = {c["id"] for c in COMPARATORS}


class ValidationError(ValueError):
    """规则 JSON 不合法。"""


def _require(obj: dict, keys: tuple[str, ...], where: str) -> None:
    for key in keys:
        if key not in obj:
            raise ValidationError(f"{where} 缺少字段 {key}")


def _as_number(value, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{where} 需要数字，得到 {value!r}")
    return float(value)


def validate_trigger(trig: dict) -> dict:
    _require(trig, ("kind",), "触发块")
    kind = trig["kind"]
    if kind == "sensor":
        _require(trig, ("sensor", "op", "value"), "传感器触发块")
        if trig["sensor"] not in CONDITION_SOURCES:
            raise ValidationError(f"未知传感器/状态: {trig['sensor']}")
        if trig["op"] not in COMPARATOR_IDS:
            raise ValidationError(f"非法比较符: {trig['op']}")
        value = trig["value"]
        if isinstance(value, bool):
            pass
        elif isinstance(value, str) and value in ("true", "false"):
            value = value == "true"
        elif not isinstance(value, (int, float, str)):
            raise ValidationError("触发阈值必须是数字或 true/false")
        clean = {"kind": "sensor", "sensor": trig["sensor"],
                 "op": trig["op"], "value": value}
        # 「持续 N 秒」：条件连续保持该时长才触发（逗留报警/烟雾确认这类需求）
        hold = trig.get("hold_sec")
        if hold not in (None, "", 0):
            hold = _as_number(hold, "传感器触发块的持续时长")
            if not 1 <= hold <= 86400:
                raise ValidationError("持续时长需在 1~86400 秒之间")
            clean["hold_sec"] = hold
        return clean
    if kind == "event":
        _require(trig, ("event",), "事件触发块")
        event = trig["event"]
        if event not in EVENT_TRIGGERS:
            raise ValidationError(f"未知事件: {event}")
        clean = {"kind": "event", "event": event}
        # keypad / ir 事件可带参数过滤（按键名 / 红外命令码）
        for extra in ("key", "command"):
            if trig.get(extra) not in (None, ""):
                clean[extra] = str(trig[extra]).strip()
        return clean
    if kind == "interval":
        seconds = _as_number(trig.get("seconds"), "周期触发块")
        if seconds < 2:
            raise ValidationError("周期间隔不能小于 2 秒")
        return {"kind": "interval", "seconds": min(seconds, 86400)}
    if kind == "time":
        hhmm = str(trig.get("hhmm", ""))
        try:
            hour, minute = (int(x) for x in hhmm.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValidationError(f"定时时间格式应为 HH:MM，得到 {hhmm!r}")
        return {"kind": "time", "hhmm": f"{hour:02d}:{minute:02d}"}
    raise ValidationError(f"未知触发类型: {kind}")


def validate_condition(cond: dict) -> dict:
    _require(cond, ("sensor", "op", "value"), "条件块")
    if cond["sensor"] not in CONDITION_SOURCES:
        raise ValidationError(f"条件块未知传感器/状态: {cond['sensor']}")
    if cond["op"] not in COMPARATOR_IDS:
        raise ValidationError(f"条件块非法比较符: {cond['op']}")
    value = cond["value"]
    if isinstance(value, str) and value in ("true", "false"):
        value = value == "true"
    if not isinstance(value, (int, float, bool, str)):
        raise ValidationError("条件值必须是数字、布尔或字符串")
    return {"sensor": cond["sensor"], "op": cond["op"], "value": value}


def validate_action(action: dict, where: str = "动作块") -> dict:
    _require(action, ("device",), where)
    device = action["device"]
    if device not in ACTION_DEVICES:
        raise ValidationError(f"{where}未知设备: {device}")
    clean = {"device": device}
    if device == "delay":
        seconds = _as_number(action.get("seconds", 1), where)
        if not 0 < seconds <= 300:
            raise ValidationError("延时需在 1~300 秒之间")
        clean["seconds"] = seconds
        return clean
    if device == "door":
        status = action.get("status", "open")
        if status not in ("open", "close"):
            raise ValidationError("门动作只能是 open/close")
        clean["status"] = status
    elif device == "window":
        status = action.get("status", "open")
        if status not in ("open", "close", "normal"):
            raise ValidationError("窗动作只能是 open/close/normal(半开45°)")
        clean["status"] = status
    elif device == "light":
        status = action.get("status", "on")
        if status not in ("on", "off"):
            raise ValidationError("灯动作只能是 on/off")
        brightness = int(_as_number(action.get("brightness", 100), where))
        clean.update({"status": status,
                      "brightness": max(0, min(100, brightness))})
    elif device == "fan":
        speed = int(_as_number(action.get("speed", 100), where))
        clean["speed"] = max(0, min(100, speed))
    elif device == "buzzer":
        count = int(_as_number(action.get("count", 1), where))
        on_ms = int(_as_number(action.get("on_ms", 200), where))
        off_ms = int(_as_number(action.get("off_ms", 200), where))
        clean.update({"count": max(1, min(10, count)),
                      "on_ms": max(50, min(2000, on_ms)),
                      "off_ms": max(50, min(2000, off_ms))})
    elif device == "oled":
        # 二选一：clear 清屏，或 text 显示文本（可含 {占位符}）
        if action.get("clear"):
            clean["clear"] = True
        else:
            raw = action.get("text")
            if not isinstance(raw, str):
                raise ValidationError("OLED 文本必须为字符串")
            text = raw.strip()
            if not text:
                raise ValidationError("OLED 文本不能为空（或请用 clear 清屏）")
            if len(text) > 200:
                raise ValidationError("OLED 文本过长（最多 200 字符）")
            clean["text"] = text
    elif device == "home_mode":
        # 三项都可选，但至少要设一项；空串 = 该项不改
        mode = str(action.get("mode") or "").strip()
        if mode:
            if mode not in ("auto", "manual", "away", "toggle"):
                raise ValidationError("全屋模式只能是 auto/manual/away/toggle")
            clean["mode"] = mode
        fan = str(action.get("fan_override") or "").strip()
        if fan:
            if fan not in ("auto", "on", "off", "cycle"):
                raise ValidationError("风扇档位只能是 auto(回到自动)/on/off/cycle(循环下一档)")
            clean["fan_override"] = fan
        light = str(action.get("light_level") or "").strip()
        if light:
            if light not in ("auto", "hold", "dark", "half", "bright", "cycle"):
                raise ValidationError("灯光档位只能是 auto/hold/dark/half/bright/cycle")
            clean["light_level"] = light
        if len(clean) == 1:
            raise ValidationError("全屋模式动作至少要设置一项（模式/风扇档位/灯光档位）")
    elif device == "voice":
        act = str(action.get("action") or "wake").strip()
        if act not in ("wake", "say"):
            raise ValidationError("语音助手动作只能是 wake(唤醒)/say(播报)")
        clean["action"] = act
        text = str(action.get("text") or "").strip()
        if act == "say" and not text:
            raise ValidationError("语音播报需要填写文本")
        if len(text) > 200:
            raise ValidationError("语音文本过长（最多 200 字符）")
        if text:
            clean["text"] = text
    return clean


def validate_rule(rule: dict) -> dict:
    _require(rule, ("name", "trigger", "actions"), "规则")
    name = str(rule["name"]).strip()
    if not name:
        raise ValidationError("规则名称不能为空")
    trigger = validate_trigger(rule["trigger"])
    conditions = [validate_condition(c) for c in (rule.get("conditions") or [])]
    match = rule.get("match", "all")
    if match not in ("all", "any"):
        raise ValidationError("条件组合方式只能是 all/any")
    actions = [validate_action(a, "执行块") for a in (rule.get("actions") or [])]
    if not actions:
        raise ValidationError("每条规则至少要有一个执行动作")
    else_actions = [validate_action(a, "否则块")
                    for a in (rule.get("else_actions") or [])]
    raw_cooldown = rule.get("cooldown", 3)
    cooldown = 3.0 if raw_cooldown is None else float(raw_cooldown)
    clean = {
        "id": str(rule.get("id") or "").strip() or None,   # None 时由引擎补 id
        "name": name[:50],
        "enabled": bool(rule.get("enabled", True)),
        "trigger": trigger,
        "match": match,
        "conditions": conditions,
        "actions": actions,
        "else_actions": else_actions,
        "cooldown": max(0.0, min(cooldown, 3600.0)),
    }
    # 内置默认规则带 preset 标记（仅用于「是否已注入过」的判断，用户可自由改名/删除）
    preset = str(rule.get("preset") or "").strip()
    if preset:
        clean["preset"] = preset[:40]
    return clean


def validate_rules(payload) -> list[dict]:
    """payload 可以是 {'rules': [...]} 或直接 [...]。"""
    if isinstance(payload, dict):
        payload = payload.get("rules")
    if not isinstance(payload, list):
        raise ValidationError("规则列表格式错误")
    if len(payload) > 80:
        raise ValidationError("规则数量不能超过 80 条")
    return [validate_rule(r) for r in payload]
