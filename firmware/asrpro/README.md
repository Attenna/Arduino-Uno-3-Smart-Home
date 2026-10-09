# ASRPRO V2.0 + 香橙派语音控制

`smart_home.cpp` 是天问 Block AI 的 ASRPRO 字符编程源代码。
香橙派运行 `PC_Test/asrpro_bridge.py`：ASRPRO 板载 Type-C/CH340 → USB 串口 →
香橙派桥接进程 → 已认证 Web 硬件网关 → A/B 板。
仅烧录 C++ 而没有启动桥接进程时，设备会提示等待回复超时。

## 1. 接线

本版本使用 ASRPRO 开发板板载 Type-C/CH340 对应的默认 `Serial`（UART0），
波特率 115200、8N1。使用支持数据传输的 USB 线连接到香橙派 **USB Host** 口；
若 Type-C 对 Type-C 连接后 `lsusb` 没有出现 CH340，请改用香橙派 USB-A Host 口和
USB-A 转 Type-C 数据线。仅供电的 Type-C 口或充电线不能工作。

连接成功后，香橙派应新增一个 CH340 和 `/dev/ttyUSB*`，同时保留两块 Arduino 的
`/dev/ttyACM0`、`/dev/ttyACM1`。不得将任一 `ttyACM` 配置给 ASRPRO 桥接服务。
ASRPRO 的 PA2/PA3 不再需要外接，现有 A/B 板继续使用各自的串口。

## 2. 在天问 Block AI 烧录

1. 主板选择 **ASRPRO**，进入字符/C++ 编程模式。
2. 将同目录 `smart_home.cpp` 的全部内容复制到主程序，替换示例代码。
3. 保留 `//{ID:...}` 和 `//{playid:...}` 注释：这是语音模型配置，不是可删除的普通注释。
4. 点击 **生成模型**。必须包含 ID 0–9、201–214、10001/10002 和 10084–10100 数字播报资源。
5. 模型生成成功后，根据实际板卡 Flash 容量选择烧录设置，再执行 **编译下载**。
6. 说“智能管家”，听到“我在”后说下表中的口令。

代码已按本机 `D:\twenblock\asrpro` SDK 接口编写；语音模型生成需要在天问软件中完成。
编译器的源文件/目标文件检查不等于模型生成、固件整包链接和硬件烧录成功。

| 命令 ID | 口令 | 行为 |
|---|---|---|
| 1 | 开灯 | 白光，亮度 255 |
| 2 | 关灯 | 关闭灯光 |
| 3 | 开门 | 执行开门指令 |
| 4 | 开窗 | 执行开窗指令 |
| 5 | 开风扇 | 风扇全速 |
| 6 | 关风扇 | 停止风扇 |
| 7 | 当前温度 | 播报 A 板最新有效温度 |
| 8 | 当前湿度 | 播报 A 板最新有效湿度 |
| 9 | 现在几点 | 播报香橙派系统时间，固定 UTC+8 |

ASRPRO 本身不联网校时，也不直接测量温湿度。香橙派系统时钟应已同步。
传感器离线、无效值、鉴权失败和网关错误均不播报成功。
门窗回复表示控制器接受并执行指令，不代表存在机械到位传感器。
一条指令尚未结束时不排队执行新口令。超时不自动重发；请先确认设备状态。

## 3. 香橙派安装桥接进程

按仓库流程完成 PR 审查、合并和 `scripts/sync_orangepi.ps1` 同步后，在活动目录操作。
不修改现有 Docker 编排，桥接服务在宿主机运行，访问宿主机 5000 端口。

```bash
cd /home/HwHiAiUser/smart-home
python3 -m venv /home/HwHiAiUser/.venvs/asrpro
/home/HwHiAiUser/.venvs/asrpro/bin/pip install pyserial==3.5
ls -l /dev/serial/by-id/
```

识别新增 CH340 的稳定路径，不要选 A/B 板端口。
如果多个同型号适配器没有唯一序列号，使用 `/dev/serial/by-path/` 对应固定 USB 插口。
源码检出环境在 `PC_Test/.auth.asrpro.env` 中配置以下两项；部署脚本会将
`PC_Test` 内容平铺到 `/home/HwHiAiUser/smart-home`，因此香橙派运行时文件为
`/home/HwHiAiUser/smart-home/.auth.asrpro.env`。文件权限设为 `600`：

```text
ASRPRO_PORT=/dev/serial/by-id/替换为ASRPRO适配器实际名称
SMART_HOME_SERVICE_TOKEN=与现有Web服务相同的服务令牌
```

从现有部署认证配置安全复制服务令牌，不要生成一个与 Web 不一致的新令牌，
也不要将令牌粘贴到聊天、命令行参数、Git 或文档中。此文件已由仓库 `.auth*` 规则忽略。

安装同目录的 systemd 单元（需要系统管理权限）：

```bash
sudo install -m 644 firmware/asrpro/asrpro-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now asrpro-bridge
systemctl status asrpro-bridge
journalctl -u asrpro-bridge -n 30 --no-pager
```

USB 拔出后进程会等待并重连，不重试已经发出的控制请求。
首次接线、语音模型下载及设备选口完成前，不应将服务视为已可用。
回滚时先 `sudo systemctl disable --now asrpro-bridge`，再按仓库流程回滚代码。

## 4. 串口协议与测试

外部串口输入、通用意图注册与场景扩展的**接口规范**见
[ASRPRO 串口控制接口规范](../../docs/asrpro-serial-control.md)。`SH1` 1–9 号行为不变；
`SH2` 意图白名单（`light`/`door`/`window`/`fan`/`buzzer`/`ac`/`status`）已在香橙派
`asrpro_bridge.py` 落地，但**本固件仍只发 SH1**，升级到 SH2 随场景一并实施。

115200、8N1、ASCII、换行结尾，每次只有一个请求在途：

```text
SH1 12 7
SH1 12 7 TEMP 2530 0
```

请求：`SH1 请求编号 命令ID`。响应：`SH1 请求编号 命令ID 类型 数值A 数值B`。
类型为 OK、ERR、TEMP、HUM、TIME。温湿度值为实际值乘 100；TIME 为小时/分钟。
固件核对编号与命令后才播放，超长帧整帧丢弃；不是任意文本 TTS 协议。
不要从串口终端发送控制帧做连通性测试，以免触发执行器；只读测试可用 ID 9。

独立 Python 环境中，从仓库根目录运行（Windows 先设置 `$env:PYTHONPATH='PC_Test'`）：

```bash
PYTHONPATH=PC_Test python -m unittest discover -s PC_Test/tests -v
python -m compileall PC_Test/asrpro_bridge.py PC_Test/tests/test_asrpro_bridge.py
```

测试使用模拟网关与临时数据库，不打开真实串口。实机还需验证语音识别、音频顺序、
USB 插拔、传感器断线、开关动作与时间播报。
