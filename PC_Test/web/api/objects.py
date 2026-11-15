"""物体检测接口与 SQLite 事件记录。"""
import json
import base64
import time
import os
import sqlite3
import threading
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory
from ..config import DATA_DIR
from ..object_detection import ObjectDetector
from .camera import _stream_url

bp = Blueprint("objects", __name__)


class ObjectService:
    def __init__(self, model, data_dir):
        self.detector = None
        self.error = None
        self.latest = None
        self.last_event = 0
        self.lock = threading.Lock()
        self.directory = data_dir / "objects"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db_path = data_dir / "smart_home.db"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS object_events (id TEXT PRIMARY KEY, time TEXT NOT NULL, result TEXT NOT NULL, image_name TEXT)")
        try:
            self.detector = ObjectDetector(model)
        except Exception as exc:
            self.error = str(exc)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def run(self, jpeg, evidence=False):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("检测进行中，请稍后重试")
        try:
            result = self.detector.detect(jpeg)
            result["event_id"] = None
            if result["detections"] and time.monotonic() - self.last_event >= 30:
                event_id = uuid.uuid4().hex
                image_name = event_id + ".jpg" if evidence else None
                target = self.directory / image_name if image_name else None
                try:
                    if target:
                        temporary = target.with_suffix(".tmp")
                        temporary.write_bytes(jpeg)
                        temporary.replace(target)
                    with self.connect() as db:
                        db.execute("INSERT INTO object_events VALUES (?,?,?,?)",
                                   (event_id, result["time"], json.dumps(result), image_name))
                except Exception:
                    if target:
                        target.unlink(missing_ok=True)
                        target.with_suffix(".tmp").unlink(missing_ok=True)
                    raise
                self.last_event = time.monotonic()
                result["event_id"] = event_id
            self.latest = result
            return result
        finally:
            self.lock.release()


def init_objects(app):
    cfg = app.config["SMART_HOME_CFG"].get("objects", {})
    model = os.environ.get("SMART_HOME_OBJECT_MODEL", cfg.get("model_path", "models/objects/best.onnx"))
    app.extensions["objects"] = ObjectService(model, DATA_DIR)
    app.register_blueprint(bp)


def service():
    return current_app.extensions["objects"]


@bp.get("/objects")
def page():
    return render_template("objects.html")


@bp.get("/api/objects/status")
def status():
    s = service()
    return jsonify(s.detector.info() if s.detector else {"loaded": False, "error": s.error})


@bp.get("/api/objects/result")
def latest():
    return jsonify(service().latest or {"detections": [], "time": None})


@bp.post("/api/objects/detect")
def detect():
    s = service()
    if not s.detector:
        return jsonify(error=s.error), 503
    if request.files.get("image"):
        jpeg = request.files["image"].read(10*1024*1024+1)
        if len(jpeg) > 10*1024*1024:
            return jsonify(error="图片超过 10MB"), 413
    else:
        url = _stream_url()
        if not url:
            return jsonify(error="未配置共享摄像头"), 503
        parts = urllib.parse.urlsplit(url)
        path = parts.path.rsplit("/", 1)[0] + "/snapshot"
        snapshot = urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))
        try:
            with urllib.request.urlopen(snapshot, timeout=5) as response:
                jpeg = response.read(10*1024*1024+1)
        except Exception:
            return jsonify(error="共享摄像头快照不可用"), 503
    try:
        result = s.run(jpeg, request.form.get("evidence") == "true")
        return jsonify(**result, preview="data:image/jpeg;base64," + base64.b64encode(jpeg).decode())
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 409


@bp.get("/api/objects/events")
def events():
    with service().connect() as db:
        rows = db.execute("SELECT * FROM object_events ORDER BY time DESC LIMIT 100").fetchall()
    return jsonify([{"id": r["id"], "time": r["time"], "result": json.loads(r["result"]),
                     "image": "/api/objects/images/"+r["id"] if r["image_name"] else None} for r in rows])


@bp.get("/api/objects/images/<event_id>")
def image(event_id):
    from flask import abort
    if len(event_id) != 32 or any(c not in "0123456789abcdef" for c in event_id):
        abort(404)
    return send_from_directory(service().directory, event_id + ".jpg")
