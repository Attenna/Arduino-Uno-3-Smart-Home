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
LOGIN = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title data-zh="智能家居登录" data-en="Smart Home Login">智能家居登录</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400..700&family=Noto+Serif+SC:wght@500;600;700&family=Plus+Jakarta+Sans:wght@400..800&display=swap" rel="stylesheet">
<style>
:root{
  --bg-primary:#fdf3d7;--bg-card:#fffef7;--border:#ead5a0;
  --text-primary:#3b362c;--text-secondary:#7c7466;--text-muted:#b2a992;
  --accent:#f5b301;--accent-strong:#e0a200;--danger:#b5544a;
  --radius:18px;--radius-sm:10px;
  --transition:all .3s cubic-bezier(.4,0,.2,1);
}
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
  color:var(--text-primary);background:var(--bg-primary);line-height:1.5;
  background-image:radial-gradient(1200px 600px at 50% -10%,#fffdf0 0%,rgba(253,243,215,0) 70%),
                   radial-gradient(900px 520px at 92% 112%,rgba(245,179,1,.16) 0%,rgba(253,243,215,0) 62%);
  display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px;
}
.login-card{
  position:relative;width:100%;max-width:400px;
  background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);
  box-shadow:0 18px 48px rgba(196,158,44,.22);padding:42px 34px 30px;
}
.lang-switch{
  position:absolute;top:16px;right:16px;height:32px;min-width:46px;padding:0 12px;
  background:#fffbf0;border:1px solid var(--border);border-radius:999px;
  color:var(--text-secondary);font-size:13px;font-weight:600;cursor:pointer;transition:var(--transition);
}
.lang-switch:hover{color:var(--text-primary);border-color:var(--accent);background:#fdecc0}
.brand{text-align:center;margin-bottom:26px}
.brand-icon{
  display:inline-flex;align-items:center;justify-content:center;width:56px;height:56px;margin-bottom:14px;
  color:#fff;background:var(--accent);border-radius:16px;box-shadow:0 8px 20px rgba(245,179,1,.35);
}
.brand-icon svg{width:30px;height:30px}
h1{font-size:24px;font-weight:600;letter-spacing:.5px}
.brand-sub{margin-top:6px;font-size:13px;color:var(--text-secondary)}
.field{display:block;margin-bottom:16px}
.field>span{display:block;margin-bottom:6px;font-size:13px;font-weight:600;color:var(--text-secondary)}
.field input{
  width:100%;padding:12px 14px;font-size:15px;color:var(--text-primary);
  background:#fffef7;border:1px solid var(--border);border-radius:var(--radius-sm);
  outline:none;transition:var(--transition);
}
.field input:focus{border-color:var(--accent);background:#fff;box-shadow:0 0 0 3px rgba(245,179,1,.18)}
.submit{
  width:100%;margin-top:6px;padding:13px;font-size:15px;font-weight:700;color:#3b362c;
  background:var(--accent);border:none;border-radius:var(--radius-sm);cursor:pointer;transition:var(--transition);
}
.submit:hover{background:var(--accent-strong);box-shadow:0 6px 18px rgba(245,179,1,.35);transform:translateY(-1px)}
.submit:active{transform:translateY(0)}
.error{
  margin-top:14px;padding:10px 12px;text-align:center;font-size:13px;color:var(--danger);
  background:rgba(181,84,74,.1);border:1px solid rgba(181,84,74,.3);border-radius:var(--radius-sm);
}
.error[hidden]{display:none}
.foot{margin-top:24px;text-align:center;font-size:12px;color:var(--text-muted)}
html[lang="en"] body{font-family:'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
html[lang="en"] h1{font-family:'Fraunces',Georgia,serif;font-weight:600}
</style>
</head>
<body>
  <div class="login-card">
    <button class="lang-switch" id="langSwitch" type="button" aria-label="language">EN</button>
    <div class="brand">
      <span class="brand-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
      </span>
      <h1 data-zh="智能家居" data-en="Smart Home">智能家居</h1>
      <p class="brand-sub" data-zh="请登录以继续" data-en="Sign in to continue">请登录以继续</p>
    </div>
    <form method="post">
      <input type="hidden" name="csrf" value="{{ csrf }}">
      <label class="field">
        <span data-zh="用户名" data-en="Username">用户名</span>
        <input name="username" autocomplete="username" required>
      </label>
      <label class="field">
        <span data-zh="密码" data-en="Password">密码</span>
        <input type="password" name="password" autocomplete="current-password" required>
      </label>
      <button class="submit" data-zh="登录" data-en="Sign in">登录</button>
      <p class="error" id="errBox"{% if not error %} hidden{% endif %}>{{ error }}</p>
    </form>
    <div class="foot" data-zh="智能家居控制系统 · v2.9" data-en="Smart Home System · v2.9">智能家居控制系统 · v2.9</div>
  </div>
  <script>
  (function(){
    var KEY='smart_home_lang';
    var WRONG=['用户名或密码错误','Incorrect username or password'];
    function apply(lang){
      var en=lang==='en';
      document.documentElement.lang=en?'en':'zh-CN';
      document.querySelectorAll('[data-zh]').forEach(function(el){
        el.textContent=en?el.dataset.en:el.dataset.zh;
      });
      var sw=document.getElementById('langSwitch');
      if(sw){sw.textContent=en?'中':'EN';}
      var err=document.getElementById('errBox');
      if(err){
        var v=(err.textContent||'').trim();
        if(v===WRONG[0]){err.textContent=WRONG[1];}
        else if(v===WRONG[1]){err.textContent=WRONG[0];}
      }
    }
    var saved='zh';
    try{saved=localStorage.getItem(KEY)||'zh';}catch(e){}
    apply(saved);
    var sw=document.getElementById('langSwitch');
    if(sw){sw.addEventListener('click',function(){
      var next=document.documentElement.lang==='en'?'zh':'en';
      try{localStorage.setItem(KEY,next);}catch(e){}
      apply(next);
    });}
  })();
  </script>
</body>
</html>"""


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
