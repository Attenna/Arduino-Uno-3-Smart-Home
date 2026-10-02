# 系统架构

## 1. 总体边界（最高优先级约束）

> **A 板不做决定，只报告；B 板不做决定，只执行；Orange Pi 负责协议转换；决策层负责决定做什么。**

整套系统有**两种等价的部署形态**，区别只在"决策层与协议转换如何落地"，两块 Arduino 的定位始终不变：

| 形态 | 决策层 | 协议转换 | 适用场景 |
|------|--------|---------|---------|
| **形态 A：HA 生产架构** | Home Assistant | Python 网关（Serial ↔ MQTT） | 长期运行、以 HA 生态为中心的智能家居 |
| **形态 B：智能终端 Docker 栈** | Web 积木引擎 + Qwen2.5 语音 | MCP server（Serial ↔ MCP stdio，由 web 独占） | 香橙派一体化交付：面板 + 人脸 + 语音 + 摄像头 |

---

## 2. 形态 A：HA 生产架构

四个严格分层，职责单一、方向单向：

```text
┌─────────────────────────────────────────┐
│             Home Assistant              │
│                                         │
│ Automation / Scene / Script / State     │
│              业务逻辑                   │
└───────────────────┬─────────────────────┘
                    │ MQTT (1883)
┌───────────────────▼─────────────────────┐
│              Orange Pi                  │
│                                         │
│     sensor_gateway / output_gateway     │
│         Serial ↔ MQTT 协议转换           │
└───────────────┬───────────────┬─────────┘
              USB             USB
        ┌───────▼──────┐ ┌─────▼────────┐
        │   Module A   │ │   Module B   │
        │ Sensor Node  │ │ Output Node  │
        │ 只负责采集   │ │ 只负责执行   │
        └──────────────┘ └──────────────┘
```

### 各层职责

| 层 | 职责 | 禁止做的事 |
|----|------|-----------|
| Module A | 采集传感器数据，向上报告 | 做业务判断（如"温度太高"）、控制执行器 |
| Module B | 接收命令，驱动执行器 | 做业务判断、访问传感器、命令其它驱动 |
| Orange Pi 网关 | USB↔MQTT 协议转换 | 做业务决策 |
| Home Assistant | 业务逻辑、联动、场景 | 直接访问硬件 |

---

## 3. 形态 B：智能终端 Docker 栈

以 `PC_Test/docker-compose.yml` 交付的四个容器（香橙派等 Linux aarch64 设备）：

```text
┌──────────────────────────────┐        ┌──────────────────────────────┐
│  web (:5000)  硬件网关        │        │  qwen (:8000)                │
│  Flask 面板 + SQLite         │        │  OpenAI 兼容 LLM 服务         │
│  YOLOv8-face / ArcFace       │        │  llama.cpp（离线兜底，        │
│  积木自动化引擎               │        │   默认 profiles 不启动）      │
│  └─ 子进程 mcp_home_server   │        └───────────────┬──────────────┘
└──┬───────────────▲───────────┘                        │ /v1/chat/completions
   │ USB           │                              │ (工具调用)
   │               │ GET /api/hardware/tools      │
   ▼               │ POST /api/hardware/tool  ┌───▼──────────────────────┐
┌──────────┐ ┌─────┴──────┐ HTTP 唤醒/播报 ──▶│  voice (:8101)           │
│ Module A │ │  Module B  │◀(voice.url)        │  Sherpa KWS/ASR + VITS   │
└──────────┘ └────────────┘                    │  SSE /events 对话实况    │
                                               └─────────────────────────┘

   web ──/api/camera/stream（MJPEG 同源代理）──▶ camera (:8080，USB 摄像头 MJPEG)
```

**关键设计：串口归属唯一，且串口在 web**。A/B 串口同一时刻只能一个进程占用，因此：

- **串口归 web 容器**：`mcp_home_server.py` 作为 web 的 MCP stdio 子进程独占串口，暴露 13 个工具；web 对外提供两个硬件端点：
  - `GET /api/hardware/tools` → 以 OpenAI function schema 返回工具清单；
  - `POST /api/hardware/tool`（`{"name","arguments","source","timeout"}`）→ 下发到板子后做**与面板动作完全一致的记账**（更新 SQLite 状态、写历史、发 `manual_control` 事件让全屋切手动）；桥未就绪时 503；
- **voice 容器不碰串口**：纯 HTTP 客户端。启动时从 `GET /api/hardware/tools` 取工具清单喂给 LLM，工具调用一律 `POST http://web:5000/api/hardware/tool`（带 `source=voice`）。执行与记账都在 web，语音与面板天然等价（同一状态、同一历史、同一「全屋切手动」事件），无需任何回传；
- **web → voice** 的联动（面板「唤醒/发送指令」与对话实况、自动化「唤醒/播报」动作）走独立配置 `voice.url`（容器内 `http://voice:8101`），与硬件链路无关；
- 摄像头画面 → web 经 `http://camera:8080/video_feed` 同源代理；对话实况由 voice 的 SSE `GET :8101/events` 提供，web 同源代理为 `GET /api/voice/events`；
- **LLM 默认云端硅基流动**（SiliconFlow，OpenAI 兼容，模型 `Qwen/Qwen3.5-4B`；备选阿里云百炼）：本地 `qwen` 容器退为离线兜底，只有叠加 `docker-compose.local-llm.yml`（`profiles: local-llm`）时才启动。

> 非容器环境可用 `PC_Test/start_all.py` 获得完全相同的联动关系（本机端口替代容器服务发现）：先起 web（持 A/B 串口），再起 voice（指向 web 网关）与 camera。

---

## 4. Module A（Sensor Node）内部

原则：**只负责"观察世界"**。固件 `V2.1`，现役 9 类传感器（含矩阵键盘）；超声波 / 土壤湿度已裁剪。

```text
Sensor(s)
   ↓
SensorManager
   ↓
Protocol (JSON)
   ↓
USB Serial
   ↓
上位机
```

- 每个传感器驱动只做：`begin()` / `read()` / 读取结果。
- 驱动内**禁止**出现 `if (temperature > 30)` 之类的业务判断，**更禁止** `fan.turnOn()`。
- `SensorManager` 负责读取所有传感器、组织数据、交给 `Protocol`，同样不做业务判断。
- 输出为 JSON：周期性状态（`type: data`）+ 事件（`type: event`），**数据与事件不混用**。

---

## 5. Module B（Output Node）内部

原则：**只负责"改变世界"**。固件 `V2.4`，现役 7 类执行器/显示设备；TM1637 已裁剪。

```text
USB Serial
   ↓
Protocol (JSON / 冒号文本)
   ↓
CommandParser
   ↓
CommandDispatcher
   ↓
Driver
   ↓
Hardware
```

- 驱动只做硬件动作，例如 `fan.setSpeed(180)`、`door.open()`、`light.rgb(255,0,0)`。
- 禁止业务命令，如 `ALARM:SMOKE`、`door.openAndWelcome()`。
- `CommandDispatcher` 负责把 `{cmd, action, value}` 路由到对应驱动，仅此而已。
- 驱动之间**禁止**互相调用（如 `Door -> OLED`、`Light -> Buzzer`）。

---

## 6. 数据流只能向前

```text
Module A: Sensor → Manager → Protocol → Serial
Module B: Serial → Protocol → Parser → Dispatcher → Driver → Hardware
```

**不要反过来。** Module B 不访问 Module A；驱动不反向依赖上层（`Fan.cpp` 不得 `#include "CommandDispatcher.h"`）。

依赖方向：

```text
Module A:  main → SensorManager → Sensor Drivers → Arduino Hardware
Module B:  main → Protocol → Parser/Dispatcher → Drivers → Arduino Hardware
```

下层绝对不能反向依赖上层。

---

## 7. 关键链路时序

### 7.1 人脸识别 → 自动开门（形态 B）

```text
camera ──MJPEG──▶ web 人脸引擎(YOLO+ArcFace)
                      │ 识别到授权人脸 (face granted)
                      ▼
                 积木规则 face_open_door ──▶ web 硬件桥(MCP) ──▶ Module B 开门
                      │
                      └── 与面板动作同一套记账：更新状态 / 写历史 / manual_control
```

> 开门由默认积木规则 `face_open_door`（`face_granted` 事件驱动）完成，用户可停用/编辑。

### 7.2 语音指令 → 工具调用（形态 B）

```text
麦克风 ──KWS「Hey Bota」──▶ COMMAND ──流式 ASR──▶ 文本指令
文本指令 ──▶ Qwen3.5(默认云端硅基流动) ──tool_calls──▶ POST /api/hardware/tool（web）
                │                                    └─ MCP ──▶ mcp_home_server ──▶ Module B
                └── 文本流 ──▶ VITS TTS（边生成边播）
```

> voice 不带串口：工具清单来自 `GET /api/hardware/tools`，执行与记账都发生在 web，
> 因此语音控制与面板控制在状态、历史、「全屋切手动」事件上完全等价。

### 7.3 HA 自动化 → B 板（形态 A）

```text
sensor/data ──▶ HA Automation 触发 ──▶ mqtt.publish ──▶ output/command
                                                         │
Module B 执行 ◀── output_gateway ◀────────────────────────┘
       └── response / state ──▶ HA 更新实体
```

---

## 8. 技术栈一览

| 部件 | 技术 |
|------|------|
| Module A / B | Arduino Uno (ATmega328P)、PlatformIO、C++ |
| 网关（形态 A） | Python 3、pyserial、paho-mqtt、systemd |
| Broker（形态 A） | Eclipse Mosquitto (Docker) |
| 决策层（形态 A） | Home Assistant (Docker) |
| Web 面板（形态 B） | Flask、SQLite、原生 JS + Blockly + Chart.js（同时是硬件网关） |
| 人脸识别（形态 B） | YOLOv8n-face (ultralytics) + ArcFace ONNX (onnxruntime) |
| 语音（形态 B） | Sherpa-ONNX (KWS/ASR/TTS)、Qwen3.5（默认云端硅基流动 / 本地 llama.cpp 兜底） |
| 硬件桥（形态 B） | MCP (Model Context Protocol) stdio（web 的子进程）+ web HTTP 硬件端点 |

> 相关文档：协议细节见 [serial-protocol.md](serial-protocol.md)；
> 接口清单见 [api.md](api.md)；开发约束见 [development-guide.md](development-guide.md)。
