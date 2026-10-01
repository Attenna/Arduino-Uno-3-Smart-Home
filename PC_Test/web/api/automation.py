"""自动化规则 API：积木规则集的读写、能力清单、实时判定预览、手动测试、执行日志。"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import extensions
from ..automation.capabilities import capabilities_payload
from ..automation.schema import ValidationError

bp = Blueprint("automation", __name__)


@bp.route("/api/automation/capabilities", methods=["GET"])
def get_capabilities():
    """Blockly 工具箱下拉框元数据（传感器/事件/执行器）。"""
    return jsonify(capabilities_payload())


@bp.route("/api/automation/rules", methods=["GET"])
def get_rules():
    engine = extensions.automation
    return jsonify({"rules": engine.rules if engine else []})


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


@bp.route("/api/automation/home_mode", methods=["GET"])
def get_home_mode():
    """全屋模式状态（自动/手动/离家 + 风扇/灯光覆盖档位 + 逗留/关门倒计时）。"""
    engine = extensions.automation
    if engine is None:
        return jsonify({"error": "自动化引擎未启动"}), 503
    return jsonify(engine.home_mode.config())


@bp.route("/api/automation/home_mode", methods=["PUT"])
def put_home_mode():
    """设置全屋模式。body: {mode?, fan_override?, light_level?, enabled?, 阈值...}。"""
    engine = extensions.automation
    if engine is None:
        return jsonify({"error": "自动化引擎未启动"}), 503
    try:
        data = request.get_json(force=True) or {}
        reason = str(data.pop("reason", "") or "页面设置")
        cfg = engine.home_mode.configure(reason=reason, **data)
        # 手动模式下 tick 不重发覆盖档；页面显式切换风扇/灯光覆盖档时立即执行
        # 一次（_apply_* 去重保证目标未变不下发串口）
        if "fan_override" in data or "light_level" in data:
            engine.home_mode.apply_overrides_now(
                reason="页面切换" + ("风扇覆盖" if "fan_override" in data
                                    else "灯光档位"))
    except Exception as e:                               # noqa: BLE001
        return jsonify({"error": f"全屋模式设置失败：{e}"}), 500
    return jsonify({"ok": True, "config": cfg, "message": "全屋模式设置已生效"})


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
