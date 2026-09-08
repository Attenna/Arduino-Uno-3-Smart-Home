# Gateway — 串口 ↔ MQTT 网关 部署与二次开发指南

> 面向：在 **Orange Pi（Linux / ARM）** 上部署本网关，把两块 Arduino 接入 MQTT / Home Assistant。
> 基础信息见 [README.md](README.md) 与 [docs/architecture.md](../docs/architecture.md)。

**功能一句话**：两个独立 Python 进程做纯协议转换，不做业务决策：
- `sensor_gateway.py`：读 Module A 串口 JSON → 发布 MQTT
- `output_gateway.py`：订阅 MQTT 命令 → 写 Module B 串口；回传响应/状态

---

## 1. Linux 部署（Orange Pi）

### 1.1 环境

建议 Python 3.9+。Orange Pi 多数系统自带 `python3`；若为精简系统先装：

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv
```

### 1.2 创建虚拟环境并装依赖

```bash
cd gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt     # pyserial + paho-mqtt
```

> 若编译慢，可加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 换国内源。

### 1.3 串口权限与设备识别

```bash
# 权限
sudo usermod -a -G dialout $USER && sudo reboot   # 或重启会话

# 识别哪块板在哪个串口（看 ready 消息的 board 字段）
sudo apt install -y picocom
picocom -b 115200 /dev/ttyUSB0      # 上电应看到 MODULE_A 或 MODULE_B 的 ready
```

通常：Module A = `/dev/ttyUSB0`，Module B = `/dev/ttyUSB1`（以实际为准，可互换）。

> 为固定设备名，可写 udev 规则绑定（按 USB 序列号），避免每次拔插顺序变化：
> `/etc/udev/rules.d/99-arduino.rules` 中按 `ATTRS{serial}` 映射为 `/dev/module_a`、`/dev/module_b`。

### 1.4 环境变量（覆盖默认值）

```bash
export SENSOR_PORT=/dev/ttyUSB0     # Module A 串口
export OUTPUT_PORT=/dev/ttyUSB1     # Module B 串口
export BAUD=115200
export MQTT_HOST=localhost          # Mosquitto 地址
export MQTT_PORT=1883
```

### 1.5 手动启动（先验证）

```bash
# 终端1：传感器网关
python src/sensor_gateway.py

# 终端2：执行器网关
python src/output_gateway.py
```

看到类似输出即正常：
```
[sensor_gateway] 监听 /dev/ttyUSB0 @ 115200 -> MQTT localhost:1883
[output_gateway] 已订阅 smarthome/output/command
```

### 1.6 用 systemd 托管为开机服务（推荐）

为每个进程各写一个 unit，或用一个 unit 跑两个进程（此处用 `&` 简单方案）。示例 `/etc/systemd/system/smarthome-gateway.service`：

```ini
[Unit]
Description=SmartHome Gateway (serial <-> MQTT)
After=network.target mosquitto.service
Wants=mosquitto.service

[Service]
User=orangepi
WorkingDirectory=/opt/Arduino-Uno-3-Smart-Home/gateway
Environment=SENSOR_PORT=/dev/ttyUSB0
Environment=OUTPUT_PORT=/dev/ttyUSB1
Environment=MQTT_HOST=localhost
ExecStart=/opt/Arduino-Uno-3-Smart-Home/gateway/.venv/bin/python /opt/Arduino-Uno-3-Smart-Home/gateway/run_both.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

其中 `run_both.py` 可简化为两个进程的后台拉起（或用两个独立 unit）。启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now smarthome-gateway
journalctl -u smarthome-gateway -f    # 看日志
```

> 仓库默认按「串口已由系统分配」假设；若两块板供电不稳导致掉线，可加 `Restart=always`（已含）与硬件复位/看门狗。

---

## 2. 设备安装与连接

### 2.1 连接拓扑

```text
Module A (USB) ──/dev/ttyUSB0──▶ sensor_gateway.py ──▶ MQTT smarthome/sensor/data & /event ──▶ Home Assistant
Module B (USB) ──/dev/ttyUSB1──◀ output_gateway.py ◀── MQTT smarthome/output/command ◀── Home Assistant
                                     │
                                     └──▶ smarthome/output/response & /state
```

### 2.2 MQTT Broker（Mosquitto）

本仓库用 Docker 起 Mosquitto（见 `docker/compose.yaml`）。若想原生安装：

```bash
sudo apt install -y mosquitto
sudo systemctl enable --now mosquitto
# 默认监听 1883，允许匿名（内网用）
```

### 2.3 连线清单

| 端口 | 接哪块板 | 需先确认 |
|------|---------|---------|
| `/dev/ttyUSB0` | Module A（传感器） | 上电 ready 含 `MODULE_A` |
| `/dev/ttyUSB1` | Module B（执行器） | 上电 ready 含 `MODULE_B` |

两板与 Orange Pi 之间只用 **USB 数据线**（无额外电气接线）。

---

## 3. 调试方法

### 3.1 看串口侧原始数据

```bash
# A 板（应周期性看到 data JSON）
picocom -b 115200 /dev/ttyUSB0

# B 板（手动发命令）
echo 'B:LIGHT:RED' > /dev/ttyUSB1
```

### 3.2 看 MQTT 侧数据（mosquitto 自带客户端）

```bash
# 订阅全部主题，实时观察
mosquitto_sub -h localhost -t 'smarthome/#' -v

# 手动发命令到 B 板（等效于 HA 下发）
mosquitto_pub -h localhost -t smarthome/output/command \
  -m '{"cmd":"light","action":"red"}'
```

### 3.3 逐段定位问题

| 症状 | 定位点 |
|------|--------|
| HA 看不到 A 板数据 | `mosquitto_sub -t smarthome/sensor/data` 有无数据 → 无则看 sensor_gateway 日志/串口 |
| 发命令 B 板无动作 | `mosquitto_pub` 手动发 → 无响应则查 output_gateway 与串口；响应 `parse_error` 则见 Module B 文档已知问题 |
| MQTT 连不上 | 检查 mosquitto 服务、`MQTT_HOST/PORT`、防火墙 1883 |

---

## 4. 二次开发定义

### 4.1 架构约束

> **网关只做协议转换，不做业务决策**。若要在串口与 MQTT 之间加「规则」，请放 Home Assistant 或 PC_Test DSL，不要写进 gateway。

### 4.2 常用扩展点

| 需求 | 改哪里 |
|------|--------|
| 换 MQTT 主题 | `sensor_gateway.py` / `output_gateway.py` 顶部 `TOPIC_*` 常量（需同步 HA 配置） |
| 增加对某类 A 板消息的处理 | `sensor_gateway.py` main 循环里按 `msg_type` 增加分支/主题 |
| 增加 B 板响应分类 | `output_gateway.py` 的 `serial_reader()` |
| 加 QoS/保留位 | 把 `client.publish(...)` 加 `qos=1` 参数 |
| 断线重连/遗嘱 | 在 MQTT 回调 `on_connect` / 加 `will_set` |

### 4.3 新增「串口↔MQTT」数据通路的最小改动示例

以把 A 板某新字段透传到新主题 `smarthome/sensor/extra` 为例，在 `sensor_gateway.py`：

```python
if msg_type == "data":
    client.publish(TOPIC_DATA, line)
    if msg.get("data", {}).get("wind") is not None:
        client.publish("smarthome/sensor/extra", line)   # 新增主题
```

### 4.4 相关文档

- 数据流架构：[docs/architecture.md](../docs/architecture.md)
- 串口协议：[docs/serial-protocol.md](../docs/serial-protocol.md)
- MQTT 主题表：[README.md](README.md)
