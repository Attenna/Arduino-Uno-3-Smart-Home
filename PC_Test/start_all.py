"""一键启动「语音助手 + 人脸识别 Web + 摄像头视频流」联动栈
================================================================
一次拉起 4 个进程（串口归语音助手独占，Web 以 --no-serial 看板模式运行，
硬件控制/人脸自动开门经语音助手的 POST /tool 静默转发）：

    1. qwen_server.py       本地 LLM（llm-mode=local 时；:8000）
    2. voice_assistant.py   语音助手，独占 A/B 串口（:8101，含 POST /tool）
    3. run_web.py --no-serial  人脸 YOLO+ArcFace + 仪表盘（:5000）
    4. camera_stream.py     USB 摄像头 MJPEG 流（:8080）

用法（在 PC_Test 目录下）:
    py -3.13 start_all.py                     # 全部启动（推荐）
    py -3.13 start_all.py --port-a COM7 --port-b COM6 --cam 0
    py -3.13 start_all.py --llm-mode dashscope --api-key sk-xxx
    py -3.13 start_all.py --camera-mode both  # 摄像头同时弹本地窗口
    py -3.13 start_all.py --no-camera         # 不起摄像头

退出：本窗口按 Ctrl+C，会 taskkill 整个进程树（含 mcp_home_server 子进程），
不留孤儿。各服务实时日志在 logs/ 下（qwen.log / voice.log / web.log / camera.log）。
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PC_TEST_DIR = Path(__file__).resolve().parent
LOGS_DIR = PC_TEST_DIR / "logs"
PY = sys.executable

# (名称, 默认端口, 就绪探测路径)
_PROCESSES: dict[str, subprocess.Popen] = {}


def log(msg: str) -> None:
    print(f"[start_all] {msg}", flush=True)


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_ready(name: str, port: int, path: str, timeout: float,
               optional: bool = False) -> bool:
    """轮询 HTTP 端口直到 200；进程提前退出则判定失败。"""
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}{path}"
    while time.time() < deadline:
        proc = _PROCESSES.get(name)
        if proc is not None and proc.poll() is not None:
            log(f"!! {name} 进程已退出（code={proc.returncode}），见 logs/{name}.log")
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    log(f"✓ {name} 已就绪（{url}）")
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(1.0)
    tag = "（可选项，继续）" if optional else ""
    log(f"!! {name} 在 {timeout:.0f}s 内未就绪{tag}，见 logs/{name}.log")
    return False


def spawn(name: str, args: list[str], env_extra: dict | None = None) -> subprocess.Popen:
    LOGS_DIR.mkdir(exist_ok=True)
    log_path = LOGS_DIR / f"{name}.log"
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if env_extra:
        env.update(env_extra)
    log(f"启动 {name}: {PY} {' '.join(args)}（日志 logs/{name}.log）")
    # stdout/stderr 写文件（避免 PIPE 缓冲写满导致子进程阻塞）
    log_fp = open(log_path, "ab")  # noqa: SIM115 — 随父进程退出关闭
    return subprocess.Popen(
        [PY, "-u"] + args,
        cwd=str(PC_TEST_DIR),
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        env=env,
    )


def taskkill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        # Windows：/T 连子进程树一起结束（mcp_home_server / llama.cpp 子进程）
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True, check=False)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def cleanup() -> None:
    if not _PROCESSES:
        return
    log("正在停止全部服务…")
    for name, proc in _PROCESSES.items():
        taskkill_tree(proc)
    for name, proc in _PROCESSES.items():
        try:
            proc.wait(timeout=8)
        except Exception:
            log(f"!! {name} 未能在 8s 内退出")
    _PROCESSES.clear()
    log("全部服务已停止。")


def main() -> int:
    p = argparse.ArgumentParser(description="语音 + 人脸识别 Web + 摄像头流 一键启动")
    p.add_argument("--port-a", help="Module A 串口（传给语音助手，如 COM7）")
    p.add_argument("--port-b", help="Module B 串口（传给语音助手，如 COM6）")
    p.add_argument("--mic-index", type=int, help="麦克风设备索引（传给语音助手）")
    p.add_argument("--llm-mode", choices=["local", "dashscope"], default="local")
    p.add_argument("--api-key", help="dashscope 模式 API Key")
    p.add_argument("--cam", help="摄像头索引(0)或名称('Web Cam')，传给 camera_stream")
    p.add_argument("--camera-mode", choices=["local", "web", "both"], default="web",
                   help="摄像头输出模式，默认 web（无头环境友好）")
    p.add_argument("--llm-port", type=int, default=8000)
    p.add_argument("--voice-port", type=int, default=8101)
    p.add_argument("--web-port", type=int, default=5000)
    p.add_argument("--camera-port", type=int, default=8080)
    p.add_argument("--no-qwen", action="store_true", help="外部已运行 LLM 服务，不再拉起")
    p.add_argument("--no-voice", action="store_true")
    p.add_argument("--no-web", action="store_true")
    p.add_argument("--no-camera", action="store_true")
    args = p.parse_args()

    want_qwen = (not args.no_voice and not args.no_qwen
                 and args.llm_mode == "local")
    want_voice = not args.no_voice
    want_web = not args.no_web
    want_camera = not args.no_camera

    # 1. 端口占用预检
    planned = []
    if want_qwen:
        planned.append(("qwen_server", args.llm_port))
    if want_voice:
        planned.append(("voice_assistant", args.voice_port))
    if want_web:
        planned.append(("run_web", args.web_port))
    if want_camera:
        planned.append(("camera_stream", args.camera_port))
    for svc, port in planned:
        if port_in_use(port):
            log(f"!! 端口 {port} 已被占用（{svc} 需要）。请先停掉占用进程，或用对应参数改端口。")
            return 1

    # 2. 依次拉起
    try:
        if want_qwen:
            _PROCESSES["qwen"] = spawn("qwen", ["qwen_server.py"])

        if want_voice:
            va_args = ["voice_assistant.py", "--llm-mode", args.llm_mode]
            if args.port_a:
                va_args += ["--port-a", args.port_a]
            if args.port_b:
                va_args += ["--port-b", args.port_b]
            if args.mic_index is not None:
                va_args += ["--mic-index", str(args.mic_index)]
            if args.api_key:
                va_args += ["--api-key", args.api_key]
            _PROCESSES["voice"] = spawn("voice", va_args)

        if want_web:
            web_args = ["run_web.py", "--no-serial", "--port", str(args.web_port)]
            # 人脸开门/设备控制经语音助手 /tool 转发（不抢串口）
            relay_env = {"SMART_HOME_HW_RELAY": f"http://127.0.0.1:{args.voice_port}"}
            _PROCESSES["web"] = spawn("web", web_args, env_extra=relay_env)

        if want_camera:
            cam_args = ["camera_stream.py",
                        "--mode", args.camera_mode,
                        "--port", str(args.camera_port)]
            if args.cam:
                cam_args += ["--cam", args.cam]
            _PROCESSES["camera"] = spawn("camera", cam_args)
    except Exception as e:
        log(f"!! 启动失败: {e}")
        cleanup()
        return 1

    # 3. 就绪等待（按依赖顺序；LLM 加载模型较慢给 120s）
    if want_qwen:
        wait_ready("qwen", args.llm_port, "/v1/models", timeout=120)
    if want_voice:
        wait_ready("voice", args.voice_port, "/state", timeout=120)
    if want_web:
        wait_ready("web", args.web_port, "/api/health", timeout=90)
    if want_camera:
        cam_ok = wait_ready("camera", args.camera_port, "/", timeout=25, optional=True)
        if not cam_ok:
            log("（摄像头不可用不影响其它服务；调试可看 logs/camera.log）")

    # 4. 常驻等待
    print("=" * 60, flush=True)
    print("  联动栈已启动：", flush=True)
    if want_web:
        print(f"    🌐 仪表盘 / 人脸识别 : http://localhost:{args.web_port}", flush=True)
    if want_camera:
        print(f"    📷 摄像头视频流       : http://localhost:{args.camera_port}", flush=True)
    if want_voice:
        print(f"    🎤 语音助手控制台     : http://localhost:{args.voice_port}", flush=True)
    if want_qwen:
        print(f"    🧠 本地 LLM           : http://localhost:{args.llm_port}/v1", flush=True)
    print("  按 Ctrl+C 停止全部服务（日志在 logs/ 目录）", flush=True)
    print("=" * 60, flush=True)

    try:
        while True:
            for name, proc in list(_PROCESSES.items()):
                if proc.poll() is not None:
                    log(f"!! {name} 已退出（code={proc.returncode}），其它服务继续运行")
                    del _PROCESSES[name]
            if not _PROCESSES:
                log("所有服务均已退出。")
                break
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
