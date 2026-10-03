# SmartHome — Arduino 双节点智能家居系统

> **一句话架构约束（最高优先级）**
> **A 板不做决定，只报告；B 板不做决定，只执行；上位机负责协议转换；决策层负责决定做什么。**

本仓库将整个系统划分为两个**完全独立**的 Arduino 固件工程，外加网关、Home Assistant 配置、PC 端智能终端栈与容器编排。

- **Module A（Sensor Node）**：只负责采集传感器数据，向上位机报告。
- **Module B（Output Node）**：只负责执行执行器动作，由上位机下发命令驱动。
- 两块板之间**不直接做业务联动**，所有决策都在决策层完成。

系统支持**两种部署形态**：

| 形态 | 决策层 | 协议转换 | 交付方式 |
|------|--------|---------|---------|
| **A：HA 生产架构** | Home Assistant | 串口↔MQTT 网关 | `docker/` + `gateway/` |
| **B：智能终端栈** | Web 积木引擎 + Qwen2.5 语音 | MCP server（串口归 web） | `PC_Test/docker-compose.yml` |

---

## 功能特性

- **环境感知**：温湿度、光照、烟雾、雨滴、触摸、PIR 人体、红外、RFID、矩阵键盘
- **设备控制**：门 / 窗舵机、风扇、NeoPixel RGB 灯带、蜂鸣器、OLED、红外（NEC + 美的空调长码）
- **Web 仪表盘**：实时监控、设备控制、历史图表（Flask + SQLite）
- **人脸识别门禁**：YOLOv8-face + ArcFace，授权通过自动开门
- **语音助手**：「Hey Bota」唤醒 + Qwen3.5（默认云端硅基流动 / 备选百炼 / 本地 llama.cpp 兜底）+ 流式 TTS
- **积木式自动化**：Blockly 可视化编排「触发 → 条件 → 动作」，内置默认规则

> 固件经 2026-09 正式版裁剪：A 板移除超声波 / 土壤、新增矩阵键盘（`V2.1`）；
> B 板移除 TM1637 数码管（`V2.4`）。驱动文件均保留，可通过 `Config.h` 裁剪开关恢复。

---

## 目录结构

```text
Arduino-Uno-3-Smart-Home/
├── README.md                    # 本文件
├── docs/                        # 项目文档
│   ├── README.md                #   文档中心（索引）
│   ├── architecture.md          #   总体架构（两种部署形态）
│   ├── serial-protocol.md       #   串口 JSON 协议
│   ├── api.md                   #   API 接口文档
│   ├── configuration.md         #   配置说明
│   ├── development-guide.md     #   开发规范
│   ├── ha-automation-examples.md#   HA 自动化实战
│   ├── hardware-debug-notes.md  #   硬件调试备忘
│   └── faq.md                   #   常见问题
│
├── module-a-sensor/             # Module A：Sensor Node（PlatformIO）
├── module-b-output/             # Module B：Output Node（PlatformIO）
├── gateway/                     # 形态 A：串口↔MQTT 网关
├── homeassistant/               # 形态 A：Home Assistant 精简配置
├── ha_config/                   # 实际运行 HA 的配置快照
├── docker/                      # 形态 A：Compose（Mosquitto + HA）
├── tools/                       # 红外原始码捕获 / 分析工具
└── PC_Test/                     # 形态 B：PC 端工具 + 智能终端 Docker 栈
    ├── README.md                #   工具总览与快速开始
    ├── docker-compose.yml       #   web(硬件网关,持串口)/voice/camera；qwen 在 local-llm profile
    └── web/automation/          #   积木式自动化引擎
```

---

## 快速开始

**形态 A（HA + 网关）**

1. Module A：[module-a-sensor/README.md](module-a-sensor/README.md)
2. Module B：[module-b-output/README.md](module-b-output/README.md)
3. 网关：[gateway/README.md](gateway/README.md)
4. Home Assistant / Docker：[homeassistant/](homeassistant/) 与 [docker/compose.yaml](docker/compose.yaml)

**形态 B（智能终端 Docker 栈，香橙派）**

```bash
cd PC_Test
cp docker/.env.example .env        # 按实际串口/摄像头修改，并填 LLM_API_KEY
docker compose up -d --build       # 默认云端 LLM（硅基流动，web 独占串口）
```

详见 [PC_Test/README.md](PC_Test/README.md)。

**默认端口**

| 端口 | 服务 |
|------|------|
| 5000 | Web 仪表盘 |
| 8080 | 摄像头 MJPEG |
| 8101 | 语音助手 HTTP |
| 8000 | 本地 LLM（OpenAI 兼容，离线兜底；默认不启动） |
| 8123 | Home Assistant（形态 A） |
| 1883 | MQTT Broker（形态 A） |

---

## 核心文档

| 文档 | 内容 |
|------|------|
| [docs/README.md](docs/README.md) | 📖 文档中心（按角色/部件快速定位） |
| [docs/architecture.md](docs/architecture.md) | 两种部署形态、分层架构、数据流向、关键时序 |
| [docs/api.md](docs/api.md) | Web REST / 语音 HTTP / MCP 工具 / LLM / 摄像头接口 |
| [docs/configuration.md](docs/configuration.md) | yaml / .env / 环境变量 / Config.h 配置参考 |
| [docs/serial-protocol.md](docs/serial-protocol.md) | 串口 JSON 协议规范（A 上报 / B 命令） |
| [docs/development-guide.md](docs/development-guide.md) | 命名、依赖方向、禁止跨层调用等开发规范（含 PC_Test / Web 前端硬约定） |
| [docs/ha-automation-examples.md](docs/ha-automation-examples.md) | Home Assistant 自动化实战 |
| [docs/hardware-debug-notes.md](docs/hardware-debug-notes.md) | 硬件调试备忘（踩坑复盘、排障速查） |
| [docs/faq.md](docs/faq.md) | 常见问题解答 |

### 各部件部署指南

每个部件目录的 `DEPLOYMENT.md` 自包含：**Linux 部署 → 设备安装连接 → 调试 → 二次开发定义**。

| 部件 | 部署指南 |
|------|---------|
| Module A 传感器板 | [module-a-sensor/DEPLOYMENT.md](module-a-sensor/DEPLOYMENT.md) |
| Module B 执行器板 | [module-b-output/DEPLOYMENT.md](module-b-output/DEPLOYMENT.md) |
| Gateway 网关 | [gateway/DEPLOYMENT.md](gateway/DEPLOYMENT.md) |
| Home Assistant + Docker | [homeassistant/DEPLOYMENT.md](homeassistant/DEPLOYMENT.md) |
| PC_Test 工具集 | [PC_Test/DEPLOYMENT.md](PC_Test/DEPLOYMENT.md) |
