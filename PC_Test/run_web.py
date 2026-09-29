"""Web 仪表盘服务入口。

用法：
    py -3.13 run_web.py                      # 读 web_config.yaml，自动探测串口
    py -3.13 run_web.py --no-serial          # 不连硬件，纯看板/演示（人脸可用模拟）
    py -3.13 run_web.py --port-a COM7 --port-b COM6 --port 5000

架构：本进程不直接开串口，而是以 MCP stdio client 方式拉起 mcp_home_server.py
（与 voice_assistant 相同的单进程串口约束），因此不能与语音模式同时运行。
"""
import argparse
import logging

from web import create_app
from web.config import load_config


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="智能家居 Web 仪表盘服务")
    parser.add_argument("--host", help="监听地址（覆盖 web_config.yaml）")
    parser.add_argument("--port", type=int, help="HTTP 端口（覆盖配置）")
    parser.add_argument("--port-a", help="Module A 传感器串口，auto=探测")
    parser.add_argument("--port-b", help="Module B 执行器串口，auto=探测")
    parser.add_argument("--no-serial", action="store_true",
                        help="不拉 MCP 串口子进程（纯看板/演示模式）")
    args = parser.parse_args()

    cfg = load_config()
    if args.host:
        cfg["server"]["host"] = args.host
    if args.port:
        cfg["server"]["port"] = args.port
    if args.port_a:
        cfg["serial"]["port_a"] = args.port_a
    if args.port_b:
        cfg["serial"]["port_b"] = args.port_b
    if args.no_serial:
        cfg["serial"]["enabled"] = False

    app = create_app(cfg)

    host = cfg["server"]["host"]
    port = int(cfg["server"]["port"])
    print("=" * 56)
    print("  智能家居 Web 仪表盘启动中...")
    print(f"  请访问: http://localhost:{port}")
    if cfg["serial"]["enabled"]:
        print("  硬件链路: MCP 子进程独占 A/B 串口（请勿同时运行语音模式）")
    else:
        print("  硬件链路: 已禁用 (--no-serial)，设备控制将返回 503")
    print("=" * 56)
    # threaded + 关闭 reloader：保证 MCP 子进程只拉起一次，摄像头/轮询不被重复初始化
    app.run(host=host, port=port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
