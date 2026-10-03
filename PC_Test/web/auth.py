"""Browser sessions and narrowly scoped service credentials. Fail closed."""
import hmac
import logging
import os
import secrets
import threading
import time
from datetime import timedelta

from flask import g, jsonify, redirect, render_template_string, request, session
from werkzeug.security import check_password_hash

logger = logging.getLogger(__name__)
SERVICE_ROUTES = {("GET", "/api/hardware/tools"),
                  ("POST", "/api/hardware/tool"), ("GET", "/api/status")}
LOGIN = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>智能家居登录</title><style>body{font:18px sans-serif;max-width:360px;
margin:12vh auto;padding:24px}input,button{box-sizing:border-box;width:100%;
padding:12px;margin:10px 0}p{color:#b22}</style><h1>智能家居</h1>
<form method="post"><input type="hidden" name="csrf" value="{{ csrf }}">
<label>用户名<input name="username" autocomplete="username" required></label>
<label>密码<input type="password" name="password" autocomplete="current-password" required></label>
<button>登录</button><p>{{ error }}</p></form></html>"""


def install_auth(app):
    username = os.environ.get("SMART_HOME_ADMIN_USER", "HwHiAiUser")
    password_hash = os.environ.get("SMART_HOME_ADMIN_PASSWORD_HASH", "")
    secret = os.environ.get("SMART_HOME_SESSION_SECRET", "")
    service_token = os.environ.get("SMART_HOME_SERVICE_TOKEN", "")
    if not password_hash or len(secret) < 32 or len(service_token) < 32:
        raise RuntimeError("Missing authentication configuration; refusing to start")
    app.secret_key = secret
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      SESSION_COOKIE_SECURE=os.environ.get("SMART_HOME_HTTPS") == "1",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
                      MAX_CONTENT_LENGTH=24 * 1024 * 1024)
    failures = {}
    lock = threading.Lock()

    def same_origin():
        return request.headers.get("Origin", "").rstrip("/") == request.host_url.rstrip("/")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        session.setdefault("login_csrf", secrets.token_urlsafe(32))
        if request.method == "POST":
            if not hmac.compare_digest(request.form.get("csrf", ""), session["login_csrf"]):
                return jsonify(error="登录表单已失效，请刷新"), 403
            now = time.monotonic()
            address = request.remote_addr or "unknown"
            with lock:
                for key in list(failures):
                    if now - failures[key][0] > 300:
                        del failures[key]
                start, count = failures.get(address, (now, 0))
                if count >= 10 or len(failures) >= 4096:
                    return jsonify(error="尝试次数过多，请五分钟后重试"), 429
                failures[address] = (start, count + 1)
            if (request.form.get("username", "") == username
                    and check_password_hash(password_hash, request.form.get("password", ""))):
                with lock:
                    failures.pop(address, None)
                session.clear()
                session["user"] = username
                session.permanent = True
                logger.info("Login succeeded user=%s ip=%s", username, address)
                return redirect("/")
            error = "用户名或密码错误"
        return render_template_string(LOGIN, csrf=session["login_csrf"], error=error)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect("/login")

    @app.before_request
    def authenticate():
        if request.path in {"/api/live", "/api/ready", "/api/health", "/login"}:
            return None
        # External identity assertions are disabled until a trusted producer is deployed.
        # Neither an ordinary browser session nor the voice token may impersonate a face.
        if request.path == "/api/face/notify":
            return jsonify(error="外部人脸结果推送已禁用，请使用本机识别"), 403
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].encode(), service_token.encode()):
            if (request.method, request.path) not in SERVICE_ROUTES:
                return jsonify(error="服务凭据无此权限"), 403
            g.actor = "voice-service"
            return None
        if session.get("user") != username:
            if request.path.startswith("/api/"):
                return jsonify(error="请先登录", login_url="/login"), 401
            return redirect("/login")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not same_origin():
            return jsonify(error="请求来源校验失败"), 403
        g.actor = username

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            logger.info("API audit actor=%s method=%s path=%s status=%s ip=%s",
                        getattr(g, "actor", "anonymous"), request.method,
                        request.path, response.status_code, request.remote_addr)
        return response
