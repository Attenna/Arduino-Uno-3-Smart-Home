"""Flask 应用工厂：注册蓝图、全局错误处理、启停 MCP 硬件桥。"""
from __future__ import annotations

import atexit
import logging
import traceback

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException
from .auth import install_auth

from .api import access, automation, camera, devices, face, ha, pages, status, voice
from .config import ensure_dirs, load_config
from .extensions import init_bridge, shutdown_bridge, start_watchers

logger = logging.getLogger(__name__)


def create_app(config: dict | None = None, start_hardware: bool = True):
    ensure_dirs()
    cfg = config or load_config()

    app = Flask(__name__)
    app.config["SMART_HOME_CFG"] = cfg
    install_auth(app)

    for module in (pages, status, devices, access, face, camera, voice, ha, automation):
        app.register_blueprint(module.bp)

    # ==================== 全局异常处理 ====================

    @app.errorhandler(Exception)
    def handle_global_error(e):
        if isinstance(e, HTTPException):
            return jsonify(error=e.description), e.code
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

    # ==================== 缓存策略 ====================
    @app.after_request
    def _no_cache_html(resp):
        # HTML 页面不缓存：避免浏览器加载到旧版本页面（脚本/样式已带 ?v 版本参数）
        if resp.headers.get("Content-Type", "").startswith("text/html"):
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
        return resp

    if start_hardware:
        init_bridge(cfg)
        # 识别哨兵跟硬件桥同一条启停路径：测试里 create_app(start_hardware=False)
        # 不该起线程，而 --no-serial 的真服务必须照样能刷脸开门（PIR 门控会自动退化）
        start_watchers(cfg)
    atexit.register(shutdown_bridge)
    return app
