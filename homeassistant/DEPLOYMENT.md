# Home Assistant + Docker — 部署与二次开发指南

> 面向：在 **Orange Pi（Linux/ARM）** 上通过 Docker 运行 Home Assistant（业务决策层）与 Mosquitto（MQTT Broker），
> 并把两块 Arduino 的传感器/执行器接入 HA。
> 相关：`../docker/compose.yaml`、本目录 `configuration.yaml` / `automations.yaml` / `scripts.yaml`。

**功能一句话**：HA 是本系统**唯一的业务决策层** —— 订阅 A 板传感器，按自动化规则向 B 板下发命令。

---

## 1. Linux 部署（Docker）

### 1.1 安装 Docker 与 Compose 插件

```bash
# Orange Pi 多为 Debian/Ubuntu 系（ARM64）
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
docker --version && docker compose version
```

### 1.2 目录准备

```bash
cd Arduino-Uno-3-Smart-Home
# 结构已就绪：
#   docker/compose.yaml
#   docker/mosquitto/mosquitto.conf
#   homeassistant/*.yaml        ← HA 容器把此目录挂载为 /config
```

### 1.3 启动服务

```bash
cd docker
docker compose up -d
docker compose ps        # mosquitto、homeassistant 应均为 Up
```

首次拉取 HA 镜像较大（ARM 版约几百 MB），视网络等待。

### 1.4 验证

- **Mosquitto**：`docker compose logs mosquitto`
- **Home Assistant**：浏览器打开 `http://<OrangePi-IP>:8123`
  首次访问需创建管理员账号（本地安装向导，几秒完成）。

### 1.5 配置加载说明

`docker/compose.yaml` 中把宿主 `../homeassistant` 挂载为容器 `/config`。
HA 启动即读取 `configuration.yaml`（内含 `mqtt:` 集成与 sensor/binary_sensor/switch/fan 实体定义）。
改完 `*.yaml` 后：

```bash
docker compose restart homeassistant
# 或在 HA「开发者工具 → YAML」里 reload
```

> ⚠️ `configuration.yaml` 里 `mqtt.broker: localhost` 成立的前提是 HA 与 Mosquitto **同机**（本 compose 即同机）。
> 若 Mosquitto 在另一台机，把 broker 改成其 IP。

---

## 2. 设备安装与连接

### 2.1 硬件接线

HA 本身不接硬件。两块 Arduino 通过 USB 接 Orange Pi，网关进程转发到 MQTT（见 [../gateway/DEPLOYMENT.md](../gateway/DEPLOYMENT.md)）。

### 2.2 MQTT 主题约定（HA 与网关的"接口契约"）

| 主题 | 方向 | 内容 |
|------|------|------|
| `smarthome/sensor/data` | A → HA | 周期数据 JSON |
| `smarthome/sensor/event` | A → HA | 事件 JSON（rfid/touch/smoke...） |
| `smarthome/output/command` | HA → B | B 板命令 JSON |
| `smarthome/output/response` | B → HA | 命令响应 |
| `smarthome/output/state` | B → HA | 执行器状态 JSON |

> `configuration.yaml` 的实体全部基于这些主题 + `value_template` 解析，属"MQTT 原生自动发现"的手写配置方式。

### 2.3 接入顺序检查清单

1. Mosquitto 容器 Up（`docker compose ps`）；
2. 两个 gateway 进程连上 MQTT 且订阅正常；
3. 用 `mosquitto_sub -h <IP> -t 'smarthome/#' -v` 能看到 A 板 data / B 板 state；
4. HA 已启动并加载 yaml → 实体出现（`sensor.temperature`、`switch.door`、`fan.fan` 等）。

---

## 3. 调试方法

### 3.1 看 MQTT 数据

```bash
# 在 Orange Pi 上
mosquitto_sub -t 'smarthome/#' -v
```

### 3.2 HA 日志

```bash
docker compose logs -f homeassistant
```

浏览器端：「设置 → 系统 → 日志」。

### 3.3 检查实体与状态

- HA 页面「设置 → 设备与服务 → MQTT」看集成是否正常；
- 开发者工具 → 状态，搜索 `sensor.temperature` 等，看数值是否更新（每 2s 随 A 板上报刷新）；
- 开发者工具 → 服务，手动调用 `switch.turn_on`（Door）验证命令链路到 B 板。

### 3.4 常见问题

| 症状 | 排查 |
|------|------|
| 实体显示「不可用/未知」 | MQTT 没数据 → 查 gateway 与串口；`value_template` 字段名与协议不一致 |
| 自动化不触发 | 看自动化 trigger 的实体 id 是否与 configuration.yaml 生成的一致 |
| B 板命令 parse_error | Module B 固件 JSON bug，改用纯文本等价或修复固件 |
| 改 yaml 不生效 | 未 restart/reload |

---

## 4. 二次开发定义

### 4.1 架构约束

> **所有业务逻辑都在 HA 的 automation/script/scene 里**。新增联动不要改 Arduino 固件。

### 4.2 新增一个自动化（以「人走灯灭」为例）

在 `homeassistant/automations.yaml` 追加：

```yaml
- id: "pir_off_light_after_idle"
  alias: "无人自动关灯"
  trigger:
    - platform: state
      entity_id: binary_sensor.smoke   # 换成实际人体实体（若 A 板 PIR 已建实体）
      ...
  action:
    - service: switch.turn_off
      target: { entity_id: switch.light }
```

改完重启/reload。HA 触发条件、延时等详见 [docs/ha-automation-examples.md](../docs/ha-automation-examples.md)。

### 4.3 新增实体 / 接入新传感器字段

在 `configuration.yaml` 的 `mqtt.sensor` / `binary_sensor` 段按现有模式追加条目即可（主题相同、`value_template` 指向新字段）。例如 A 板上报里出现新字段 `wind`：

```yaml
sensor:
  - name: "Wind"
    state_topic: "smarthome/sensor/data"
    value_template: "{{ value_json.data.wind }}"
    unit_of_measurement: "m/s"
```

### 4.4 更灵活地发原始命令（脚本模式）

复杂动作（蜂鸣几段、RGB 组合）可写成脚本放 `scripts.yaml`（已含 door/window/fan/light/oled 示例），自动化里调用 `script.xxx`。

### 4.5 相关文档

- HA 自动化实战示例（联动/场景/脚本）：[docs/ha-automation-examples.md](../docs/ha-automation-examples.md)
- 串口协议（实体映射的字段来源）：[docs/serial-protocol.md](../docs/serial-protocol.md)
- 数据流架构：[docs/architecture.md](../docs/architecture.md)
