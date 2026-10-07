"""摄像头实时画面：把 camera_stream.py 的 MJPEG 流同源转发给前端页面。

浏览器直连摄像头服务需要额外端口（Docker 里 camera 是独立容器 :8080），
这里由后端代理，人脸识别页面只需访问 /api/camera/stream，天然同源、
不受端口/CORS 影响。地址优先级：环境变量 SMART_HOME_CAMERA_URL >
web_config.yaml 的 camera.stream_url。摄像头服务连不上时返回 503。

/api/camera/status 会顺带问一次 camera 服务的 /health，把「有没有插着、
设备名、上一帧多久以前」原样透出，省得只看 enabled 时分不清是没配置、
容器没起还是摄像头被拔了。
"""
import json
import os
import urllib.parse
import urllib.request

from flask import Blueprint, Response, current_app, jsonify

bp = Blueprint("camera", __name__)

STREAM_PATH = "/api/camera/stream"
_BOUNDARY = "frame"          # 与 camera_stream.py 的 video_feed 一致
_HEALTH_TIMEOUT = 2.0


def _stream_url() -> str:
    env = os.environ.get("SMART_HOME_CAMERA_URL")
    if env:
        return env.strip()
    cfg = current_app.config.get("SMART_HOME_CFG") or {}
    return str((cfg.get("camera") or {}).get("stream_url") or "").strip()


def _health_url(stream_url: str) -> str:
    """同一服务的健康端点：.../video_feed -> .../health。"""
    parts = urllib.parse.urlsplit(stream_url)
    path = parts.path.rsplit("/", 1)[0] + "/health"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _camera_health(stream_url: str) -> dict:
    try:
        with urllib.request.urlopen(_health_url(stream_url), timeout=_HEALTH_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:                               # noqa: BLE001
        return {"online": False, "error": f"摄像头服务无响应: {e}"}


@bp.route("/api/camera/distance")
def doorway_distance():
    from .. import extensions
    engine = extensions.automation
    return jsonify(engine.doorway.snapshot() if engine else
                   {"distance_cm": None, "valid": False, "status": "unavailable"})


@bp.route("/api/camera/status")
def camera_status():
    url = _stream_url()
    body = {"enabled": bool(url), "stream_url": url, "stream": STREAM_PATH}
    body["camera"] = _camera_health(url) if url else {"online": False, "error": "未配置摄像头流地址"}
    return jsonify(body)


@bp.route("/api/camera/stream")
def camera_stream():
    url = _stream_url()
    if not url:
        return jsonify({"error": "未配置摄像头流地址",
                        "error_en": "Camera stream URL not configured"}), 503
    # 先探一次连接：能连上才返回 200 流，否则给前端明确的 503，便于提示
    try:
        upstream = urllib.request.urlopen(url, timeout=5)
    except Exception as e:                               # noqa: BLE001
        return jsonify({"error": f"摄像头流不可用: {e}",
                        "error_en": f"Camera stream unavailable: {e}"}), 503

    def _gen():
        try:
            while True:
                chunk = upstream.read(8192)
                if not chunk:
                    break
                yield chunk
        except Exception:                                # noqa: BLE001
            return
        finally:
            upstream.close()

    return Response(_gen(), mimetype=f"multipart/x-mixed-replace; boundary={_BOUNDARY}")

@bp.route("/api/security/events")
def security_events():
    from ..config import DATA_DIR
    from ..security_monitor import SecurityMonitor
    return jsonify(SecurityMonitor(DATA_DIR / "security").events())


@bp.route("/api/security/images/<event_id>")
def security_image(event_id):
    import re
    from flask import abort, send_from_directory
    from ..config import DATA_DIR
    if not re.fullmatch(r"[0-9a-f]{32}", event_id):
        abort(404)
    return send_from_directory(DATA_DIR / "security", event_id + ".jpg")


@bp.route("/security")
def security_page():
    from flask import render_template
    return render_template("security.html")
