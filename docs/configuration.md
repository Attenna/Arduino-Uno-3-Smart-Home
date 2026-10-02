# 配置说明

本文件说明系统所有配置项的含义、取值与优先级。

## 1. 配置体系总览

| 配置 | 形态 | 读取者 |
|------|------|--------|
| [PC_Test/web_config.yaml](../PC_Test/web_config.yaml) | YAML | `run_web.py` / Web 包 |
| [PC_Test/voice_config.yaml](../PC_Test/voice_config.yaml) | YAML | `voice_assistant.py` / `mcp_home_server.py` / `qwen_server.py` |
| [PC_Test/docker/.env.example](../PC_Test/docker/.env.example) → `.env` | dotenv | Docker Compose |
| 环境变量 `SMART_HOME_*` | env | 容器 / 进程 |
| `src/Config.h`（两块板） | C++ 宏 | Arduino 固件（编译期） |
| 网关环境变量 | env | `gateway/src/*.py` |

### 优先级（高 → 低）

```text
命令行参数  >  环境变量 SMART_HOME_*  >  YAML 配置文件  >  内置默认值
```

> Web 人脸配置有额外规则：运行时生成的 `data/face/face_config.json` **高于** yaml。

---

## 2. web_config.yaml 参考

### 2.1 `server` — Web 监听

| 键 | 默认 | 说明 |
|----|------|------|
| `host` | `0.0.0.0` | 监听地址；仅本机访问用 `127.0.0.1` |
| `port` | `5000` | 端口 |

### 2.2 `serial` — 硬件链路

| 键 | 默认 | 说明 |
|----|------|------|
| `enabled` | `true` | `false` = 纯看板/演示模式（设备控制返回 503） |
| `port_a` | `auto` | Module A 串口（如 `COM7`），`auto` = 自动探测 |
| `port_b` | `auto` | Module B 串口（如 `COM6`） |

### 2.3 其他顶层键

| 键 | 默认 | 说明 |
|----|------|------|
| `sensor_poll_interval` | `2.0` | 后台轮询 MCP `get_sensor_status` 的间隔（秒） |
| `door.open_on_face_grant` | `true` | 人脸授权通过后自动开门 |
| `door.relay_url` | 注释 | 串口归语音助手时的硬件转发地址（通常由 `SMART_HOME_HW_RELAY` 注入） |
| `camera.stream_url` | `http://127.0.0.1:8080/video_feed` | 摄像头 MJPEG 上游地址 |

### 2.4 `face` — 人脸识别

| 键 | 默认 | 说明 |
|----|------|------|
| `model_path` | `models/face/yolov8n-face.pt` | YOLOv8-face 检测模型 |
| `confidence_threshold` | `0.4` | 人脸置信度阈值 |
| `iou_threshold` | `0.45` | NMS IoU 阈值 |
| `max_faces` | `5` | 单帧最多人脸数 |
| `simulation_mode` | `false` | `true` = 返回模拟人脸（无模型演示） |
| `recognition.enabled` | `true` | 是否启用人脸身份识别 |
| `recognition.method` | `arcface_onnx` | `arcface_onnx`（高精度）/ `simple_grayscale_cosine`（零依赖回退） |
| `recognition.model_path` | `models/face/recognition.onnx` | ArcFace 模型 |
| `recognition.similarity_threshold` | `0.5` | 身份判定相似度阈值 |
| `recognition.image_size` | `112` | 识别输入尺寸 |

---

## 3. voice_config.yaml 参考

### 3.1 `serial`

| 键 | 默认 | 说明 |
|----|------|------|
| `port_a` | `auto` | 传感器板串口 |
| `port_b` | `auto` | 执行器板串口 |

### 3.2 `llm` — 大模型

| 键 | 默认 | 说明 |
|----|------|------|
| `mode` | `local` | `local`（本地离线推理）/ `dashscope`（阿里云百炼） |
| `base_url` | `http://127.0.0.1:8000/v1` | OpenAI 兼容端点；dashscope 用 `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `api_key` | `none` | dashscope 模式填 API Key；local 无需 |
| `model` | `qwen2.5-3b-instruct-q4_k_m` | local = GGUF 文件名去 `.gguf`；dashscope 用在线模型名（如 `qwen2.5-3b-instruct`） |
| `system_prompt` | （内置） | 注入给模型的系统提示词 |

`llm.local`（仅 `mode: local` 生效，由 `qwen_server.py` 读取）：

| 键 | 默认 | 说明 |
|----|------|------|
| `gguf_path` | `models/qwen/qwen2.5-3b-instruct-q4_k_m.gguf` | 模型权重路径 |
| `n_ctx` | `8192` | 上下文长度 |
| `n_threads` | `0` | CPU 线程数，`0` = 自动 |
| `n_gpu_layers` | `0` | GPU 层数；香橙派纯 CPU 保持 `0` |
| `port` | `8000` | 本地服务端口 |

### 3.3 `sherpa` — 语音前端

| 键 | 默认 | 说明 |
|----|------|------|
| `provider` | `cpu` | 推理后端 |
| `num_threads` | `2` | KWS/ASR 推理线程 |
| `kws.model_dir` | `models/sherpa/kws` | 唤醒模型目录 |
| `kws.keywords_file` | `models/sherpa/kws/keywords.txt` | 唤醒词表 |
| `kws.keywords_score` | `1.5` | 唤醒词打分（调大更易唤醒，误唤醒增加） |
| `kws.keywords_threshold` | `0.25` | 声学阈值（调小更灵敏，误唤醒增加） |
| `asr.model_dir` | `models/sherpa/asr` | 流式识别模型目录 |
| `asr.rule1_silence` | `2.4` | 句尾静音秒数（端点检测） |
| `asr.rule2_silence` | `1.2` | 句中静音秒数 |
| `asr.rule3_utt_len` | `20.0` | 最长句长（秒） |
| `asr.hotwords_file` | `models/sherpa/asr/hotwords.txt` | 热词文件 |
| `asr.hotwords_score` | `2.0` | 热词权重（1.5~3） |
| `tts.model_dir` | `models/sherpa/tts` | TTS 模型目录 |
| `tts.speaker_id` | `0` | 说话人 ID（0 = 中文女声） |
| `tts.speed` | `1.0` | 语速倍数 |
| `tts.num_threads` | `2` | TTS 推理线程 |

### 3.4 `wake` — 唤醒与追问

| 键 | 默认 | 说明 |
|----|------|------|
| `words` | `["hey bota"]` | 唤醒词（用于剥连读前缀；声学唤醒见 KWS 词表） |
| `command_timeout` | `6.0` | 命令模式等待整句秒数 |
| `followup_timeout` | `8.0` | 回答后追问窗口（秒） |
| `wake_ack` | `在的` | 语音应答内容 |
| `ack_mode` | `chirp` | `chirp`（滴声，推荐）/ `voice` / `both` / `none` |
| `chirp_freq` | `880` | 滴声音高 Hz |
| `chirp_ms` | `120` | 滴声时长 ms |

### 3.5 `trigger` 与 `mic`

| 键 | 默认 | 说明 |
|----|------|------|
| `trigger.keyboard` | `true` | 终端打字回车 = 文本指令；空回车 = 开语音监听 |
| `trigger.http` | `true` | 开启 HTTP 接口（:8101） |
| `trigger.host` | `0.0.0.0` | HTTP 监听地址 |
| `trigger.port` | `8101` | HTTP 端口 |
| `mic.device_index` | `null` | 麦克风索引，`null` = 系统默认（用 `--list-mic` 查看） |

---

## 4. Docker Compose：`.env` 参考

复制 `docker/.env.example` 为 `PC_Test/..env`：

| 变量 | 默认 | 说明 |
|------|------|------|
| `TZ` | `Asia/Shanghai` | 时区 |
| `SERIAL_PORT_A` | `/dev/ttyUSB0` | A 板串口（建议用 `/dev/serial/by-id/...` 稳定路径） |
| `SERIAL_PORT_B` | `/dev/ttyUSB1` | B 板串口 |
| `CAMERA_DEVICE` | `/dev/video0` | 摄像头**优先候选**节点；容器随宿主机 `/dev` 走，不在位时自动枚举其它 `/dev/video*` |
| `MIC_INDEX` | （空） | 麦克风索引，空 = 系统默认 |
| `QWEN_PORT` | `8000` | 本地 LLM 宿主端口 |
| `VOICE_PORT` | `8101` | 语音宿主端口 |
| `WEB_PORT` | `5000` | Web 宿主端口 |
| `CAMERA_PORT` | `8080` | 摄像头宿主端口 |
| `DASHSCOPE_API_KEY` | — | 仅云端 LLM 覆盖时需要 |

查设备：

```bash
ls -l /dev/ttyUSB* /dev/ttyACM* /dev/serial/by-id/* /dev/video*
```

---

## 5. 运行时环境变量（SMART_HOME_*）

容器编排与 `start_all.py` 通过这些变量注入配置：

### voice 进程

| 变量 | 作用 |
|------|------|
| `SMART_HOME_LLM_BASE_URL` | 覆盖 LLM 端点（容器内为 `http://qwen:8000/v1`） |
| `SMART_HOME_LLM_API_KEY` | 覆盖 LLM API Key |
| `SMART_HOME_LLM_MODEL` | 覆盖模型名（云端为 `qwen-turbo`） |
| `SMART_HOME_PORT_A` / `SMART_HOME_PORT_B` | 覆盖 A/B 串口 |
| `SMART_HOME_MIC_INDEX` | 覆盖麦克风索引 |
| `SMART_HOME_WEB_URL` | 动作回传 Web 的地址（容器内 `http://web:5000`） |
| `SMART_HOME_DISABLE_MIC` | `1` = 跳过麦克风（纯硬件网关/人脸开门模式） |

### web 进程

| 变量 | 作用 |
|------|------|
| `SMART_HOME_HW_RELAY` | 硬件转发地址（容器内 `http://voice:8101`） |
| `SMART_HOME_CAMERA_URL` | 摄像头上游地址（容器内 `http://camera:8080/video_feed`） |
| `SMART_HOME_DB` | 自定义 SQLite 路径（可选） |

---

## 6. 固件配置（src/Config.h）

### 6.1 Module A（[Config.h](../module-a-sensor/src/Config.h)）

裁剪开关（`1` = 启用，`0` = 不初始化不读取，引脚高阻）：

| 宏 | 默认 | 说明 |
|----|------|------|
| `ENABLE_ULTRASONIC` | `0` | HC-SR04（已移除） |
| `ENABLE_SOIL` | `0` | 土壤湿度（已移除，引脚改键盘） |
| `ENABLE_KEYPAD` | `1` | 矩阵键盘（D4 行 / A4 列） |
| `ENABLE_IR_RECV` | `1` | 红外接收（D3） |
| `ENABLE_PIR` | `1` | PIR（D8） |
| `ENABLE_RFID` | `1` | RC522 |

常用参数宏：`SERIAL_BAUD`、`DHT_PIN`、`DHT_INTERVAL_MS`、`REPORT_INTERVAL_MS`、
`KEYPAD_DEBOUNCE_MS`、`KEYPAD_RELEASE_MS`、`RAIN_THRESHOLD`、各类 `DEBOUNCE_*`，
以及设备标识 `BOARD_TYPE` / `BOARD_ROLE` / `FW_VERSION`。

### 6.2 Module B（[Config.h](../module-b-output/src/Config.h)）

| 宏 | 默认 | 说明 |
|----|------|------|
| `ENABLE_TM1637` | `0` | 四位数码管（已移除，D5/D6 悬空） |
| `ENABLE_IR_TX` | `1` | 红外发射（D12） |

常用参数宏：门/窗舵机引脚与角度（`DOOR_*` / `WINDOW_*` / `SERVO_SETTLE_TIME`）、
`FAN_INA` / `FAN_INB`、`RGB_PIN` / `LED_COUNT` / `LIGHT_BRIGHTNESS`、
`LIGHT_BOOT_ON` / `LIGHT_BOOT_LEVEL`、`BUZZER_*`、`OLED_*` / `OLED_IS_SH1106`、
`MIDEA_*`（美的长码时序）、`FW_VERSION`。

> 所有引脚/阈值/时序只能改 Config.h，禁止在驱动 `.cpp` 内硬编码。

---

## 7. 网关环境变量（形态 A）

| 变量 | 默认 | 说明 |
|------|------|------|
| `SENSOR_PORT` | `/dev/ttyUSB0` | A 板串口（sensor_gateway） |
| `OUTPUT_PORT` | `/dev/ttyUSB1` | B 板串口（output_gateway） |
| `BAUD` | `115200` | 波特率 |
| `MQTT_HOST` | `localhost` | Broker 地址 |
| `MQTT_PORT` | `1883` | Broker 端口 |

---

## 8. 运行时生成的文件

| 文件 | 作用 | 处理建议 |
|------|------|---------|
| `PC_Test/data/face/face_config.json` | 运行时人脸配置，**优先级高于 yaml** | 改 yaml 不生效时删除它并重启 |
| `PC_Test/data/ha_config.json` | 可选 HA 对接配置（默认无密钥） | 硬件管理页维护 |
| `PC_Test/data/smart_home.db` | SQLite 数据库 | 删除即重置全部历史 |
| `PC_Test/data/global_state.json` | 积木用的全局状态变量（含 `g:全屋模式` 等） | 与 `automation_rules.json` 同生命周期；在列表页删掉那条「📌 状态」条目即可，不必删文件 |
| `PC_Test/data/automation_rules.pre-global-state.json` | 首次加载时旧规则迁移前的一次性备份 | 只写一次，确认规则无误后可删 |
| `PC_Test/data/face/embeddings.pkl` | 人脸嵌入库 | 由 `scripts/enroll_faces.py` 生成 |

`data/` 与 `models/` 均已在 `.gitignore` 中，不入库。

---

## 9. 密钥管理

- **百炼 API Key** 三选一：① `PC_Test/dashscope_key.txt`（推荐，已 gitignore）；
  ② 环境变量 `DASHSCOPE_API_KEY`；③ `llm.api_key`。
- 容器部署时 Key 只写入宿主机 `.env`（已 gitignore），不要提交。
- HA 的 `secrets.yaml` 用于存放 HA 侧敏感值，避免明文进配置。
