"""USB 摄像头流式传输 + 人脸检测
====================================
通过 USB 摄像头（如 USB2.0 Web Cam）采集画面，支持两种输出模式：
  1. 本地窗口显示（--mode local）—— 开发机调试用
  2. HTTP MJPEG 流（--mode web）—— 香橙派部署用，浏览器查看

默认同时支持两种模式（有图形界面时弹本地窗口，同时起 HTTP 服务）。

热插拔：进程启动时没有摄像头也照常起来，HTTP 服务与采集线程各自常驻；
采集线程按退避节奏重新枚举设备（Linux 下扫 /dev/video*），物理拔插后
自行恢复。断流期间 /video_feed 发送占位帧（而不是静默不返回），前端
onerror 与 /api/camera/status 因此能看到真实状态。

路由：/ 首页、/video_feed MJPEG 流、/snapshot 最近一帧单张 JPEG（供
后端识别哨兵轮询，无新鲜帧时返回 503 JSON，绝不发占位帧）、/health。

用法:
    python camera_stream.py                       # 自动发现摄像头，本地窗口 + HTTP 流
    python camera_stream.py --mode web            # 仅 HTTP 流（适合香橙派无头环境）
    python camera_stream.py --mode local          # 仅本地窗口
    python camera_stream.py --no-detect           # 关闭人脸检测（纯流式传输）
    python camera_stream.py --cam 0               # 指定摄像头索引
    python camera_stream.py --cam /dev/video1     # 指定设备节点
    python camera_stream.py --host 0.0.0.0 --port 8080

依赖:
    pip install opencv-python flask
"""

import argparse
import glob
import os
import sys
import threading
import time

import cv2
import numpy as np

IS_LINUX = sys.platform.startswith("linux")

BACKOFF_MIN_S = 1.0
BACKOFF_MAX_S = 10.0
# 打开后不到这么久就断流，视为设备在抖动（元数据节点、供电不足等），退避加倍
FLAP_WINDOW_S = 2.0
# 超过这个秒数没有新帧，/video_feed 改发占位帧
FRAME_FRESH_S = 2.0
# 占位帧的出图频率，避免空转时把 CPU 打满
PLACEHOLDER_INTERVAL_S = 0.2


# ==================== 摄像头发现 ====================

def list_video_devices():
    """宿主机当前的 /dev/video* 节点，按编号排序（热插拔后重新枚举即可看到新节点）。"""
    if not IS_LINUX:
        return []

    def order(path):
        digits = "".join(c for c in os.path.basename(path) if c.isdigit())
        return int(digits) if digits else 0

    return sorted(glob.glob("/dev/video*"), key=order)


def _normalize_preferred(preferred):
    """把 --cam 参数变成 (打开目标, 描述)；无法识别返回 None。

    未显式指定时读 CAMERA_DEVICE（compose 里透传宿主机探测到的节点），
    只作为优先候选——它不在位时仍会继续枚举其它 /dev/video*。
    """
    if preferred in (None, ""):
        preferred = os.environ.get("CAMERA_DEVICE", "").strip()
    if preferred in (None, ""):
        return None
    text = str(preferred).strip()
    if text.isdigit():
        return int(text), f"指定索引 {text}"
    if IS_LINUX:
        path = text if text.startswith("/") else f"/dev/{text}"
        return path, f"指定设备 {path}"
    return text, f"指定名称 {text}"


def candidate_devices(preferred=None):
    """按优先级排好的候选设备，逐个尝试打开。"""
    cands = []
    norm = _normalize_preferred(preferred)
    if norm:
        cands.append(norm)
    if IS_LINUX:
        # 名称 'Web Cam' 是 Windows/DSHOW 的习惯，Linux 下只认设备节点
        for path in list_video_devices():
            if (path, f"指定设备 {path}") not in cands:
                cands.append((path, f"节点 {path}"))
    else:
        if norm is None:
            cands.append(("Web Cam", "名称 'Web Cam'"))
        for i in range(5):
            cands.append((i, f"索引 {i}"))
    return cands


def open_device(target):
    """打开单个候选设备；失败返回 None。Linux 下强制走 V4L2，跳过其它后端的探测。"""
    cap = cv2.VideoCapture(target, cv2.CAP_V4L2) if IS_LINUX else cv2.VideoCapture(target)
    if cap.isOpened():
        return cap
    cap.release()
    return None


# ==================== 摄像头持有者（打开 / 重开 / 最近帧） ====================

class CameraSource:
    """一个 VideoCapture 加上它的重开策略与最近一帧，供采集线程和 HTTP 线程共享。"""

    def __init__(self, preferred=None):
        self._preferred = preferred
        self._cap = None
        self._desc = ""
        self._frame = None
        self._frame_ts = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last_error = ""
        self._sticky = ""      # 上次成功的描述，重开时优先再试它

    def request_stop(self):
        self._stop.set()

    def stopping(self):
        return self._stop.is_set()

    def _ordered_candidates(self):
        cands = candidate_devices(self._preferred)
        for i, (_, desc) in enumerate(cands):
            if desc == self._sticky:
                cands.insert(0, cands.pop(i))
                break
        return cands

    def open(self):
        """尝试打开任一候选；成功返回设备描述，失败返回 None。"""
        with self._lock:
            if self._cap is not None:
                return self._desc
        for target, desc in self._ordered_candidates():
            cap = open_device(target)
            if cap is None:
                continue
            with self._lock:
                self._cap, self._desc = cap, desc
                self._sticky = desc
                self._last_error = ""
            return desc
        with self._lock:
            self._last_error = ("未发现可用摄像头（/dev/video* 为空或全部无法打开）"
                                if IS_LINUX else "未发现可用摄像头")
        return None

    def close(self, reason=""):
        """释放句柄并丢弃缓存帧；拔出后调用，让上层重新枚举。"""
        with self._lock:
            cap, self._cap = self._cap, None
            self._desc = ""
            self._frame = None
            self._frame_ts = 0.0
            if reason:
                self._last_error = reason
        if cap is not None:
            cap.release()

    def read(self):
        with self._lock:
            cap = self._cap
        if cap is None:
            return False, None
        return cap.read()

    def set_frame(self, frame):
        with self._lock:
            self._frame = frame
            self._frame_ts = time.monotonic()

    def fresh_frame(self, max_age=FRAME_FRESH_S):
        """最近一帧仍在有效期内则返回，否则 None（设备已拔或卡住）。"""
        with self._lock:
            if self._frame is None:
                return None
            if time.monotonic() - self._frame_ts > max_age:
                return None
            return self._frame

    def status(self):
        with self._lock:
            online = self._cap is not None
            age = time.monotonic() - self._frame_ts if self._frame_ts else None
        return {
            "online": online,
            "device": self._desc,
            "frame_age_s": round(age, 2) if online and age is not None else None,
            "error": "" if online else self._last_error,
        }


# ==================== 人脸检测 ====================

class FaceDetector:
    """封装 OpenCV 级联分类器人脸检测。"""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self._cascade = None
        if enabled:
            path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._cascade = cv2.CascadeClassifier(path)
            if self._cascade.empty():
                print("[警告] 人脸检测模型加载失败，已关闭检测")
                self.enabled = False

    def detect(self, gray):
        """返回人脸矩形列表 [(x, y, w, h), ...]。"""
        if not self.enabled:
            return []
        return self._cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )

    @staticmethod
    def draw(frame, faces):
        """在帧上绘制人脸框与数量。"""
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(frame, f"Face: {len(faces)}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        return frame


# ==================== 占位帧 ====================

_PLACEHOLDER = None
_PLACEHOLDER_LOCK = threading.Lock()


def placeholder_jpeg():
    """没有实时画面时发给浏览器的一帧，避免 /video_feed 只回头就不发体。"""
    global _PLACEHOLDER
    with _PLACEHOLDER_LOCK:
        if _PLACEHOLDER is None:
            img = np.full((360, 640, 3), 40, np.uint8)
            for i, line in enumerate(("NO CAMERA", "waiting for /dev/video*")):
                cv2.putText(img, line, (50, 160 + i * 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (210, 210, 210), 2)
            ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            _PLACEHOLDER = enc.tobytes() if ok else b""
        return _PLACEHOLDER


def _multipart(jpeg):
    return (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")


# ==================== 采集循环 ====================

def stream_frames(src, detector, mode):
    """持续读帧直到断流或被要求停止。返回 True 表示用户按 q 退出程序。"""
    while not src.stopping():
        ret, frame = src.read()
        if not ret:
            print("[摄像头] 读取帧失败（设备可能已被拔出）")
            return False

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        detector.draw(frame, detector.detect(gray))
        src.set_frame(frame)

        if mode in ("local", "both"):
            cv2.imshow("Face Detection", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                return True
            if key == ord("s"):
                name = f"captured_{int(time.time())}.jpg"
                cv2.imwrite(name, frame)
                print(f"已保存 {name}")
    return False


def sleep_unless_stopping(src, seconds):
    """分段睡眠，让 Ctrl-C / 停止请求不必等满整个退避间隔。"""
    deadline = time.monotonic() + seconds
    while not src.stopping() and time.monotonic() < deadline:
        time.sleep(0.1)


def _backoff(failures):
    """连续失败越多退得越久，封顶 BACKOFF_MAX_S。"""
    return min(BACKOFF_MIN_S * (2 ** min(failures, 8)), BACKOFF_MAX_S)


def capture_loop(src, detector, mode):
    """守护循环：没设备就重试，断流就重开，自己不会退出。

    failures 统计连续失败（一个设备都没打开，或刚打开就断流），稳定出过图就归零，
    所以正常拔插是「秒级恢复」，而选错节点/供电不稳不会变成疯狂重试。
    """
    failures = 0
    while not src.stopping():
        desc = src.open()
        if desc is None:
            delay = _backoff(failures)
            print(f"[摄像头] {src.status()['error']}，{delay:.1f}s 后重试")
            sleep_unless_stopping(src, delay)
            failures += 1
            continue

        print(f"[摄像头] 已打开：{desc}")
        started = time.monotonic()
        quit_app = stream_frames(src, detector, mode)
        src.close("设备已断开，正在重新枚举")
        if quit_app or src.stopping():
            break
        failures = 0 if time.monotonic() - started >= FLAP_WINDOW_S else failures + 1
        sleep_unless_stopping(src, _backoff(failures))
    print("[摄像头] 采集线程已退出。")


# ==================== HTTP MJPEG 流 ====================

def stream_multipart(src, sleep=time.sleep):
    """产出 MJPEG 分节：有新鲜帧就发真帧，否则发占位帧。

    关键是「没有帧也要发点什么」：早先的实现只回头就不发体，浏览器既不报错
    也不重连，看起来就像摄像头没被识别到。
    """
    while not src.stopping():
        frame = src.fresh_frame()
        if frame is None:
            jpeg = placeholder_jpeg()
            if jpeg:
                yield _multipart(jpeg)
            sleep(PLACEHOLDER_INTERVAL_S)
            continue
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            sleep(PLACEHOLDER_INTERVAL_S)
            continue
        yield _multipart(encoded.tobytes())


def make_app(src, capture_alive):
    """构建 Flask 应用（仅当选择 web 模式时才 import flask）。"""
    from flask import Flask, Response, jsonify

    app = Flask(__name__)

    @app.route("/")
    def index():
        return (
            "<html><head><title>Camera Stream</title></head><body>"
            "<h2>USB 摄像头流</h2>"
            '<img src="/video_feed" style="max-width:100%">'
            '<p><a href="/health">/health</a></p>'
            "</body></html>"
        )

    @app.route("/video_feed")
    def video_feed():
        return Response(stream_multipart(src),
                        mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/snapshot")
    def snapshot():
        # 识别哨兵要把「没画面」和「画面是占位帧」区分开，所以无新鲜帧时报 503 而不是发占位帧
        frame = src.fresh_frame()
        if frame is None:
            return jsonify({"error": "摄像头当前无新鲜画面",
                            "error_en": "no fresh frame available"}), 503
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return jsonify({"error": "画面编码 JPEG 失败",
                            "error_en": "jpeg encode failed"}), 503
        resp = Response(encoded.tobytes(), mimetype="image/jpeg")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/health")
    def health():
        # 采集线程活着就 200：没插摄像头是正常等待状态，不该让容器被判死；
        # 线程死了（异常退出）才 503，好让 docker / 运维看得见。
        state = src.status()
        state["capture_alive"] = capture_alive()
        return jsonify(state), (200 if state["capture_alive"] else 503)

    return app


# ==================== 主入口 ====================

def main():
    parser = argparse.ArgumentParser(description="USB 摄像头流式传输 + 人脸检测")
    parser.add_argument("--cam", help="摄像头索引(如 0)、设备节点(如 /dev/video1)或名称(如 'Web Cam')")
    parser.add_argument("--mode", choices=["local", "web", "both"], default="both",
                        help="local=本地窗口；web=HTTP流；both=两者同时（默认）")
    parser.add_argument("--no-detect", action="store_true", help="关闭人脸检测")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP 监听地址")
    parser.add_argument("--port", type=int, default=8080, help="HTTP 端口")
    args = parser.parse_args()

    src = CameraSource(args.cam)
    detector = FaceDetector(enabled=not args.no_detect)
    print(f"[检测] 人脸检测已{'启用' if detector.enabled else '关闭'}")

    # 采集线程不因为「此刻没摄像头」而结束，所以先起服务、后插设备也能出图
    t = threading.Thread(target=capture_loop,
                         args=(src, detector, args.mode), daemon=True)
    t.start()

    if args.mode in ("web", "both"):
        app = make_app(src, lambda: t.is_alive())
        print(f"[流] HTTP 服务启动: http://{args.host}:{args.port}")
        print(f"[流] 浏览器打开 http://<本机IP>:{args.port} 查看")
        # 注意：Flask 的 reloader 需关闭，否则会重复开摄像头
        try:
            app.run(host=args.host, port=args.port, threaded=True, debug=False)
        finally:
            src.request_stop()
    else:
        # 仅 local 模式：等待采集线程结束
        try:
            while t.is_alive():
                t.join(1)
        except KeyboardInterrupt:
            pass
            src.request_stop()

    src.close()
    if args.mode in ("local", "both"):
        cv2.destroyAllWindows()
    print("已退出。")


if __name__ == "__main__":
    main()
