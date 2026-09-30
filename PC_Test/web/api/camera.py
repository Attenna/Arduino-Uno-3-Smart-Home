"""摄像头实时画面：把 camera_stream.py 的 MJPEG 流同源转发给前端页面。

浏览器直连摄像头服务需要额外端口（Docker 里 camera 是独立容器 :8080），
这里由后端代理，人脸识别页面只需访问 /api/camera/stream，天然同源、
不受端口/CORS 影响。地址优先级：环境变量 SMART_HOME_CAMERA_URL >
web_config.yaml 的 camera.stream_url。摄像头不可用时返回 503。
"""
import os
import urllib.request

from flask import Blueprint, Response, current_app, jsonify

bp = Blueprint("camera", __name__)

STREAM_PATH = "/api/camera/stream"
_BOUNDARY = "frame"          # 与 camera_stream.py 的 video_feed 一致


def _stream_url() -> str:
    env = os.environ.get("SMART_HOME_CAMERA_URL")
    if env:
        return env.strip()
    cfg = current_app.config.get("SMART_HOME_CFG") or {}
    return str((cfg.get("camera") or {}).get("stream_url") or "").strip()


@bp.route("/api/camera/status")
def camera_status():
    url = _stream_url()
    return jsonify({"enabled": bool(url), "stream_url": url, "stream": STREAM_PATH})


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