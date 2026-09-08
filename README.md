# SmartHome — Arduino 双节点 + Home Assistant 智能家居系统

> **一句话架构约束（最高优先级）**
> **A 板不做决定，只报告；B 板不做决定，只执行；Orange Pi 负责协议转换；Home Assistant 负责决定做什么。**

本仓库将整个系统划分为两个**完全独立**的 Arduino 固件工程，外加网关、Home Assistant 配置与容器编排。

- **Module A（Sensor Node）**：只负责采集传感器数据，向上游（Orange Pi → Home Assistant）报告。
- **Module B（Output Node）**：只负责执行执行器动作，由上游下发命令驱动。
- 两块板之间**不直接做业务联动**，所有决策都在 Home Assistant 完成。

---

## 目录结构

```text
SmartHome/
├── README.md
├── docs/
│   ├── README.md              # 文档中心（索引）
│   ├── architecture.md        # 总体架构
│   ├── serial-protocol.md     # 串口 JSON 协议
│   ├── development-guide.md   # 开发规范（含最高架构约束）
│   ├── ha-automation-examples.md  # HA 自动化实战示例
│   └── hardware-debug-notes.md    # 硬件调试备忘（踩坑复盘）
│
├── module-a-sensor/           # Module A：Sensor Node（PlatformIO）
├── module-b-output/           # Module B：Output Node（PlatformIO）
├── gateway/                   # Orange Pi 串口↔MQTT 网关
├── homeassistant/             # Home Assistant 配置
├── docker/                    # Docker Compose（Mosquitto + HA）
└── PC_Test/                   # PC 端工具集（串口调试 + 本地自动化 DSL）
    ├── README.md              #   工具总览与快速开始
    ├── test_serial.py         #   串口调试控制台
    ├── run_automation.py      #   自动化 DSL 运行器
    └── automation/            #   AST 自动化引擎 + .auto 脚本
```

> 仓库中仍保留旧的 `Module_A/`、`Module_B/` 目录（`.ino` 单文件工程），
> 作为历史参考与独立调试用。新架构以 `module-a-sensor/`、`module-b-output/` 为准。
> `PC_Test/` 是 PC 端调试与本地自动化工具，独立于生产部署（gateway + HA）。

---

## 快速开始

1. **Module A**：见 [module-a-sensor/README.md](module-a-sensor/README.md)
2. **Module B**：见 [module-b-output/README.md](module-b-output/README.md)
3. **网关**：见 [gateway/README.md](gateway/README.md)
4. **Home Assistant / Docker**：见 [homeassistant/](homeassistant/) 与 [docker/compose.yaml](docker/compose.yaml)
5. **PC 端调试 / 本地自动化**：见 [PC_Test/README.md](PC_Test/README.md)

---

## 核心文档

| 文档 | 内容 |
|------|------|
| [docs/README.md](docs/README.md) | 📖 文档中心（按角色/部件快速定位） |
| [docs/architecture.md](docs/architecture.md) | 分层架构、数据流向、模块边界 |
| [docs/serial-protocol.md](docs/serial-protocol.md) | 串口 JSON 协议规范（A 上报 / B 命令） |
| [docs/development-guide.md](docs/development-guide.md) | 命名、依赖方向、禁止跨层调用等开发规范 |
| [docs/ha-automation-examples.md](docs/ha-automation-examples.md) | Home Assistant 自动化实战（联动、场景、脚本） |
| [docs/hardware-debug-notes.md](docs/hardware-debug-notes.md) | Module B 硬件调试备忘（踩坑复盘、排障速查） |
| [PC_Test/README.md](PC_Test/README.md) | PC 端工具总览（串口调试控制台 + 自动化 DSL） |
| [PC_Test/automation/README.md](PC_Test/automation/README.md) | 自动化 DSL 语法手册 |

### 各部件部署指南（Linux / 接线 / 调试 / 二次开发）

每个部件目录的 `DEPLOYMENT.md` 自包含：**Linux 部署 → 设备安装连接 → 调试 → 二次开发定义**。

| 部件 | 部署指南 |
|------|---------|
| Module A 传感器板 | [module-a-sensor/DEPLOYMENT.md](module-a-sensor/DEPLOYMENT.md) |
| Module B 执行器板 | [module-b-output/DEPLOYMENT.md](module-b-output/DEPLOYMENT.md) |
| Gateway 网关 | [gateway/DEPLOYMENT.md](gateway/DEPLOYMENT.md) |
| Home Assistant + Docker | [homeassistant/DEPLOYMENT.md](homeassistant/DEPLOYMENT.md) |
| PC_Test 工具集 | [PC_Test/DEPLOYMENT.md](PC_Test/DEPLOYMENT.md) |
