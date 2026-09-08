# PC_Test — PC 端工具集 部署与二次开发指南

> 面向：把 PC 端工具（串口调试控制台、自动化 DSL 引擎、OLED 轮播、摄像头流）在 **Linux** 上运行、
> 接线调试、二次开发。
> 使用总览见 [README.md](README.md)；DSL 语法见 [automation/README.md](automation/README.md)。

**功能一句话**：PC 直接连 USB 串口调试 Arduino 双板，或跑 `.auto` 脚本做本地自动化（不依赖 MQTT/HA）；也能起 USB 摄像头 MJPEG 流。

---

## 1. Linux 部署

### 1.1 安装 Python 与依赖

```bash
cd PC_Test
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # pyserial

# 摄像头工具需要额外依赖（可选）
pip install opencv-python flask
```

### 1.2 串口权限

```bash
sudo usermod -a -G dialout $USER && newgrp dialout
ls /dev/ttyUSB* /dev/ttyACM*          # 确认设备
```

### 1.3 运行各工具

```bash
# ① 串口调试控制台（B 板）
python test_serial.py --port-b /dev/ttyUSB1

# ② 自动化 DSL（A板+B板）
python run_automation.py automation/examples/smoke_alarm.auto \
  --port-a /dev/ttyUSB0 --port-b /dev/ttyUSB1

# ③ OLED 轮播（带执行器状态页，需周期性查询 B 板状态）
python run_automation.py automation/examples/edge_timer.auto \
  --port-a /dev/ttyUSB0 --port-b /dev/ttyUSB1 --carousel

# ④ 摄像头快速自检 / 流式传输
python camera_test.py
python camera_stream.py --mode web --host 0.0.0.0 --port 8080
```

> 与 Windows 的差异仅在设备名（`/dev/ttyUSB*` 而非 `COMx`）与 Python 命令（`python3`/venv 而非 `py -3.13`）。

---

## 2. 设备安装与连接

| 工具 | 需连接设备 | 连接方式 |
|------|-----------|---------|
| `test_serial.py` | Module A 或 B | USB 数据线连串口 |
| `run_automation.py` | Module A + Module B（双板） | 两根 USB 线；A=--port-a，B=--port-b |
| `camera_test.py` / `camera_stream.py` | USB 摄像头 | USB2.0 Web Cam 即插即用 |

接线细节（传感器/执行器到板）见对应板目录 [../module-a-sensor/DEPLOYMENT.md](../module-a-sensor/DEPLOYMENT.md)、[../module-b-output/DEPLOYMENT.md](../module-b-output/DEPLOYMENT.md)。

> 若只有单板：`run_automation.py` 支持缺省 — `--port-a` 或 `--port-b` 只给其一，脚本会单板运行（动作发给已连接的板）。

---

## 3. 调试方法

### 3.1 常见调试流程

```bash
# 1. 列出串口与摄像头
python -c "import serial.tools.list_ports as p; [print(x.device, x.description) for x in p.comports()]"
python camera_test.py

# 2. 手动测试 B 板（interactive 菜单 b1/b9/b12...）
python test_serial.py --port-b /dev/ttyUSB1

# 3. 单轮跑自动化验证规则
python run_automation.py automation/examples/smoke_alarm.auto --once --port-a ... --port-b ...
```

### 3.2 已知问题

- **命令错位**：OLED 轮播连发多行若过快会被 B 板串口打乱。`oled_carousel.py` 已内置逐行 30ms 节流 + 仅发送变化行；仍错位可调 `line_delay`。
- **B 板 JSON parse_error**：B 板固件 JSON 命令有 bug，DSL 已自动降级为文本命令 `B:XXX`，无需处理。

---

## 4. 二次开发定义

### 4.1 整体架构

```text
.auto 脚本 ──▶ Lexer(token) ──▶ Parser(AST) ──▶ Runtime(执行) ──▶ 动作映射 ──▶ 文本命令 → 串口
```

- `automation/lexer.py`  词法分析
- `automation/parser.py` 语法分析（AST 节点）
- `automation/runtime.py` 解释执行 + `ACTION_MAP`（动作→文本命令）
- `run_automation.py`    入口（串口/轮播/主循环）
- `oled_carousel.py`     OLED 轮播（与 AST 引擎独立）

### 4.2 DSL 语法速查（详见 automation/README.md）

```
规则 "名称" { 语句 }
当 条件 { }         如果 条件 { } 否则 { }
执行 <动作>         等待 2 秒          设置 x = 1
边沿 <字段> { }     边沿 下降 <字段> { }    每 N 秒 { }   定时 N 秒 { }
```

### 4.3 常用扩展点

| 需求 | 改哪里 |
|------|--------|
| 新增动作（如继电器） | `automation/runtime.py` 的 `ACTION_MAP` 加一行别名 → `B:RELAY:ON` 之类文本命令 |
| 新增 DSL 语句 | `parser.py` 加 AST 节点与解析分支 + `runtime.py` 加 `_exec` 分支 |
| 新传感器字段直接判断 | 脚本写 `data.<字段>` 即可，无需改代码 |
| 自定义 OLED 轮播页 | `oled_carousel.py` 的 `DEFAULT_PAGES` |
| 新增串口工具行为 | 以 `run_automation.py` 为模板复制改造 |

### 4.4 二次开发约定

- 复用 `automation/` 包：`from automation.parser import parse`、`from automation.runtime import Runtime`，把 `Runtime(emitter=...)` 的 emitter 指向你自己的发送函数即可在别的项目复用。
- 动作映射默认发 B 板文本命令（`B:XXX`）；如 B 板固件 JSON bug 修复后，想切回 JSON，把 `ACTION_MAP` 值改为发 `{"cmd":...}` 的函数即可（emitter 同时支持文本/JSON）。

### 4.5 相关文档

- DSL 语法手册：[automation/README.md](automation/README.md)
- 工具总览：[README.md](README.md)
- 串口协议：[docs/serial-protocol.md](../docs/serial-protocol.md)
