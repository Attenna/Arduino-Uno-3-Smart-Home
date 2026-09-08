"""USB 摄像头流式传输 + 人脸检测
====================================
通过 USB 摄像头（如 USB2.0 Web Cam）采集画面，支持两种输出模式：
  1. 本地窗口显示（--mode local）—— 开发机调试用
  2. HTTP MJPEG 流（--mode web）—— 香橙派部署用，浏览器查看

默认同时支持两种模式（有图形界面时弹本地窗口，同时起 HTTP 服务）。

用法:
    python camera_stream.py                       # 自动发现摄像头，本地窗口 + HTTP 流
    python camera_stream.py --mode web            # 仅 HTTP 流（适合香橙派无头环境）
    python camera_stream.py --mode local          # 仅本地窗口
    python camera_stream.py --no-detect           # 关闭人脸检测（纯流式传输）
    python camera_stream.py --cam 0               # 指定摄像头索引
    python camera_stream.py --cam "Web Cam"       # 指定摄像头名称
    python camera_stream.py --host 0.0.0.0 --port 8080

依赖:
    pip install opencv-python flask
"""

import argparse
import sys
import threading
import time

import cv2


# ==================== 摄像头发现 ====================

def find_camera(preferred=None):
    """尝试打开摄像头，返回 (VideoCapture, 描述)。

    优先级：用户指定(preferred) > 名称 "Web Cam" > 索引 0~4。
    """
    if preferred is not None:
        # 用户指定：可能是数字索引或名称
        if isinstance(preferred, str) and preferred.isdigit():
            preferred = int(preferred)
        cap = cv2.VideoCapture(preferred)
        if cap.isOpened():
            return cap, f"指定设备 {preferred}"
        print(f"[警告] 无法打开指定摄像头 {preferred}，回退到自动发现")

    # 先尝试名称 "Web Cam"（USB 摄像头常见名称）
    cap = cv2.VideoCapture("Web Cam")
    if cap.isOpened():
        return cap, "名称 'Web Cam'"

    # 索引回退
    for i in range(5):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            return cap, f"索引 {i}"

    return None, ""


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


# ==================== 共享帧缓冲区（线程安全） ====================

class FrameBuffer:
    """最近一帧的线程安全容器，供采集线程与 HTTP 流线程共享。"""

    def __init__(self):
        self._frame = None
        self._lock = threading.Lock()

    def set(self, frame):
        with self._lock:
            self._frame = frame

    def get(self):
        with self._lock:
            return self._frame


# ==================== 采集循环 ====================

def capture_loop(cap, detector, buf, mode, save_dir=None):
    """主采集循环：读帧 -> 检测 -> 分发（本地窗口 / HTTP 流）。"""
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            print("读取帧失败")
            time.sleep(0.1)
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector.detect(gray)
        detector.draw(frame, faces)

        # 供 HTTP 流读取
        buf.set(frame)

        # 本地窗口模式
        if mode in ("local", "both"):
            cv2.imshow("Face Detection", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("s"):
                name = f"captured_{int(time.time())}.jpg"
                cv2.imwrite(name, frame)
                print(f"已保存 {name}")

        frame_count += 1


# ==================== HTTP MJPEG 流 ====================

def make_app(buf, detector_enabled):
    """构建 Flask 应用（仅当选择 web 模式时才 import flask）。"""
    from flask import Flask, Response

    app = Flask(__name__)

    def gen():
        while True:
            frame = buf.get()
            if frame is None:
                time.sleep(0.03)
                continue
            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                continue
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")

    @app.route("/")
    def index():
        return (
            "<html><head><title>Camera Stream</title></head><body>"
            "<h2>USB 摄像头流</h2>"
            '<img src="/video_feed" style="max-width:100%">'
            "</body></html>"
        )

    @app.route("/video_feed")
    def video_feed():
        return Response(gen(),
                        mimetype="multipart/x-mixed-replace; boundary=frame")

    return app


# ==================== 主入口 ====================

def main():
    parser = argparse.ArgumentParser(description="USB 摄像头流式传输 + 人脸检测")
    parser.add_argument("--cam", help="摄像头索引(如 0)或名称(如 'Web Cam')")
    parser.add_argument("--mode", choices=["local", "web", "both"], default="both",
                        help="local=本地窗口；web=HTTP流；both=两者同时（默认）")
    parser.add_argument("--no-detect", action="store_true", help="关闭人脸检测")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP 监听地址")
    parser.add_argument("--port", type=int, default=8080, help="HTTP 端口")
    args = parser.parse_args()

    # 1. 打开摄像头
    cap, desc = find_camera(args.cam)
    if cap is None:
        print("错误：找不到任何可用摄像头")
        sys.exit(1)
    print(f"[摄像头] 已打开：{desc}")

    # 2. 人脸检测器
    detector = FaceDetector(enabled=not args.no_detect)
    if detector.enabled:
        print("[检测] 人脸检测已启用")
    else:
        print("[检测] 人脸检测已关闭")

    # 3. 共享帧缓冲
    buf = FrameBuffer()

    # 4. 启动采集线程
    t = threading.Thread(target=capture_loop,
                         args=(cap, detector, buf, args.mode), daemon=True)
    t.start()

    # 5. HTTP 流（web / both 模式）
    if args.mode in ("web", "both"):
        app = make_app(buf, detector.enabled)
        print(f"[流] HTTP 服务启动: http://{args.host}:{args.port}")
        print(f"[流] 浏览器打开 http://<本机IP>:{args.port} 查看")
        # 注意：Flask 的 reloader 需关闭，否则会重复开摄像头
        app.run(host=args.host, port=args.port, threaded=True, debug=False)
    else:
        # 仅 local 模式：等待采集线程结束
        try:
            while t.is_alive():
                t.join(1)
        except KeyboardInterrupt:
            pass

    cap.release()
    if args.mode in ("local", "both"):
        cv2.destroyAllWindows()
    print("已退出。")


if __name__ == "__main__":
    main()
