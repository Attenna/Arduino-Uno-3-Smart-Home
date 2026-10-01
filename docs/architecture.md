# 系统架构

## 1. 总体边界（最高优先级约束）

> **A 板不做决定，只报告；B 板不做决定，只执行；Orange Pi 负责协议转换；决策层负责决定做什么。**

整套系统有**两种等价的部署形态**，区别只在"决策层与协议转换如何落地"，两块 Arduino 的定位始终不变：

| 形态 | 决策层 | 协议转换 | 适用场景 |
|------|--------|---------|---------|
| **形态 A：HA 生产架构** | Home Assistant | Python 网关（Serial ↔ MQTT） | 长期运行、以 HA 生态为中心的智能家居 |
| **形态 B：智能终端 Docker 栈** | Web 积木引擎 + Qwen2.5 语音 | MCP server（Serial ↔ MCP stdio/HTTP） | 香橙派一体化交付：面板 + 人脸 + 语音 + 摄像头 |

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
┌──────────────────────────────┐   ┌──────────────────────────────┐
│  web (:5000)                 │   │  qwen (:8000)                │
│  Flask 面板 + SQLite         │   │  OpenAI 兼容 LLM 服务         │
│  YOLOv8-face / ArcFace       │   │  (llama.cpp, 可切云端百炼)    │
│  积木自动化引擎               │   │                              │
└───────┬──────────────┬───────┘   └───────────────┬──────────────┘
        │ POST /tool    │ /api/camera/stream         │ /v1/chat/completions
        │ (静默硬件转发) │ (MJPEG 同源代理)           │ (工具调用)
┌───────▼──────────────▼───────┐               ┌─────▼──────────────┐
│  voice (:8101)               │               │  camera (:8080)    │
│  语音助手                    │               │  USB 摄像头 MJPEG  │
│  Sherpa KWS/ASR + VITS TTS   │               └────────────────────┘
│  内含 mcp_home_server 子进程 │
└───────────┬──────────┬───────┘
          USB        USB
     ┌─────▼────┐ ┌───▼──────┐
     │ Module A │ │ Module B │
     └──────────┘ └──────────┘
```

**关键设计：串口归属唯一**。A/B 串口同一时刻只能一个进程占用，因此：

- **串口归 voice 容器**：`mcp_home_server.py` 作为其子进程独占串口，暴露 12 个工具；
- **web 容器不碰串口**（以 `--no-serial` 看板模式运行）：
  - 设备控制 / 人脸自动开门 → 经内网 `POST http://voice:8101/tool` 静默转发（不经 LLM、不发语音）；
  - 摄像头画面 → 经 `http://camera:8080/video_feed` 同源代理；
- **云端 LLM 覆盖**：叠加 `docker-compose.dashscope.yml` 后 qwen 容器不启动，voice 直连阿里云百炼。

> 非容器环境可用 `PC_Test/start_all.py` 获得完全相同的联动关系（本机端口替代容器服务发现）。

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
                 POST /tool {"name":"door","arguments":{"action":"open"}}
                      │
voice ◀────────────────┘
   └── MCP ──▶ mcp_home_server ──▶ Module B 开门
   └── 记账回传 web（状态/历史）
```

> 开门由默认积木规则 `face_open_door`（`face_granted` 事件驱动）完成，用户可停用/编辑。

### 7.2 语音指令 → 工具调用（形态 B）

```text
麦克风 ──KWS「Hey Bota」──▶ COMMAND ──流式 ASR──▶ 文本指令
文本指令 ──▶ Qwen2.5 ──tool_calls──▶ MCP ──▶ Module B
                └── 文本流 ──▶ VITS TTS（边生成边播）
```

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
| Web 面板（形态 B） | Flask、SQLite、原生 JS + Blockly + Chart.js |
| 人脸识别（形态 B） | YOLOv8n-face (ultralytics) + ArcFace ONNX (onnxruntime) |
| 语音（形态 B） | Sherpa-ONNX (KWS/ASR/TTS)、Qwen2.5（本地 llama.cpp / 云端百炼） |
| 硬件桥（形态 B） | MCP (Model Context Protocol) stdio + HTTP |

> 相关文档：协议细节见 [serial-protocol.md](serial-protocol.md)；
> 接口清单见 [api.md](api.md)；开发约束见 [development-guide.md](development-guide.md)。
