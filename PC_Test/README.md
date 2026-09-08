# PC 端工具集（PC_Test）

PC 端在电脑上通过 USB 串口直接与两块 Arduino 通信，用于**调试**、**测试**与**本地自动化**。

> 🚀 部署（含 Linux）/调试/二次开发完整指南见 **[DEPLOYMENT.md](DEPLOYMENT.md)**。

> 与 `gateway/`（Orange Pi 串口↔MQTT 网关）不同，本目录的工具**直接连串口**，不走 MQTT / Home Assistant，
> 适合在开发机上快速验证硬件与自动化逻辑。

---

## 目录结构

```text
PC_Test/
├── README.md               # 本文件（PC 端总览）
├── requirements.txt        # Python 依赖
│
├── test_serial.py          # ① 串口调试控制台（交互式，手动发命令测试硬件）
├── run_automation.py       # ② 自动化 DSL 运行器（运行 .auto 脚本）
├── oled_carousel.py        #    OLED 多行轮播模块（被 run_automation 调用）
├── camera_stream.py        # ④ USB 摄像头流式传输 + 人脸检测（本地窗口 / HTTP 流）
├── camera_test.py          #    摄像头快速自检（验证摄像头 + 检测链路）
├── link_server.py          # ③ 旧版联动服务（已过时，见下方说明）
│
└── automation/             # AST 自动化引擎核心库
    ├── __init__.py
    ├── lexer.py            # 词法分析：脚本文本 → Token
    ├── parser.py           # 语法分析：Token → AST（递归下降）
    ├── runtime.py          # 运行时：遍历 AST + 动作映射
    ├── examples/           # 示例脚本（.auto）
    │   ├── smoke_alarm.auto
    │   ├── climate_control.auto
    │   └── edge_timer.auto
    └── README.md           # DSL 语法手册（写脚本时查这里）
```

---

## 三个工具怎么选

| 工具 | 用途 | 什么时候用 |
|------|------|-----------|
| `test_serial.py` | 手动发命令测试单块板 | 排查硬件、验证某个传感器/执行器是否正常 |
| `run_automation.py` | 运行 `.auto` 自动化脚本 | 写联动规则、定时任务、OLED 轮播 |
| `camera_stream.py` | USB 摄像头流式传输 + 人脸检测 | 视频监控、人脸识别（香橙派部署用 HTTP 流） |
| `link_server.py` | 旧的硬编码规则联动 | ⚠️ 已过时，建议改用 `run_automation.py` |

---

## 环境准备

```powershell
cd PC_Test
py -3.13 -m pip install -r requirements.txt
```

> 本机 Python 环境说明：`python` 指向 msys64 的 Python（无 pip），请使用 `py -3.13`（Windows 官方 Python 3.13）。

**识别串口**（COM6 = B 板执行器，COM7 = A 板传感器，需按实际调整）：

```powershell
py -3.13 -c "import serial.tools.list_ports as p; [print(x.device, x.description) for x in p.comports()]"
```

---

## ① test_serial.py — 串口调试控制台

交互式控制台，手动发送命令测试硬件。

```powershell
# 仅 B 板（执行器）
py -3.13 test_serial.py --port-b COM6

# 仅 A 板（传感器）
py -3.13 test_serial.py --port-a COM7

# 双板 + 自动跑一轮测试
py -3.13 test_serial.py --auto-test

# 记录传感器数据到 CSV
py -3.13 test_serial.py --log sensor_log.csv
```

常用菜单命令（B 板）：

| 输入 | 作用 |
|------|------|
| `b1` | 查询状态 STATUS |
| `b9` / `b10` | 开灯 / 关灯 |
| `b7` / `b8` | 开风扇 / 关风扇 |
| `b2` / `b3` | 开门 / 关门 |
| `b12` | 蜂鸣器（短鸣/长鸣/停止） |

---

## ② run_automation.py — 自动化 DSL 运行器

用接近自然语言的 `.auto` 脚本定义自动化规则（条件、分支、计时、边沿、定时器、操作）。

```powershell
# 运行示例脚本（自动探测串口）
py -3.13 run_automation.py automation/examples/smoke_alarm.auto

# 手动指定串口
py -3.13 run_automation.py automation/examples/smoke_alarm.auto --port-a COM7 --port-b COM6

# 只跑一轮（调试用）
py -3.13 run_automation.py automation/examples/smoke_alarm.auto --once

# 启用 OLED 多行轮播（3 秒切一页）
py -3.13 run_automation.py automation/examples/edge_timer.auto --carousel

# 调整轮播间隔 / 轮询间隔
py -3.13 run_automation.py automation/examples/edge_timer.auto --carousel --carousel-interval 5 --interval 1
```

**脚本语法见 [automation/README.md](automation/README.md)**，示例脚本在 [automation/examples/](automation/examples/)。

一个最小示例：

```
规则 "烟雾报警" {
    边沿 data.smoke {
        执行 蜂鸣器.开
        执行 红灯
    }
    边沿 下降 data.smoke {
        执行 蜂鸣器.关
        执行 关灯
    }
}
```

---

## ④ camera_stream.py — USB 摄像头流式传输 + 人脸检测

通过 USB 摄像头（如 USB2.0 Web Cam）采集画面，支持人脸检测，两种输出模式：

- **本地窗口**（`--mode local`）：开发机调试用，弹 OpenCV 窗口
- **HTTP MJPEG 流**（`--mode web`）：香橙派无头部署用，浏览器查看

```powershell
# 安装依赖（仅摄像头工具需要）
py -3.13 -m pip install opencv-python flask

# 本地窗口 + HTTP 流（默认 both）
py -3.13 camera_stream.py

# 香橙派无头环境：仅 HTTP 流（在浏览器访问 http://<香橙派IP>:8080）
py -3.13 camera_stream.py --mode web --host 0.0.0.0 --port 8080

# 关闭人脸检测（纯流式传输）
py -3.13 camera_stream.py --no-detect

# 指定摄像头
py -3.13 camera_stream.py --cam 0            # 按索引
py -3.13 camera_stream.py --cam "Web Cam"    # 按名称
```

**交互按键**（本地窗口模式）：

| 按键 | 作用 |
|------|------|
| `q` | 退出 |
| `s` | 保存当前帧为 `captured_<时间戳>.jpg` |

**摄像头发现策略**：用户指定 > 名称 `"Web Cam"` > 索引 `0~4` 依次尝试。

**快速自检**（先确认摄像头可用再上流）：

```powershell
py -3.13 camera_test.py              # 自动发现摄像头，读 5 帧
py -3.13 camera_test.py --cam 0 --frames 10
```

> 香橙派部署提示：`--mode web` 会用 Flask 起 MJPEG 流，浏览器打开 `http://<香橙派IP>:8080` 即可实时查看，
> 无需图形界面。HTTP 服务与摄像头采集在不同线程运行，互不阻塞。

---

## ③ link_server.py — 旧版联动服务（已过时）

> ⚠️ **建议改用 `run_automation.py`**。本脚本用硬编码的 `RULES` 列表实现联动，
> 逻辑与代码耦合，改规则需要改 Python 代码；新方案用 `.auto` 脚本解耦，可读可维护。

仅作历史参考保留，不再维护。

---

## 常见问题

### 串口被占用（PermissionError / 拒绝访问）

串口同一时刻只能被一个程序打开。若报 `拒绝访问`，先关闭其他占用串口的程序（包括之前启动的 Python 进程）。

### 命令发送过快导致错位

OLED 轮播连发多行命令时，若 B 板固件处理不过来会导致命令错位。已在 `oled_carousel.py` 中内置**逐行 30ms 节流** + **仅发送变化行**，正常使用即可。

### B 板 JSON 命令 parse_error

B 板固件当前存在 JSON 解析 bug（所有 JSON 命令返回 `parse_error`），因此 DSL 动作统一降级为**文本命令**（`B:XXX` 格式），已实测全部正常。详见 [automation/README.md](automation/README.md) 的操作映射表。

---

## 与其它模块的关系

```text
                    ┌─────────────┐
                    │  PC_Test    │  本目录：直接串口，用于调试与本地自动化
                    └─────────────┘
                           │ USB 串口
              ┌────────────┴────────────┐
              │  Module A（传感器）      │  Module B（执行器）
              └─────────────────────────┘

生产部署走 gateway/（串口↔MQTT）+ Home Assistant，见根目录 README。
```
