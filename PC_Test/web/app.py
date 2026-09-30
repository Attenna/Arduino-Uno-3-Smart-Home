"""Flask 应用工厂：注册蓝图、全局错误处理、启停 MCP 硬件桥。"""
from __future__ import annotations

import atexit
import logging
import traceback

from flask import Flask, jsonify

from .api import access, automation, devices, face, ha, pages, status
from .config import ensure_dirs, load_config
from .extensions import init_bridge, shutdown_bridge

logger = logging.getLogger(__name__)


def create_app(config: dict | None = None, start_hardware: bool = True):
    ensure_dirs()
    cfg = config or load_config()

    app = Flask(__name__)
    app.config["SMART_HOME_CFG"] = cfg

    for module in (pages, status, devices, access, face, ha, automation):
        app.register_blueprint(module.bp)

    # ==================== 全局异常处理 ====================

    @app.errorhandler(Exception)
    def handle_global_error(e):
        logger.error("Unhandled exception: %s\n%s", e, traceback.format_exc())
        return jsonify({
            "error": "服务器内部错误",
            "error_en": "Internal server error",
            "detail": str(e) if app.debug else None,
        }), 500

    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify({"error": "接口不存在",
                        "error_en": "API endpoint not found"}), 404

    if start_hardware:
        init_bridge(cfg)
    atexit.register(shutdown_bridge)
    return app
