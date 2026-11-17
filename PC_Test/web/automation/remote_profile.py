"""显式安装的遥控规则方案；不在 Web 启动时改写用户规则。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "automation"
FAN_AUTO = {"sensor": "g:允许自动开风扇", "op": "==", "value": True}


def is_ir_rule(rule: dict) -> bool:
    trigger = rule.get("trigger") or {}
    return trigger.get("kind") == "event" and trigger.get("event") == "ir"


def configure_remote(document: dict) -> tuple[dict, list[str]]:
    """返回新配置和被替换的规则名称；输入不变，非遥控规则保持原样。

    用户显式选择此方案时，全部旧 IR 接收规则被统一的 0–9 方案替换。
    对本项目 temp26on/off 补上自动许可，避免遥控开扇后下一轮温控立即关扇。
    不改其他自动化。存在其他启用的自动风扇动作时拒绝安装，需先解决冲突。
    """
    if not isinstance(document, dict) or not isinstance(document.get("rules"), list):
        raise ValueError("规则文件必须是含 rules 列表的对象")
    result = copy.deepcopy(document)
    old = result["rules"]
    removed = [r.get("name", r.get("id", "")) for r in old if is_ir_rule(r)]
    known_ids = {"temp26on", "temp26off"}
    for rule in old:
        actions = rule.get("actions", []) + rule.get("else_actions", [])
        if (rule.get("enabled") and not is_ir_rule(rule)
                and rule.get("id") not in known_ids
                and any(a.get("device") == "fan" for a in actions)):
            raise ValueError(f"请先处理其他自动风扇规则：{rule.get('name')}")

    kept = [r for r in old if not is_ir_rule(r)]
    thermal = json.loads((EXAMPLES / "fan-temperature-26.json").read_text(encoding="utf-8"))["rules"]
    for template in thermal:
        existing = next((r for r in kept if r.get("id") == template["id"]), None)
        if existing is None:
            kept.append(copy.deepcopy(template))
            continue
        if (existing.get("match", "all") != "all"
                or existing.get("trigger", {}).get("kind") != "interval"
                or existing.get("else_actions")):
            raise ValueError(f"温控规则已自定义，请先审阅：{existing.get('name')}")
        conditions = existing.setdefault("conditions", [])
        if any(c.get("sensor") == FAN_AUTO["sensor"] and c != FAN_AUTO for c in conditions):
            raise ValueError("温控规则的自动许可条件冲突")
        if FAN_AUTO not in conditions:
            conditions.append(copy.deepcopy(FAN_AUTO))

    profile = json.loads((EXAMPLES / "ir-remote-0-9.json").read_text(encoding="utf-8"))["rules"]
    seen_commands = set()
    old_presets = {r.get("preset"): r for r in old if is_ir_rule(r) and r.get("preset")}
    for raw in profile:
        rule = copy.deepcopy(raw)
        previous = old_presets.get(rule.get("preset"))
        if previous:
            rule["id"] = previous["id"]
        command = int(rule["trigger"]["command"], 16)
        if command in seen_commands:
            raise ValueError("方案存在重复按键")
        seen_commands.add(command)
        kept.append(rule)
    ids = [r.get("id") for r in kept]
    if len(ids) != len(set(ids)):
        raise ValueError("规则 ID 冲突，未生成配置")
    result["rules"] = kept
    return result, removed
