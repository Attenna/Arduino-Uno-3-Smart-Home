# Gateway — 串口 ↔ MQTT 网关（Orange Pi）

> **职责：只做协议转换，不做业务决策。**
>
> 🚀 部署/接线/调试/二次开发完整指南见 **[DEPLOYMENT.md](DEPLOYMENT.md)**。

两个独立进程：

| 脚本 | 作用 |
|------|------|
| `src/sensor_gateway.py` | 读取 Module A 串口 JSON → 发布到 MQTT |
| `src/output_gateway.py` | 订阅 MQTT 命令 → 下发到 Module B 串口；回传响应/状态 |

---

## 依赖安装

```bash
cd gateway
pip install -r requirements.txt
```

## 环境变量（均有默认值）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SENSOR_PORT` | `/dev/ttyUSB0` | Module A 串口 |
| `OUTPUT_PORT` | `/dev/ttyUSB1` | Module B 串口 |
| `BAUD` | `115200` | 波特率 |
| `MQTT_HOST` | `localhost` | MQTT Broker |
| `MQTT_PORT` | `1883` | MQTT 端口 |

## 运行

```bash
# 终端 1：传感器网关
python src/sensor_gateway.py

# 终端 2：执行器网关
python src/output_gateway.py
```

## MQTT 主题

| 主题 | 方向 | 内容 |
|------|------|------|
| `smarthome/sensor/data` | A → HA | 周期数据 |
| `smarthome/sensor/event` | A → HA | 事件 |
| `smarthome/output/command` | HA → B | 命令 |
| `smarthome/output/response` | B → HA | 响应 |
| `smarthome/output/state` | B → HA | 状态 |

## 识别串口

```bash
# Linux（Orange Pi）
ls /dev/ttyUSB* /dev/ttyACM*
```

两块板同时接入时，可通过上电后的 `ready` 消息中的 `board` 字段区分。
