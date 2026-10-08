# API 接口文档

本文件汇总系统对外提供的全部编程接口，按服务分组：

| 服务 | 默认地址 | 使用者 |
|------|---------|--------|
| Web 仪表盘 REST API | `http://<host>:5000` | 前端 / 第三方程序 / 语音助手（硬件网关） |
| 语音助手 HTTP API | `http://<host>:8101` | Web 同源代理 / 外部系统 / 按钮 |
| 硬件工具网关 | `http://<host>:5000/api/hardware/*` | 语音助手 / 外部程序（与面板同权同账） |
| MCP 工具 | stdio（Web 服务的子进程，独占 A/B 串口） | 仅 Web 内部 |
| 云端 LLM（OpenAI 兼容，默认） | `https://api.siliconflow.cn/v1` | 语音助手（硅基流动；备选百炼 `https://dashscope.aliyuncs.com/compatible-mode/v1`） |
| 本地 LLM（OpenAI 兼容，离线兜底） | `http://<host>:8000/v1` | 语音助手（`llm.mode: local`） |
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
| 404 | 资源不存在 |
| 502 | 上游/硬件执行失败：经 Web 转发给语音助手的请求失败（上游非 2xx 或不可达）、`POST /api/hardware/tool` 工具下发后硬件回失败 |
| 503 | 依赖未就绪，**两种来源要分开看**（见下） |

### 503 的几类含义

| 类别 | 触发条件 | 典型 `error` 文案 | 出现的接口 |
|------|---------|------------------|-----------|
| 硬件链路不可用 | web 的硬件桥未初始化（MCP 子进程没起 / 串口未启用 / 演示模式 `--no-serial`）/ 工具清单为空 | `硬件服务未启动（硬件桥未初始化）`、`硬件控制失败`、`硬件服务未就绪（MCP 未连接或串口未启用）` | `POST /api/{door,window,light,fan,ac}`、`GET /api/hardware/tools`、`POST /api/hardware/tool`、`/api/hardware/self_test` |
| 上游服务不可达 | 摄像头或语音助手连不上（`voice.url` / `SMART_HOME_VOICE_URL` 指向的进程没起） | `语音助手不可达（http://…）` | `/api/camera/stream`、`GET /api/voice/status` |
| 自动化引擎未启动 | 只在 `create_app(start_hardware=False)`（单测/被嵌入调用）或硬件桥初始化失败时出现。**`--no-serial` 只是桌面/演示降级**，不是生产形态：串口归 web 独占后，生产 web 直接带着硬件桥跑自动化 | `自动化引擎未启动` | `/api/automation/*`（除 `capabilities`） |

> 读接口（`GET /api/door` 等）直接返回数据库里的最近状态，**不会**因串口离线而 503；
> `POST /api/devices/manual_report` 与工具网关里的记账部分只记账、不碰硬件，同样不会 503。

### 鉴权与跨域：目前**没有**

- 所有 Web REST 接口（含规则读写、门禁记录、人脸推送 `/api/face/notify`）
  **无鉴权、无 token、无 Cookie 会话**；只要 TCP 能到 :5000 就能读改全部数据。
- 未配置 CORS 头：同源页面（含本仪表盘）可直接调，跨源脚本会被浏览器拦下。
- 无速率限制、无请求体上限（仅 `/api/face/recognize` 的 base64 图像限 5MB，
  且人脸引擎自带节流：过频时返回 `{"detected": false, "mode": "throttled"}`，HTTP 仍是 200）。
- 因此本系统按**可信局域网**设计：不要把 :5000 直接暴露到公网；需要对外时
  自行加反向代理 + 鉴权，或只开放自动化出站（见下）。

### 出站方向（二次开发）

规则里可用「HTTP 请求」积木把事件/状态推给外部系统，默认只放行本机与内网目标，
不带认证头、不跟随重定向；放开方式与用法见 [扩展开发指南](extension-guide.md)。

> 设备控制请求可带 `_cid`（页面实例 ID）与 `_seq`（单调递增序号），
> 服务端据此做弱网防乱序、连点合并与幂等处理；curl 等简单客户端可省略。
> 两者只对**面板/外部直控**生效：`manual_report` 与自动化引擎不过收口器。

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
  "light_mode": "white",
  "light_temp": null,
  "light_rgb": null,
  "fan_speed": 0,
  "last_updated": "2026-10-02 10:00:00",
  "statistics": { "...": "见 /api/statistics" },
  "hardware_bridge": {
    "enabled": true,
    "online": true,
    "last_error": null
  },
  "device_mismatch": null,
  "serial_health": { "...": "A/B 连接、重连与复位计数、引脚告警等" }
}
```

> 状态行还可能包含 `smoke / rain / touch / motion / light_raw / device_uptime_ms`
> 以及 `ac_swing_ud / ac_swing_lr / ac_eco / ac_fzc` 等扩展列（按数据可得性出现）。
>
> `device_mismatch` 是 B 板硬件回读与库中期望状态的比对结果（一致时为 `null`）；
> `serial_health` 由 web 的硬件桥在自己的循环里低频轮询 MCP `get_serial_health` 得到
> （串口就在本进程的 MCP 子进程里，不再跨容器取回），桥未启动时为 `null`。

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

### GET|POST `/api/hardware/self_test`

触发 **B 板固件自检**（只读诊断，需固件 V2.9+），用来把「灯不亮 / 风扇自转」二分到
固件未执行 / 引脚被外设抢走 / 引脚物理短路：

```json
{ "ok": true, "selftest": { "cmd_ok": 12, "cmd_bad": 0, "fan_dir": "…", "strip_shown": 4 } }
```

硬件桥未初始化或固件不支持时返回 503 `{"ok": false, "error": "…"}`。
GET 与 POST 等价（便于浏览器地址栏直接点）。

## 2.3 设备控制

> 只有**下发硬件的 POST** 才可能 503（web 的硬件桥未初始化 / MCP 调用失败），
> 同名 GET 读的是数据库，不碰硬件；`manual_report` 也只记账。见 §1「503 的几类含义」。
> 这组接口与下方「硬件工具网关」是同一套执行 + 记账路径，所以面板、语音、外部程序
> 看到的状态与历史完全一致。

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
| GET | `/api/light` | 返回 `light_status`、`light_brightness` 与当前亮法 `light_mode` / `light_temp` / `light_rgb` |
| POST | `/api/light` | 开关灯、设置亮度与「亮法」（白光 / 夜灯 / 色温 / 自定义颜色） |

请求：

```json
{ "status": "on", "brightness": 80 }
```

- `brightness` 为百分比 **0~100**（自动夹取到该范围）；
- `status:"on"` 且未给亮度时沿用库里当前亮度（灯是关的则按 100%）；**亮度 0 就是关灯**；`status:"off"` 时亮度强制为 0，并保留原亮法（下次开灯还是同一种亮法）；
- `mode`（可选）：`white`（整条灯带白光）/ `night`（夜灯，固件只点亮居中几颗灯珠）；
- `temp`（可选）：色温 **2700~6500K**（超出自动夹取），由固件按色温表出光，`brightness` 仍是亮度；
- `rgb`（可选）：`[r,g,b]` 三个 0~255 的自定义颜色，`brightness` 作为整体亮度缩放；
- 同时给出多个时按 `rgb` > `temp` > `mode` 取其一，一条请求只表达一种亮法；
- **三个亮法字段一个都不给 = 沿用当前亮法**：只调亮度或只开关的请求不会把色温/颜色打回白光。B 板一条命令只认一种亮法，所以服务端会把当前亮法展开进每条下发命令，调用方无需自己记住。

亮法示例：

```json
{ "status": "on", "brightness": 25, "mode": "night" }
{ "status": "on", "brightness": 80, "temp": 3000 }
{ "status": "on", "brightness": 50, "rgb": [255, 128, 0] }
{ "status": "on", "brightness": 60 }
```

响应：

```json
{
  "light_status": "on",
  "light_brightness": 80,
  "light_mode": "temp",
  "light_temp": 3000,
  "light_rgb": null,
  "message": "灯光已打开，亮度: 80%（色温 3000K）",
  "message_en": "Light turned on, brightness: 80% (color temperature 3000K)"
}
```

`light_rgb` 对外**一律是 `[r,g,b]` 三元列表**（库里存成 `"r,g,b"` 文本，接口层已归一）；不是自定义颜色时为 `null`。`light_mode` ∈ `white` / `night` / `temp` / `rgb`，`light_temp` 仅在 `mode:"temp"` 时有值。GET `/api/status` 里的同名字段口径完全一致。

### GET `/api/light-level/history?hours=24`

返回环境光敏 ADC 历史（**不是**灯具开关历史，后者见 `/api/light/history`）。返回数组，
元素形如 `{"timestamp": "YYYY-MM-DDTHH:MM:SSZ", "light_raw": 整数, "samples": N, "light_dark": 布尔}`：

- `timestamp`：ISO-8601 UTC、秒级、带 `Z`；最近 1 小时按秒分桶，更长窗口按时间分桶。
- `light_raw`：该桶光照 ADC 平均值取整（0~1023）；**读数越大越暗**（实测：捂住≈918、环境光≈479）。
- `samples`：该桶样本数；超过 7 天原始保留期后来自 `sensor_hourly` 小时归档。
- `light_dark`：布尔二态标注（`true`=暗），由后端按与自动化引擎**同款回差**逐点给出
  （raw≥730 判暗、raw≤670 判亮、区间内沿用上一点；窗口首个点落在区间时用中点兜底），
  口径与积木里的 `light_dark` 能力源一致，供历史页把「亮/暗」可视化。

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

供**不受本进程控制**的外部执行者（有人手工拨了继电器、另一台网关在操作）在动作已执行后
**只记账、不下发**，使面板状态/历史与真实硬件一致：

```json
{ "device": "door", "status": "open", "source": "voice" }
```

支持 `device` = `door` / `window` / `light` / `fan` / `ac`（ac 需传 `state` 对象）。

> 本接口**只记账、不下发硬件**（动作已由外部执行完），因此不会 503，
> 也不参与 `_cid`/`_seq` 收口器；成功后同样广播 `manual_control` 事件，
> 让「手动优先」类积木规则照常生效。窗口状态在此接受 `open/closed/normal`。
>
> ⚠️ 本系统的语音助手**已不再调用本接口**：串口归 web 独占后，语音走下面的工具网关，
> 执行与记账一次完成，无需二段式回传。

### 硬件工具网关（语音助手 / 外部程序共用）

> 串口归 web：`mcp_home_server.py` 是 web 的 MCP stdio 子进程，A/B 口只有它一个读者。
> 语音助手完全不碰串口，所有硬件动作都经这两个端点走 web，因此与面板**同权同账**。

#### GET `/api/hardware/tools`

返回全部 MCP 硬件工具的 function schema（语音助手启动时据此向大模型注册工具）：

```json
{ "tools": [ { "name": "door", "description": "…", "parameters": { "type": "object", "properties": { … } } } ] }
```

> MCP 未连接或串口未启用（`{"error":"硬件服务未就绪（MCP 未连接或串口未启用）"}`）→ 503。
> 调用方拿到的是扁平的 `name/description/parameters`，需要自行包成 OpenAI 的
> `{"type":"function","function":{…}}` 再交给模型（语音助手即这么做）。

#### POST `/api/hardware/tool`

静默执行一个工具（不经 LLM、不发语音），成功后做**与面板操作等价**的记账：

```json
{ "name": "door", "arguments": { "action": "open" }, "source": "voice", "timeout": 10 }
```

| 字段 | 说明 |
|------|------|
| `name` | 工具名，见 §4 |
| `arguments` | 对象，参数与 §4 完全相同 |
| `source` | `voice` / `web`，仅用于历史记录里的来源标注（缺省记为「外部」） |
| `timeout` | 可选，秒；缺省 10（`ac` / `ir` 为 20） |

响应：

```json
{ "ok": true, "name": "door", "result": "…" }
```

| 状态码 | 场景 |
|--------|------|
| 400 | `name` 为空 / `arguments` 不是对象 |
| 503 | 硬件桥未初始化（web 没起 MCP 子进程或串口未启用） |
| 502 | 工具执行返回失败（`ok:false`，`result` 里是错误文本） |

> 记账内容与面板点击完全一致：更新 SQLite 状态 → 写历史 → 广播 `manual_control`
> 事件（全屋切「手动优先」）。只有**执行器类**工具会记账，只读工具
> （`get_sensor_status` / `get_serial_health` / `get_output_state` / `self_test`）不动库。
>
> 同样**无鉴权**：能连到 :5000 即可操作硬件，本系统按可信局域网设计（见 §1）。

## 2.4 门禁（Access）

本模块只管「谁有什么凭证」和「把凭证录进来」；开门、延时关门、被拒报警都不在这里，
鉴权结果统一广播成 `access_granted` / `access_denied` 事件，由 /automation 页的积木规则决定。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/access/persons` | 授权人员列表（含人脸/房卡状态） |
| POST | `/api/access/persons` | 新增人员（只要姓名；凭证之后单独录入） |
| DELETE | `/api/access/persons/<id>` | 删除人员，并清掉他的注册照与识别身份 |
| POST | `/api/access/persons/<id>/enabled` | 停用 / 启用（凭证保留但不认） |
| POST | `/api/access/persons/<id>/enroll/face` | 录入人脸：前端从实时画面截的 base64 帧 |
| POST | `/api/access/persons/<id>/enroll/rfid` | 录入房卡：开一个等待刷卡的会话 |
| GET | `/api/access/enroll/rfid/<sid>` | 轮询录入会话状态 |
| DELETE | `/api/access/enroll/rfid/<sid>` | 取消录入会话 |
| GET | `/api/access/logs` | 通行记录列表 |
| GET | `/api/access/diagnostics` | 门禁体检 + 识别哨兵状态（页顶状态栏的数据源） |
| POST | `/api/access/test` | 链路自测：拿名单里的真实人员走完整鉴权（不碰硬件） |

`GET /api/access/persons` 返回：

```json
[{ "id": 1, "name": "张三", "face_id": "张三", "rfid_uid": "AA 53 0C 07",
   "enabled": true, "face_images": 6 }]
```

`face_id` 就是人脸库的目录名（清洗后的姓名），`face_images` 是该身份当前的注册照张数。

### 录入人脸（浏览器截帧）

`POST /api/access/persons/<id>/enroll/face` 请求（一次最多 12 帧，单帧 ≤4MB）：

```json
{ "images": ["data:image/jpeg;base64,...", "..."] }
```

后端逐帧检脸，太小的丢弃，合格的存进 `data/face/authorized/<face_id>/`，
重算该身份的均值原型并热加载识别器（认人立即生效，不用重启）：

```json
{ "message": "已录入 4 张人脸照片（张三）", "message_en": "Enrolled 4 face image(s): 张三",
  "detail": { "rejected": ["人脸太小"], "images": 6, "dir": "…/authorized/张三" },
  "person": { "…": "同列表行" } }
```

同一身份最多留最新的 20 张参与原型；重复点「录入人脸」是追加，不会产生第二个同名身份。

### 录入房卡（等待刷卡）

`POST …/enroll/rfid` 返回 `{"session": {"id": "1a2b3c4d", "state": "pending", …},
"timeout_seconds": 45}`，用户在这 45 秒内把卡贴到 A 板 RC522 上；前端轮询
`GET /api/access/enroll/rfid/<sid>`，`state` 依次为 `pending` / `matched`（带 `person`）/
`conflict`（卡已绑别人）/ `expired` / `error`。

等待会话存在时，这张卡会被录入流程取走而**不当作一次鉴权**（否则新卡必然记一条拒绝）。

### 自测

`POST /api/access/test` 请求 `{"method": "face"|"rfid", "person_id": 1}`，
身份取自数据库、走与真实刷卡完全相同的鉴权 + 日志 + 事件广播路径，返回：

```json
{ "granted": true, "person": "张三", "method": "face", "credential": "张三",
  "reason": null,
  "message": "验证通过，欢迎 张三!", "message_en": "Verified, Welcome 张三!" }
```

被拒时 `granted=false`、`reason` 是下面表里的代码，`message` 直接带上中文原因
（`未放行：人员已停用`）。自测**不去抖**：连点两次就该有两条日志。

> 该人员没有对应凭证时返回 400（`该人员还没有录入人脸/房卡`）。

### 拒绝原因（`deny_reason`）

鉴权不再只留一句「未知人员」：`access_logs.deny_reason` 与 `face_events.deny_reason`
存的是代码，双语文案在 `web/access_guard.py: DENY_REASONS`（前端词典
`access.reason_*` 与之一一对应）。

| 代码 | 含义 |
|------|------|
| `no_such_identity` | 凭证没登记过（刷脸时 = 这张脸没录过） |
| `identity_not_in_list` | 人脸库认得出这张脸，名单里没有对应人员 |
| `unmatched_face` | 画面里有人脸，但没匹配到任何已录身份（陌生人） |
| `disabled` | 人员已停用：凭证还在，但不放行 |
| `ambiguous` | 同一凭证挂在多个生效人员身上，一律拒绝 |
| `bad_credential` | 卡号格式非法 / 鉴权方式不支持 |

同一 `(method, credential)` 在 `face.watcher.repeat_window`（默认 8 秒）内重复读数
只算一次**通行动作**：读卡器抖一下（实测 51ms 内两次读数会开两次门）、人站在门口
被连拍，都不会重复开门、也不会在 `access_logs` 里刷出一串日志。被合并的次数在
`/api/access/diagnostics` 的 `recent_repeats` 里能看到；`POST /api/access/test`
与 `handle_face_result(debounce=False)` 显式绕过去抖，用于链路自测。

> **去抖不抑制 `face_events` 历史**（#75）：每一轮识别都会各自写一行，包括陌生人在
> 内（不再因空 `face_id` 被互相顶掉）。所以「同一人站 30 秒」的事件条数 = 识别轮数，
> 去抖与 `cooldown` 只抑制重复的开门动作与通行日志，不丢弃历史。

### 事件状态（`face_events.status`）

| 值 | 含义 |
|----|------|
| `granted` | 认出已登记身份且放行（`verified=1`） |
| `denied` | 有人脸但被拒；原因见 `deny_reason`（`unmatched_face` / `identity_not_in_list` / `disabled` / `ambiguous`） |
| `observed` | 这一轮没跑完人匹配（太远/节流/无脸/未唤醒/摄像头失败等），只留痕不算通过或拒绝；`deny_reason` 存轮次种类 |

判定结果**一次落终态**：放行瞬间 `GET /api/face/events/latest` 即为 `granted`，
不再有先写 `pending` 再更新的中间态（旧库遗留的 `pending` 行前端显示为「判定中」）。
`observed` 轮次的环境类种类（`idle` / `no_camera` / `no_identity`）只在**状态变化**
时写一行，避免每 2 秒的取帧轮询把表刷满；太远/节流/无脸/出错等轮次逐轮记录。

### 体检：名单、人脸库、哨兵三方对齐

`GET /api/access/diagnostics` 只读，把「录了脸却不开门」的可能原因一次列全 ——
这些原因过去散在三处（库里没这张脸、名单里没这个人、哨兵没在跑），逐处排查太慢。

```json
{ "orphan_identities": ["person_02"],
  "persons_without_photos": [{"id": 1, "name": "管理员"}],
  "ambiguous_face_ids": [], "dead_aliases": ["FACE002"],
  "library_count": 1, "persons_count": 3,
  "watcher": { "enabled": true, "running": true, "interval": 2.0, "cooldown": 60.0,
               "min_face_px": 60, "snapshot_url": "http://…/snapshot",
               "camera_error": null, "model_ready": true, "identities": 1,
               "gate": {"open": false, "mode": "motion_idle", "motion": false,
                        "motion_age_s": 3.2, "gated": true},
               "last": {"kind": "granted", "person": "张三", "age_s": 4.1},
               "counts": {"attempts": 12, "granted": 1, "denied": 2, "strangers": 0} },
  "recent_repeats": [{"method": "face", "credential": "张三", "repeats": 1, "age_s": 2.4}],
  "recognition": { "method": "arcface_onnx", "similarity_threshold": 0.5 } }
```

- `orphan_identities`：人脸库有目录、名单里却没这个人 → 刷脸必然按
  `identity_not_in_list` 拒绝（旧演示数据或删人没清目录留下的）。
- `persons_without_photos`：生效人员一张注册照都没有 → 永远认不到他。
- `dead_aliases`：`known_faces` 里既不在名单也不在库里的别名（模拟模式演示残留）。
- `watcher.gate.mode`：`always`（没接 A 板 / 不门控）/ `motion_active` / `motion_idle`。
- `watcher.last.kind`：哨兵最近一轮的判定，取值 `granted` `denied` `no_face` `too_far`
  `cooldown` `duplicate` `throttled` `no_camera` `no_identity` `idle` `error`；
  门禁页顶部那条状态栏就是把它连同计数翻成一句人话。

## 2.5 人脸（Face）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/face/recognize` | 识别单帧并留痕（body：`{"image":"<base64>"}`，≤5MB） |
| GET | `/api/face/status` | 引擎状态（是否模拟模式、阈值等） |
| GET | `/api/face/config` | 读取配置 |
| POST | `/api/face/config` | 保存配置并重载模型 |
| POST | `/api/face/reload` | 重新加载模型 |
| GET | `/api/face/known` | 已知人脸映射 |
| POST | `/api/face/known` | 添加已知人脸 `{face_id, name}` |
| DELETE | `/api/face/known/<face_id>` | 删除已知人脸 |
| POST | `/api/face/notify` | 边缘设备推送识别结果：**鉴权 + 记录 + 发事件**（开门由积木规则做） |
| GET | `/api/face/events?limit=20` | 识别事件 |
| GET | `/api/face/events/latest` | 最近一次识别事件，额外带 `age_s`（距今秒数，后端按 UTC 算） |

`/api/face/events/latest` 的 `age_s` 是给门禁页判新鲜度用的：库里存的是 UTC naive
时间串，浏览器自己按本地时区减会差一个时区，所以「这条多久前」只能由后端算。
页面拿到 `age_s > 90` 就当它不是刚发生的判定（等待态 +「最后一条记录是 X 前」），
因为 `POST /api/face/notify` 是开放通道，任何脚本都能塞进一条 FACE001/95% 的假放行，
过去面板会把它当实时结果常驻显示。

`POST /api/face/recognize` 命中节流时不改状态、不报错，返回 200：

```json
{ "detected": false, "face_id": null, "confidence": 0, "score": null, "faces": [],
  "mode": "throttled", "message": "请求过于频繁，请等待 1.2 秒" }
```

> 识别节流在 `web/face/engine.py`（`face.recognition_interval`，默认 1.5 秒），
> 门口哨兵的取帧间隔（`face.watcher.interval`）应大于它，否则每轮都会被挡掉一次。

`POST /api/face/recognize` 也会**留痕**（#75）：识别到的这一轮会写一条
`device_source='web'` 的 `face_events` 行（认出身份 → `granted`/`denied`；无脸 → 
`observed`/`no_face`；命中节流 → `observed`/`throttled`）。与 `/api/face/notify`
不同，它一律 `record_only`：**不广播门禁事件、不写通行日志、不开门**，这样无鉴权的
单帧接口不会变成远程开门通道；它只是「网页自测」的来源，和 `docs/api.md` 对
`device_source='web'` 的定义一致。

### 谁在跑识别：内置哨兵

`face_events.device_source` 说明这条结果是谁产生的：`face_watcher`（web 内置的门口
识别哨兵，默认来源）、`orange_pi`（边缘设备经 `/api/face/notify` 推送）、
`web`（网页自测/单帧识别）。

哨兵在 `web/face_watcher.py`：摄像头只出流、模型只装在 web 进程里，过去没有任何一方
取帧，所以「录进人脸也不会自动开门」。它按 `face.watcher.interval` 取
`<摄像头服务>/snapshot` 的一帧 → `FaceEngine.recognize_jpeg` →
`AccessGuard.handle_face_result()`，识别与鉴权走的正是 `/api/face/notify` 那条路径。
默认只在 A 板 PIR 报「有人」后的 `motion_hold` 秒内抓帧（派上单核，常驻 YOLO 会拖死
语音与传感器轮询）；从未收到过 motion 时退化为常转。参数与开关见
[configuration.md](configuration.md) 的 `face.watcher.*`。

`POST /api/face/notify` 请求：

```json
{
  "face_id": "person_01",
  "score": 0.72,
  "detection_confidence": 0.96,
  "image_path": "data/face/captures/x.jpg",
  "device_source": "orange_pi"
}
```

`score` 是 ArcFace 嵌入余弦相似度，也是门禁页展示的数值；
`detection_confidence` 是 YOLO 判断画面中是否有人脸的置信度，两者不能混用。
旧边缘端若仍把 ArcFace 相似度放在 `confidence`，后端会兼容接收，但新代码应改传
`score`。旧历史事件没有独立 `score`，页面显示 `--`，不会把 YOLO 数值误标成 ArcFace。

授权通过时返回 `{"granted": true, "person": "张三", "face_id": "…", "event_id": 12,
"reason": "matched", "message": "欢迎 张三!"}`，并：
写 `access_logs`（granted）+ 更新 `face_events` 状态 → 向自动化引擎投递
`{"event":"access","status":"granted","method":"face",…}` 事件（积木里对应
`access_granted`，可按 `method` 筛选）。**开门动作不写死在这里**，
由内置规则 `access_open_door`（门禁·验证通过 → 开门）执行，可在自动化页停用或改成
「先播报欢迎语」；未授权记 denied 并广播 `access_denied`，
需要报警时挂一条 `access_denied_buzzer` 规则即可（默认停用）。

> 本接口同样**无鉴权**：能连到 :5000 的客户端可以伪造 `face_id` 触发开门规则。
> 需要收紧时，请在边缘设备与 Web 之间自行加反向代理/网络隔离，或删掉那条积木规则。

## 2.6 自动化（Automation）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/automation/capabilities` | Blockly 下拉元数据（传感器/事件/执行器 + 全局状态变量） |
| GET | `/api/automation/rules` | 规则集（首启迁移过旧规则时附带 `migration` 字段） |
| PUT | `/api/automation/rules` | 保存规则集（整体替换，含校验） |
| GET | `/api/automation/preview` | 当前数据下各规则触发/条件判定预览（不执行） |
| POST | `/api/automation/rules/<rule_id>/run` | 立即手动执行一条规则 |
| POST | `/api/automation/rules/restore` | 恢复被删除的内置规则 |
| GET | `/api/automation/logs?limit=30` | 规则执行日志 |
| GET | `/api/automation/oled` | OLED 轮播配置 |
| PUT | `/api/automation/oled` | 保存 OLED 轮播配置 |

### 全局状态

「自动/手动/离家」这类屋子状态不再是引擎里的硬编码状态机，改由积木在**全局状态**
（自由命名的变量，id 形如 `g:全屋模式`）上读写。变量的增删改查走这组接口，id 需 URL 编码。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/automation/global_state` | 全部变量定义与当前值 |
| POST | `/api/automation/global_state` | 新建变量 |
| PUT | `/api/automation/global_state/<id>` | 改变量（改名/标签/选项/手动写值/`op:"toggle"` 翻转） |
| DELETE | `/api/automation/global_state/<id>` | 删除变量 |

`POST /api/automation/global_state` 请求示例：

```json
{
  "name": "全屋模式",
  "type": "enum",
  "value": "auto",
  "choices": ["auto", "manual", "away"],
  "choice_labels": { "auto": "自动", "manual": "手动", "away": "离家" }
}
```

`type` 取 `bool` / `number` / `enum` / `text`；名字不得含空格或 `:` `：`，最长 24 字。
积木侧：读用「条件 → 全局状态」的三块专用积木（是/否、数值比较、选项等于），写用
「动作 → 全局状态」积木；新建/改名/删除（以及一次性设置当前值）用自动化页的那块
顶层「状态定义」积木——它在列表页就是一条与规则并列的「📌 状态」条目。

### HTTP 出站动作（对接外部系统）

动作块 `device: "http"` 把规则结果推给外部系统（NAS / Home Assistant / MQTT 网关 / 自建服务）：

```json
{ "device": "http", "method": "post",
  "url": "http://127.0.0.1:8101/say",
  "text": "{\"text\":\"温度 {temperature} 度，请留意\"}" }
```

| 字段 | 说明 |
|------|------|
| `method` | `get` / `post`，缺省 `post` |
| `url` | ≤500 字符；可含 `{temperature}` 等占位符（与 OLED 同一套数据源，但不受 16 列 ASCII 裁剪） |
| `text` | POST 正文，≤2048 字节（UTF-8）；以 `{` 或 `[` 开头且能解析时按 `application/json` 发，否则 `text/plain`；GET 忽略 |

护栏（写死在 `web/automation/webhook.py`）：

- **默认只放行回环与内网**：`127.0.0.1`、`localhost`、RFC1918、`*.local`/`*.internal`/`*.lan`
  与不带点的主机名；公网地址与 `169.254.*`（云厂商元数据）默认拒绝。
- 放开方式二选一：`automation.http_allowed_hosts: ["hooks.example.com"]` 逐台登记，
  或 `automation.http_allow_public: true` 全放开；`automation.http_enabled: false` 整条通道关闭。
- **不带任何凭据**：URL 里出现 `user:pass@` 直接拒绝，请求也不发 `Authorization`/`Cookie`
  ——规则 JSON 是明文，且 `GET /api/automation/rules` 无鉴权。
- **不跟随 3xx**：跳转视为失败（`HTTP 302 跳转到 …（出于安全不跟随重定向）`）。
- 超时 `automation.http_timeout`（默认 2 秒，夹到 0.2~8 秒）；目标不可达只让这条动作失败，
  结果进 `/api/automation/logs`，不影响规则线程与其它动作。

页面 `PUT /api/automation/rules` 保存时按上面的主机策略当场校验（不合规返回 400）；
引擎读盘只校验 URL 格式，**每次执行前再按当时策略复查**，因此改配置无需重存规则。

## 2.7 摄像头与语音代理

### 摄像头

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/camera/status` | `{enabled, stream_url, stream, camera}`；`camera` 是上游 `/health` 的原样结果（`online / device / frame_age_s / error / capture_alive`） |
| GET | `/api/camera/stream` | **MJPEG 实时流**（`multipart/x-mixed-replace`）；上游连不上返回 503 |

`camera.online=false` 表示服务活着但此刻没画面（未插、被别的进程占着、或刚拔下），
`camera.error` 会写清原因；摄像头没插时 `/api/camera/stream` 仍返回 200 并发送
「NO CAMERA」占位帧，前端因此能显示问题而不是空转等待。

### 语音（对 :8101 的同源代理）

地址来自 `voice.url`（或环境变量 `SMART_HOME_VOICE_URL`），默认 `http://127.0.0.1:8101`；
这条通道只做「唤醒 / 文本指令 / 状态 / 对话实况」，与硬件链路无关。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/voice/status` | 语音助手在线状态 + 状态机（IDLE/COMMAND/THINKING/FOLLOWUP）；离线时 503 |
| POST | `/api/voice/wake` | 免唤醒词进入指令模式 |
| POST | `/api/voice/say` | 直接下发文本指令 `{"text":"..."}` |
| GET | `/api/voice/events` | **SSE 对话实况流**（原样透传语音助手 `/events`，`text/event-stream`） |

> `POST /api/voice/wake|say`：上游不可达或返回非 2xx → 502；`text` 为空 → 400。
> `/api/voice/events` 上游连不上时返回一条 `{"type":"system","text":"语音助手不可达（…）"}`
> 事件后结束（HTTP 仍是 200，前端 `EventSource` 会自动重连）。

## 2.8 Home Assistant 代理（可选通道）

设备主控制链路是 MCP 直连 Arduino；这组路由保留 HA 配置/探测/代理能力，
供硬件管理页在已部署 Home Assistant 的环境里映射实体、取摄像头画面与历史。
未配置 HA 时这些接口不会报错，只会返回空结果或 `connected:false`
（配置存 `data/ha_config.json`，也可由 `POST /api/ha/config` 写入）。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/ha/connection` | 探测连通性（`ha_client.test_connection()` 原样返回） |
| GET | `/api/ha/config` | 读 `{ha_config, device_mapping, ha_url, ha_token}` |
| POST | `/api/ha/config` | 保存 `{ha_url, ha_token, device_mapping}` |
| GET | `/api/ha/devices` | 发现的实体；无结果时 `{"devices": [], "message": "…"}` |
| POST | `/api/ha/mapping` | 更新一类设备的实体映射 `{device_type, entity_id}` |
| GET | `/api/ha/temperature` | 经 HA 取温度（`{"temperature": …}`） |
| GET | `/api/ha/humidity` | 经 HA 取湿度 |
| POST | `/api/ha/light` | `{action, brightness}`，`action` 缺省 `toggle` |
| POST | `/api/ha/fan` | `{speed}`（百分比） |
| POST | `/api/ha/ac` | `{mode, temperature}`，`mode` 缺省 `off` |
| POST | `/api/ha/door` | `{action}`，缺省 `unlock` |
| GET | `/api/ha/door/status` | `{"status": …}` |
| GET | `/api/ha/window/status` | `{"status": …}` |
| GET | `/api/ha/camera` | JPEG 快照；取不到时返回 200 + `{"error": "…"}` |
| GET | `/api/ha/history?entity_id=…&hours=24` | 实体历史；缺 `entity_id` → 400 |

> 这些路由的响应形态沿用 HA 客户端返回的原字段，不保证带 `message_en`；
> 与 §2.3 的设备控制接口**互不影响**（后者走 MCP/串口，前者走 HA REST）。

---

# 3. 语音助手 HTTP API（:8101）

零依赖标准库实现，供手机网页、GPIO 按钮、外部程序与 Web 容器调用。
语音助手**不碰串口**：硬件动作一律经 web 的 `POST /api/hardware/tool`（见 §2.3），
本服务不再有 `/tool`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 内置控制台网页（聊天式深色对话界面：麦克风 + 文本输入 + 对话实况） |
| GET/POST | `/trigger` | 开启语音监听（进入 COMMAND） |
| GET | `/say?text=<文本>` | 直接下发文本指令 |
| POST | `/say` | 下发文本指令，body：`{"text":"..."}` |
| GET | `/state` | 返回当前状态机状态 |
| GET | `/events` | **SSE 对话实况流**（`text/event-stream`） |

### GET `/state`

```json
{ "state": "IDLE" }
```

### GET `/events`

`Content-Type: text/event-stream`，每条事件一行 `data: {json}\n\n`，空闲 15 秒发一次
`: ping` 注释行做心跳（防代理掐断）。新连接先收 `hello`（含最近历史），随后实时增量。

| `type` | 附带字段 | 含义 |
|--------|---------|------|
| `hello` | `state`, `history`, `info` | 建连首包：当前状态机 + 环形历史（最近 200 条）+ 摘要（网关/LLM） |
| `state` | `state` | 状态机切换（IDLE/COMMAND/THINKING/FOLLOWUP） |
| `partial` | `text` | 流式 ASR 的中间结果 |
| `user` | `text`, `source` | 一句完整用户指令（`source` 如「语音」「键盘」） |
| `delta` | `text` | 大模型回复的流式 token |
| `tool` | `name`, `arguments`, `ok`, `result` | 一次硬件工具调用（经 web 网关执行）及其结果 |
| `turn_end` | — | 本轮回答结束 |
| `system` | `text` | 系统提示（唤醒成功、已打断播报、调用失败等） |

每条事件都带 `ts`（Unix 秒）。浏览器用 `new EventSource('/events')` 即可；
Web 面板经 `GET /api/voice/events` 同源代理同一条流（见 §2.7）。

可在 `/trigger` / `/say` 请求头加 `X-Trigger-Source` 标记来源（仅日志/记账用途，**不是鉴权**）。

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

`mcp_home_server.py` 以 stdio 方式提供 MCP 服务，由 **web 作为子进程启动并独占 A/B 串口**，
共 **14 个工具**。其中 `light` 路由到 **Module A**（A0 灯带），其余执行器/显示工具与
`get_distance`/`self_test` 路由到 **Module B**。本进程之外的调用方（语音助手 / 外部程序）经 web 的
`POST /api/hardware/tool` 以 HTTP 方式调用（工具名/参数相同，见 §2.3）。

| 工具 | 主要参数 | 作用 |
|------|---------|------|
| `light` | `action`, `value`, `r`,`g`,`b`, `count` | 灯光（**执行于 A 板 A0**）：off / white / night / 预设色 / rgb / pixels（**没有 `on`**；`temp` 已停用，A 板无该分支；`value` 是 0~255 亮度，缺省 255、夜灯缺省 60；`pixels` 需 `count` 1~8） |
| `door` | `action` = open/close | 门 |
| `window` | `action` = open/close/normal | 窗 |
| `fan` | `action` = on/off/set_speed, `value` | 风扇 |
| `buzzer` | `action` = on/off/beep, `count`,`on_ms`,`off_ms` | 蜂鸣器 |
| `oled` | `action` = show_text/clear, `line`,`text` | OLED |
| `display` | `action` = show_time/show_number/clear | 数码管（TM1637 已裁剪，返回 error） |
| `ir` | `code` 或 `address`+`command` | 红外 NEC 发射 |
| `ac` | `power`,`mode`,`temperature`,`fan`,`swing_ud`,`swing_lr` | 美的空调（生成状态帧走 send_midea） |
| `get_sensor_status` | 无 | 查询全部传感器 + 最近事件 |
| `get_serial_health` | 无 | 串口链路健康度：A/B 连接、B 板复位次数、最近引脚告警、心跳失败数、**最近一条设备命令及其固件回读**（只读排障） |
| `get_output_state` | 无 | B 板（执行器）硬件回读状态：门/窗/风扇/灯/蜂鸣器实际电平 + 观测时刻 + 最近命令（只读） |
| `get_distance` | 无 | B 板 HC-SR04 实时测距（V2.10+），厘米；仅 `valid=true` 时距离有效。见 [调用示例](ultrasonic.md) |
| `self_test` | 无 | B 板固件自检（V2.9+）：命令成败计数、风扇两脚方向/电平、灯带 `show()` 次数、数据脚拉高/拉低读回（只读） |

调用示例（`POST /api/hardware/tool` 的 body）：

```json
{ "name": "fan", "arguments": { "action": "set_speed", "value": 150 } }
```

```json
{ "name": "ac", "arguments": { "mode": "cool", "temperature": 26 } }
```

> 红外 NEC 码也可用 `address` + `command`，由服务端按 NEC 帧序拼码，避免手算。

---

# 5. 本地 LLM API（qwen_server.py，:8000，离线兜底）

OpenAI 兼容接口（llama.cpp 后端）。

> **默认不走这里**：语音助手默认用硅基流动（`llm.mode: siliconflow`，
> `https://api.siliconflow.cn/v1`，OpenAI 兼容；备选百炼 `dashscope`）。
> 本地服务是离线兜底：`llm.mode: local` + `base_url: http://<host>:8000/v1`
> （Docker 下叠加 `docker-compose.local-llm.yml` 才会起 `qwen` 容器）。

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
| GET | `/` | 内嵌查看页（引用 `/video_feed`，附 `/health` 链接） |
| GET | `/video_feed` | **MJPEG 视频流**（`multipart/x-mixed-replace; boundary=frame`）；无画面时发「NO CAMERA」占位帧 |
| GET | `/snapshot` | **最新一帧 JPEG**（`Cache-Control: no-store`）；没有新鲜画面时 503 + `{"error": "摄像头当前无新鲜画面"}`，不拿占位帧冒充 |
| GET | `/health` | `{online, device, frame_age_s, error, capture_alive}`；采集线程活着=200，线程死了=503 |

`/snapshot` 是给 web 里的门口识别哨兵取单帧用的（见 §2.5）：它要的是「现在这一帧」，
不是占位图，所以宁可 503 让哨兵报 `no_camera`，也不能让识别器把「NO CAMERA」当画面认。

浏览器直接打开 `http://<host>:8080/video_feed` 或 `http://<host>:8080/` 即可查看。

热插拔行为（容器与服务都可以先于摄像头起来）：

- 每轮重开前重新枚举 `/dev/video*`，所以拔插换了序号（video0 → video1）也能找回；
  `--cam` / `CAMERA_DEVICE` 只是**优先候选**，不是唯一候选。
- 读帧失败 → 释放旧句柄 → 退避重开（1s 起指数增长，封顶 10s）；一根设备都没有时
  也只是持续重试，进程不退出。
- 这台 UVC 摄像头**同一时刻只允许一个进程打开**：被别的容器/进程占着时会一直
  重试，等对方释放后自动接上（`/health` 期间报 `online: false`）。

### 八灯珠灯光面板

`POST /api/light` 新增可选整数 `count`（1~8）。例如：
`{"status":"on","brightness":40,"rgb":[255,128,0],"count":4}`。
面板使用微光 2 颗、柔光 4 颗、明亮 6 颗、全灯 8 颗四档，独立调整颜色与亮度。
接口响应及 `/api/status` 新增 `light_count`；数据库新增可空整数列，无运行数据迁移丢失。
未传 count 沿用当前分档；首次使用旧记录按原协议执行。关灯保留颜色与分档。
显式旧 `mode`/`temp` 命令仍按原协议执行并清除分档；面板不再提供色温调节。
旧记录的原始 `/api/status.light_count` 可为 null，面板按夜灯 2 颗、其余 8 颗显示。
新增 pixels 指令要求先刷写 B 板固件，否则操作失败且不记账。
