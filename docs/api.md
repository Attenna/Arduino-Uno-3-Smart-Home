# API 接口文档

本文件汇总系统对外提供的全部编程接口，按服务分组：

| 服务 | 默认地址 | 使用者 |
|------|---------|--------|
| Web 仪表盘 REST API | `http://<host>:5000` | 前端 / 第三方程序 |
| 语音助手 HTTP API | `http://<host>:8101` | Web 转发 / 外部系统 / 按钮 |
| MCP 工具 | stdio（或经 `/tool`） | LLM / 语音助手 / Web |
| 本地 LLM（OpenAI 兼容） | `http://<host>:8000/v1` | 语音助手 |
| 摄像头 MJPEG | `http://<host>:8080` | 浏览器 / Web 代理 |

---

## 1. 通用约定

- 请求/响应默认使用 **JSON**（`Content-Type: application/json`）。
- 许多响应同时给出中文 `message` 与英文 `message_en`，供界面国际化。
- 设备控制类接口遵循"**先执行、后写库**"：只有硬件真实 ACK 后才返回成功。
- 统一错误形态：

```json
{ "error": "错误说明", "error_en": "Error description", "detail": "可选细节" }
```

| HTTP 状态码 | 含义 |
|------------|------|
| 400 | 参数缺失 / 取值非法 |
| 503 | 硬件桥未启动 / 串口离线 / 未配置 |
| 502 | 上游（语音助手）请求失败 |
| 404 | 资源不存在 |

> 设备控制请求可带 `_cid`（页面实例 ID）与 `_seq`（单调递增序号），
> 服务端据此做弱网防乱序、连点合并与幂等处理；curl 等简单客户端可省略。

---

# 2. Web 仪表盘 REST API（:5000）

## 2.1 页面路由（HTML）

| 方法 | 路径 | 页面 |
|------|------|------|
| GET | `/` | 仪表盘 |
| GET | `/history` | 历史记录 |
| GET | `/access` | 门禁管理 |
| GET | `/hardware` | 硬件管理 |
| GET | `/voice` | 语音页 |
| GET | `/automation` | 积木自动化编排 |

## 2.2 状态与健康

### GET `/api/status`

返回当前全屋状态、统计与硬件桥信息：

```json
{
  "temperature": 26.4,
  "humidity": 61.0,
  "door_status": "closed",
  "window_status": "normal",
  "light_status": "off",
  "light_brightness": 0,
  "fan_speed": 0,
  "last_updated": "2026-10-02 10:00:00",
  "statistics": { "...": "见 /api/statistics" },
  "hardware_bridge": {
    "enabled": true,
    "online": true,
    "relay": "http://voice:8101",
    "last_error": null
  }
}
```

> 状态行还可能包含 `smoke / rain / touch / motion / light_raw / device_uptime_ms`
> 以及 `ac_swing_ud / ac_swing_lr / ac_eco / ac_fzc` 等扩展列（按数据可得性出现）。

### GET `/api/health`

```json
{
  "status": "ok",
  "timestamp": 1759370400.0,
  "services": {
    "database": true,
    "ha": false,
    "face_recognition": true,
    "mcp_hardware": true
  }
}
```

异常时 `status` 为 `degraded`。

### GET `/api/statistics`

返回 24 小时温湿度统计、样本数等汇总信息。

### GET `/api/temperature?hours=24`

返回近 N 小时温湿度历史（数组）。

### GET `/api/temperature/stats`

返回 `temperature_24h` 统计对象（最高/最低/平均等）。

## 2.3 设备控制

> 以下接口在串口离线（看板/演示模式）时统一返回 **503**，不产生假状态。

### 门（Door）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/door` | 返回 `{"door_status": "open\|closed"}` |
| POST | `/api/door` | 开门 / 关门 |

请求：

```json
{ "status": "open" }
```

响应：

```json
{
  "door_status": "open",
  "message": "门已打开",
  "message_en": "Door opened"
}
```

`status` 仅接受 `open` / `closed`，否则 400。

### 窗（Window）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/window` | 返回 `{"window_status": "open\|closed\|normal"}` |
| POST | `/api/window` | 请求体 `status` 仅接受 `open` / `closed` |

> 硬件支持的 `normal`（半开 45°）状态可由自动化/语音通道设置；本 REST 入口不接收。

### GET `/api/door_window/history?hours=24`

返回门 / 窗动作历史。

### 灯（Light）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/light` | 返回 `light_status` 与 `light_brightness` |
| POST | `/api/light` | 开关灯并设置亮度 |

请求：

```json
{ "status": "on", "brightness": 80 }
```

- `brightness` 为百分比 **0~100**（自动夹取到该范围）；
- `status:"on"` 且未给亮度时按 100% 处理；`status:"off"` 时亮度强制为 0。

响应：

```json
{
  "light_status": "on",
  "light_brightness": 80,
  "message": "灯光已打开，亮度: 80%",
  "message_en": "Light turned on, brightness: 80%"
}
```

### GET `/api/light/history?hours=24`

返回灯光操作历史。

### 风扇（Fan）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/fan` | 返回 `{"fan_speed": 0~100}` |
| POST | `/api/fan` | 设置风扇转速百分比 |

请求：

```json
{ "speed": 60 }
```

响应：

```json
{
  "fan_speed": 60,
  "message": "风扇速度已设为 60%",
  "message_en": "Fan speed set to 60%"
}
```

> B 板风扇引脚为非 PWM，内部映射为开关：0=停，>0=全速。

### 空调（AC，美的红外）

#### GET `/api/ac`

```json
{
  "power": true,
  "mode": "cool",
  "temperature": 26,
  "fan": "auto",
  "swing_ud": false,
  "swing_lr": false
}
```

#### POST `/api/ac`

**只传需要改变的字段**，其余按当前状态补齐后整帧下发：

```json
{ "mode": "cool", "temperature": 26 }
```

| 字段 | 类型 | 取值 |
|------|------|------|
| `power` | boolean | `true` / `false`；缺省或 `null` 表示不改 |
| `mode` | string | `auto` / `cool` / `heat` / `dry` / `fan` |
| `temperature` | integer | `17`~`30`（整数度） |
| `fan` | string | `auto` / `low` / `mid` / `high` |
| `swing_ud` / `swing_lr` | boolean | 扫风翻转（仅值变化时补发） |

无任何字段变化时返回 `message:"空调状态未变化"`（不下发）。

### POST `/api/devices/manual_report`

供语音助手/外部系统在动作已执行后**只记账、不下发**，使面板状态/历史与真实硬件一致：

```json
{ "device": "door", "status": "open", "source": "voice" }
```

支持 `device` = `door` / `window` / `light` / `fan` / `ac`（ac 需传 `state` 对象）。

## 2.4 门禁（Access）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/access/logs` | 通行记录列表 |
| POST | `/api/access/verify` | 凭证校验（人脸 / RFID） |
| GET | `/api/access/persons` | 授权人员列表 |
| POST | `/api/access/persons` | 新增授权人员 |

`POST /api/access/verify` 请求：

```json
{ "verify_type": "face", "face_id": "person_01" }
```

通过响应：

```json
{
  "granted": true,
  "person": "张三",
  "message": "验证通过，欢迎 张三!",
  "message_en": "Verified, Welcome 张三!"
}
```

> 校验通过后会向自动化引擎投递 `face`/`granted` 事件（触发开门等规则）。
> RFID 校验使用 `verify_type:"rfid"` + `rfid_tag`。

`POST /api/access/persons` 请求：

```json
{ "name": "张三", "face_id": "person_01", "rfid_tag": "AA 53 0C 07" }
```

## 2.5 人脸（Face）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/face/recognize` | 识别单帧（body：`{"image":"<base64>"}`，≤5MB） |
| GET | `/api/face/status` | 引擎状态（是否模拟模式、阈值等） |
| GET | `/api/face/config` | 读取配置 |
| POST | `/api/face/config` | 保存配置并重载模型 |
| POST | `/api/face/reload` | 重新加载模型 |
| GET | `/api/face/known` | 已知人脸映射 |
| POST | `/api/face/known` | 添加已知人脸 `{face_id, name}` |
| DELETE | `/api/face/known/<face_id>` | 删除已知人脸 |
| POST | `/api/face/notify` | 边缘设备推送识别结果（鉴权 → 自动开门） |
| GET | `/api/face/events?limit=20` | 识别事件 |
| GET | `/api/face/events/latest` | 最近一次识别事件 |

`POST /api/face/notify` 请求：

```json
{
  "face_id": "person_01",
  "confidence": 0.72,
  "image_path": "data/face/captures/x.jpg",
  "device_source": "orange_pi"
}
```

## 2.6 自动化（Automation）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/automation/capabilities` | Blockly 下拉元数据（传感器/事件/执行器） |
| GET | `/api/automation/rules` | 规则集 |
| PUT | `/api/automation/rules` | 保存规则集（整体替换，含校验） |
| GET | `/api/automation/preview` | 当前数据下各规则触发/条件判定预览（不执行） |
| POST | `/api/automation/rules/<rule_id>/run` | 立即手动执行一条规则 |
| POST | `/api/automation/rules/restore` | 恢复被删除的内置规则 |
| GET | `/api/automation/home_mode` | 全屋模式状态 |
| PUT | `/api/automation/home_mode` | 设置全屋模式 |
| GET | `/api/automation/logs?limit=30` | 规则执行日志 |
| GET | `/api/automation/oled` | OLED 轮播配置 |
| PUT | `/api/automation/oled` | 保存 OLED 轮播配置 |

`PUT /api/automation/home_mode` 请求示例：

```json
{ "mode": "away", "reason": "页面设置" }
```

可带 `mode`（auto/manual/away）、`fan_override`、`light_level`、`enabled` 等。

## 2.7 摄像头与语音代理

### 摄像头

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/camera/status` | 返回 `{enabled, stream_url, stream}` |
| GET | `/api/camera/stream` | **MJPEG 实时流**（`multipart/x-mixed-replace`）；上游不可用返回 503 |

### 语音（对 :8101 的同源代理）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/voice/status` | 语音助手在线状态 + 状态机（IDLE/COMMAND/THINKING/FOLLOWUP） |
| POST | `/api/voice/wake` | 免唤醒词进入指令模式 |
| POST | `/api/voice/say` | 直接下发文本指令 `{"text":"..."}` |

---

# 3. 语音助手 HTTP API（:8101）

零依赖标准库实现，供手机网页、GPIO 按钮、外部程序与 Web 容器调用。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 内置控制台网页（大圆按钮 + 文本输入） |
| GET/POST | `/trigger` | 开启语音监听（进入 COMMAND） |
| GET | `/say?text=<文本>` | 直接下发文本指令 |
| POST | `/say` | 下发文本指令，body：`{"text":"..."}` |
| GET | `/state` | 返回当前状态机状态 |
| POST | `/tool` | **直调 MCP 工具**（不经 LLM、不发语音） |

### GET `/state`

```json
{ "state": "IDLE" }
```

### POST `/tool`

```json
{
  "name": "door",
  "arguments": { "action": "open" }
}
```

响应：

```json
{ "ok": true, "name": "door", "result": "..." }
```

工具失败返回 502、异常返回 500。可在请求头加 `X-Trigger-Source` 标记调用来源。

示例：

```bash
curl -X POST http://<host>:8101/say \
     -H "Content-Type: application/json" \
     -d '{"text":"把灯打开"}'

curl "http://<host>:8101/say?text=把灯打开"
curl http://<host>:8101/trigger
```

> 文本指令会立即打断正在播放的回答（barge-in）。stdin 被重定向（后台运行）时键盘输入通道自动禁用。

---

# 4. MCP 工具（mcp_home_server.py）

`mcp_home_server.py` 以 stdio 方式提供 MCP 服务，独占 A/B 串口，共 **11 个工具**。
也可经语音助手 `POST /tool` 以 HTTP 方式调用（工具名/参数相同）。

| 工具 | 主要参数 | 作用 |
|------|---------|------|
| `light` | `action`, `value`, `r`,`g`,`b` | 灯光：off/white/预设色/rgb |
| `door` | `action` = open/close | 门 |
| `window` | `action` = open/close/normal | 窗 |
| `fan` | `action` = on/off/set_speed, `value` | 风扇 |
| `buzzer` | `action` = on/off/beep, `count`,`on_ms`,`off_ms` | 蜂鸣器 |
| `oled` | `action` = show_text/clear, `line`,`text` | OLED |
| `display` | `action` = show_time/show_number/clear | 数码管（TM1637 已裁剪，返回 error） |
| `ir` | `code` 或 `address`+`command` | 红外 NEC 发射 |
| `ac` | `power`,`mode`,`temperature`,`fan`,`swing_ud`,`swing_lr` | 美的空调（生成状态帧走 send_midea） |
| `get_sensor_status` | 无 | 查询全部传感器 + 最近事件 |
| `get_serial_health` | 无 | 串口链路健康度：A/B 连接、B 板复位次数、最近引脚告警、心跳失败数（只读排障） |

调用示例（经 `/tool`）：

```json
{ "name": "fan", "arguments": { "action": "set_speed", "value": 150 } }
```

```json
{ "name": "ac", "arguments": { "mode": "cool", "temperature": 26 } }
```

> 红外 NEC 码也可用 `address` + `command`，由服务端按 NEC 帧序拼码，避免手算。

---

# 5. 本地 LLM API（qwen_server.py，:8000）

OpenAI 兼容接口（llama.cpp 后端）：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/models` | 可用模型列表 |
| POST | `/v1/chat/completions` | 对话补全（支持流式 `stream:true` 与工具调用） |

请求示例：

```bash
curl http://<host>:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-3b-instruct-q4_k_m",
    "messages": [{"role":"user","content":"你好"}],
    "stream": true
  }'
```

> 服务端支持 Qwen 原生 `<tool_call>`、裸 JSON、`{{...}}` 双括号等多种工具调用格式并做收尾扫描。
> 冒烟测试：`python qwen_server.py --smoke`（输出 `[SMOKE_OK] device=CPU`）。

---

# 6. 摄像头服务（camera_stream.py，:8080）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 内嵌查看页（引用 `/video_feed`） |
| GET | `/video_feed` | **MJPEG 视频流**（`multipart/x-mixed-replace; boundary=frame`） |

浏览器直接打开 `http://<host>:8080/video_feed` 或 `http://<host>:8080/` 即可查看。
