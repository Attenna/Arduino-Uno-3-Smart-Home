# PC_Test — PC 端工具集 部署与二次开发指南

> 面向：把 PC 端工具（串口调试控制台、积木自动化引擎、摄像头流）在 **Linux** 上运行、
> 接线调试、二次开发。
> 使用总览见 [README.md](README.md)；积木自动化扩展见 [web/automation/](web/automation/)。

**功能一句话**：PC 直接连 USB 串口调试 Arduino 双板；自动化统一走 Web 积木引擎（`/automation` 页面，经 voice 容器 `POST /tool` 下发硬件，不依赖 MQTT/HA）；也能起 USB 摄像头 MJPEG 流。

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

# ② 摄像头快速自检 / 流式传输
python camera_test.py
python camera_stream.py --mode web --host 0.0.0.0 --port 8080
```

> 与 Windows 的差异仅在设备名（`/dev/ttyUSB*` 而非 `COMx`）与 Python 命令（`python3`/venv 而非 `py -3.13`）。
>
> **自动化统一入口**：联动规则走 Web 积木引擎——启动 `run_web.py --no-serial`（经 voice 容器 `POST /tool` 下发硬件）后访问 `http://<IP>:5000/automation`。
> 历史 `.auto` 文本 DSL、`run_automation.py`、`link_server.py` 已移除。

---

## 2. 设备安装与连接

| 工具 | 需连接设备 | 连接方式 |
|------|-----------|---------|
| `test_serial.py` | Module A 或 B | USB 数据线连串口 |
| `camera_test.py` / `camera_stream.py` | USB 摄像头 | USB2.0 Web Cam 即插即用 |

接线细节（传感器/执行器到板）见对应板目录 [../module-a-sensor/DEPLOYMENT.md](../module-a-sensor/DEPLOYMENT.md)、[../module-b-output/DEPLOYMENT.md](../module-b-output/DEPLOYMENT.md)。

> 自动化规则无需直连串口：由 web 容器积木引擎经 voice 容器 `POST /tool` 下发到 Module B。

---

## 3. 调试方法

### 3.1 常见调试流程

```bash
# 1. 列出串口与摄像头
python -c "import serial.tools.list_ports as p; [print(x.device, x.description) for x in p.comports()]"
python camera_test.py

# 2. 手动测试 B 板（interactive 菜单 b1/b9/b12...）
python test_serial.py --port-b /dev/ttyUSB1

# 3. 自动化：在 Web /automation 页用积木编排规则（无需直连串口）
```

### 3.2 已知问题

- **命令错位**：OLED 文本连续下发过快会被 B 板串口打乱。积木引擎里的 OLED 动作按行节流下发；仍错位可降低动作数量或延长 `delay` 块。
- **B 板 JSON parse_error**：执行器动作统一降级为文本命令 `B:XXX`（由 MCP 工具封装），无需处理。

---

## 4. 二次开发定义（积木自动化引擎）

自动化规则全部统一到 Web 积木引擎 `PC_Test/web/automation/`：

```text
面板(Blockly) ─▶ 规则JSON(schema.py) ─▶ 引擎(engine.py) ─▶ bridge(relay→voice /tool) ▶ Module B
     传感器快照(SENSOR:)、事件(EVENT:)、人脸授权 ─▶ 引擎注入(边沿/条件/冷却)
```

- `capabilities.py`   积木下拉的能力清单（传感器/事件/比较符/执行器），前端与校验共用
- `schema.py`         规则 JSON 模型与校验（触发/条件/那么/否则/冷却）
- `engine.py`         规则引擎：触发沿、持续秒数、条件组合、动作线程、防重入、记录
- `default_rules.py`  内置默认规则积木（高温控风扇、光敏调光、雨水关窗、烟雾报警、人脸开门、离家关全屋、按键/红外切换等），可增删/停用
- `home_mode.py`      全屋模式状态机（auto/manual/away + 风扇/灯光档位覆盖）
- `oled_carousel.py`  OLED 轮播（扁平数据源 + 内容去重）

### 4.2 常用扩展点

| 需求 | 改哪里 |
|------|--------|
| 新增传感器/状态积木 | `capabilities.py` 的 `CONDITION_SOURCES` 加一项（后端校验自动跟随） |
| 新增执行器积木 | `capabilities.py` 的 `ACTION_DEVICES` + `engine._perform` 加分支 |
| 加入默认规则 | `default_rules.py` 追加一条 `preset` 并 `PRESETS_VERSION += 1` |
| 组合触发/条件积木 | Blockly 页面直接编排「当→如果→那么/否则」，无需改代码 |

### 4.3 相关文档

- 工具总览：[README.md](README.md)
- 串口协议：[docs/serial-protocol.md](../docs/serial-protocol.md)
