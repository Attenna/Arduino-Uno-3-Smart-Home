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
