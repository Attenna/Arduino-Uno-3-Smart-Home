"""摄像头快速自检 —— 验证摄像头是否可用 + 人脸检测是否正常。

用法:
    python camera_test.py              # 自动发现摄像头
    python camera_test.py --cam 0      # 指定摄像头索引
    python camera_test.py --frames 10  # 读取帧数

读几帧并打印分辨率与人脸数量，快速判断摄像头硬件与检测链路是否正常。
"""

import argparse
import time

import cv2

from camera_stream import find_camera, FaceDetector


def main():
    parser = argparse.ArgumentParser(description="摄像头快速自检")
    parser.add_argument("--cam", help="摄像头索引(如 0)或名称(如 'Web Cam')")
    parser.add_argument("--frames", type=int, default=5, help="读取帧数(默认5)")
    args = parser.parse_args()

    cap, desc = find_camera(args.cam)
    if cap is None:
        print("错误：找不到任何可用摄像头")
        return 1

    print(f"[摄像头] 已打开：{desc}")
    det = FaceDetector(enabled=True)
    print(f"[检测] 人脸检测：{'启用' if det.enabled else '关闭'}")

    ok = 0
    for i in range(args.frames):
        ret, frame = cap.read()
        if not ret:
            print(f"  第{i + 1}帧读取失败")
            time.sleep(0.2)
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = det.detect(gray)
        print(f"  帧 {frame.shape[1]}x{frame.shape[0]}, 检测到 {len(faces)} 张人脸")
        ok += 1
        time.sleep(0.2)

    cap.release()
    print(f"\n结果：成功读取 {ok}/{args.frames} 帧")
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
