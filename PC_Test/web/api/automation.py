"""自动化规则 API：积木规则集的读写、能力清单、实时判定预览、手动测试、执行日志。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import extensions
from ..automation.capabilities import capabilities_payload
from ..automation.default_rules import GATING_PRESETS
from ..automation.schema import ValidationError

bp = Blueprint("automation", __name__)


@bp.route("/api/automation/capabilities", methods=["GET"])
def get_capabilities():
    """Blockly 工具箱下拉框元数据（传感器/事件/执行器 + 全局状态变量）。"""
    engine = extensions.automation
    defs = engine.global_state.definitions() if engine else []
    return jsonify(capabilities_payload(defs))


# ==================== 全局状态（自由命名变量，见 global_state.py） ====================

@bp.route("/api/automation/global_state", methods=["GET"])
def get_global_state():
    """全部全局状态定义与当前值（状态条目卡片渲染 + 能力清单共用）。"""
    engine = extensions.automation
    if engine is None:
        return jsonify({"error": "自动化引擎未启动"}), 503
    return jsonify({"vars": engine.global_state.definitions()})


@bp.route("/api/automation/global_state", methods=["POST"])
def create_global_state():
    """新建变量。body: {name, type?, label?, value?, choices?, choice_labels?,
    unit?, min?, max?}。"""
    engine = extensions.automation
    if engine is None:
        return jsonify({"error": "自动化引擎未启动"}), 503
    data = request.get_json(force=True) or {}
    ok, res = engine.global_state.create(
        name=data.get("name", ""), type_=data.get("type", "bool"),
        label=data.get("label"), value=data.get("value"),
        choices=data.get("choices"), choice_labels=data.get("choice_labels"),
        unit=data.get("unit"), min=data.get("min"), max=data.get("max"))
    if not ok:
        return jsonify({"error": str(res)}), 400
    return jsonify({"ok": True, "var": res,
                    "vars": engine.global_state.definitions(),
                    "message": f"已新建全局状态「{res['label']}」"})


@bp.route("/api/automation/global_state/<var_id>", methods=["PUT"])
def update_global_state(var_id):
    """改变量。body 可含: name(改名) / label / choices / choice_labels /
    unit / min / max / value(手动写值) / op("toggle" 翻转)。"""
    engine = extensions.automation
    if engine is None:
        return jsonify({"error": "自动化引擎未启动"}), 503
    data = request.get_json(force=True) or {}
    store = engine.global_state
    new_name = str(data.get("name") or "").strip()
    if new_name:
        ok, res = store.rename(var_id, new_name)
        if not ok:
            return jsonify({"error": str(res)}), 400
        if res["old_id"] != res["var"]["id"]:
            engine.rewrite_state_refs(res["old_id"], res["var"]["id"])
        var_id = res["var"]["id"]
    meta_keys = ("label", "choices", "choice_labels", "unit", "min", "max")
    if any(k in data for k in meta_keys):
        ok, res = store.update(var_id, **{k: data.get(k) for k in meta_keys})
        if not ok:
            return jsonify({"error": str(res)}), 400
    if data.get("op") == "toggle":
        ok, res = store.toggle(var_id, source="页面")
        if not ok:
            return jsonify({"error": str(res)}), 400
    elif "value" in data and data.get("value") is not None:
        ok, res = store.set_value(var_id, data.get("value"), source="页面")
        if not ok:
            return jsonify({"error": str(res)}), 400
    return jsonify({"ok": True, "var": store.get(var_id),
                    "vars": store.definitions(),
                    "message": "全局状态已更新"})


@bp.route("/api/automation/global_state/<var_id>", methods=["DELETE"])
def delete_global_state(var_id):
    """删除变量。规则里的引用不会因此报错（引擎读盘宽松），但条件将永远不成立。"""
    engine = extensions.automation
    if engine is None:
        return jsonify({"error": "自动化引擎未启动"}), 503
    ok, res = engine.global_state.delete(var_id)
    if not ok:
        return jsonify({"error": str(res)}), 400
    return jsonify({"ok": True, "vars": engine.global_state.definitions(),
                    "message": f"已删除全局状态「{res['label']}」"})


@bp.route("/api/automation/rules", methods=["GET"])
def get_rules():
    engine = extensions.automation
    payload = {"rules": engine.rules if engine else []}
    if engine is not None:
        # 「门控维护预设」名单：前端据此判断哪些门控预设当前被停用并给醒目提示（#77）
        payload["gating_presets"] = list(GATING_PRESETS)
        # 启动时做过旧规则迁移 → 随首个拉取带出（只给一次，前端 toast 提示）
        info = engine.consume_migration_info()
        if info and (info.get("migrated") or info.get("dropped")
                     or info.get("invalid")):
            payload["migration"] = info
    return jsonify(payload)


@bp.route("/api/automation/rules", methods=["PUT"])
def save_rules():
    engine = extensions.automation
    if engine is None:
        return jsonify({"error": "自动化引擎未启动"}), 503
    try:
        saved = engine.save_rules(request.get_json(force=True))
    except ValidationError as e:
        return jsonify({"error": f"规则校验失败：{e}"}), 400
    except Exception as e:                               # noqa: BLE001
        return jsonify({"error": f"保存失败：{e}"}), 500
    return jsonify({"ok": True, "rules": saved,
                    "message": f"已保存 {len(saved)} 条规则"})


@bp.route("/api/automation/preview", methods=["GET"])
def preview():
    """当前真实数据下，每条规则的触发/条件成立情况（不执行任何动作）。"""
    engine = extensions.automation
    if engine is None:
        return jsonify({"error": "自动化引擎未启动"}), 503
    return jsonify({"preview": engine.preview()})


@bp.route("/api/automation/rules/<rule_id>/run", methods=["POST"])
def run_rule(rule_id):
    """立即测试：无视触发沿/冷却，按当前条件执行一条规则。"""
    engine = extensions.automation
    if engine is None:
        return jsonify({"error": "自动化引擎未启动"}), 503
    result = engine.manual_fire(rule_id)
    return jsonify(result), (200 if result.get("ok") else 400)


@bp.route("/api/automation/rules/restore", methods=["POST"])
def restore_rules():
    """恢复内置规则：把被删掉的默认规则（preset）按原样补回。"""
    engine = extensions.automation
    if engine is None:
        return jsonify({"error": "自动化引擎未启动"}), 503
    rules = engine.restore_presets()
    return jsonify({"ok": True, "rules": rules,
                    "message": f"内置规则已恢复，当前共 {len(rules)} 条"})


@bp.route("/api/automation/logs", methods=["GET"])
def get_logs():
    limit = request.args.get("limit", 30, type=int)
    return jsonify({"logs": extensions.db.get_automation_logs(limit)})


@bp.route("/api/automation/oled", methods=["GET"])
def get_oled_config():
    """读取 OLED 轮播配置（enabled/interval/pages）。"""
    engine = extensions.automation
    if engine is None:
        return jsonify({"error": "自动化引擎未启动"}), 503
    return jsonify(engine.oled_config())


@bp.route("/api/automation/oled", methods=["PUT"])
def put_oled_config():
    """写入 OLED 轮播配置并应用到引擎。body: {enabled?, interval?, pages?}。"""
    engine = extensions.automation
    if engine is None:
        return jsonify({"error": "自动化引擎未启动"}), 503
    try:
        data = request.get_json(force=True) or {}
        cfg = engine.set_oled(
            enabled=data.get("enabled"),
            interval=data.get("interval"),
            pages=data.get("pages"),
        )
    except ValueError as e:
        return jsonify({"error": f"OLED 配置校验失败：{e}"}), 400
    except Exception as e:                               # noqa: BLE001
        return jsonify({"error": f"OLED 配置保存失败：{e}"}), 500
    return jsonify({"ok": True, "config": cfg,
                    "message": "OLED 轮播配置已保存并生效"})
