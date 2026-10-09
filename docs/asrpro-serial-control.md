# ASRPRO 串口控制接口规范（SH1 / SH2）

> 状态：**接口已确认**。SH1（旧命令）继续可用；SH2 意图注册表已在
> [`PC_Test/asrpro_bridge.py`](../PC_Test/asrpro_bridge.py) 落地并通过单测。
> 具体场景（出门天气、门禁欢迎词等）不在本文件实现，见 §13。

本文件是 ASRPRO 天问开发板 → 香橙派桥接进程的唯一接口规范，供固件与
集成方对照开发。

## 1. 目标与边界

ASRPRO 只发送**意图**；由香橙派调用现有、受认证的 Web 硬件网关去控制实体设备。
它是"输入适配层"，不代替场景引擎，也不直接操作 A/B 板。

- 后续增加命令时，不必重写串口读取、应答、超时和错误处理；
- 旧版 `SH1` 1–9 号命令继续可用，已烧录的语音模型无需重做；
- ASRPRO 只能调用香橙派**启动时载入的白名单**意图（内置默认 + 配置文件），不能透传任意工具名、URL 或 Arduino 原始帧，也**不能通过串口注册意图**；
- 每次物理动作都有请求编号和明确结果，**超时后不自动重试**；
- 单元测试使用模拟网关，不打开真实串口、不驱动真实设备。

## 2. 架构

```text
ASRPRO 关键词/离线识别
        │  SH1 / SH2 帧（UART）
        ▼
asrpro_bridge 串口适配器（香橙派宿主进程）
  ├─ 帧解析与长度限制
  ├─ 意图注册表（白名单，编译期冻结）
  ├─ 参数 schema 校验
  ├─ 请求去重与超时控制
  └─ 统一结果映射
        │  Bearer Token + HTTP
        ▼
Web /api/hardware/tool 或只读 /api/status
        │
        ▼
现有 A/B 板串口独占进程（MCP）→ 实体设备
```

## 3. 接线与传输约定

- ASRPRO 使用板载 Type-C/CH340 对应的默认 `Serial`（UART0），115200、8N1、ASCII；
- 用支持数据传输的 USB 线接香橙派 **USB Host**；连不上时 `lsusb` 看不到 CH340，
  换 USB-A Host 口 + USB-A 转 Type-C 数据线（仅供电的线不行）；
- 设备路径必须固定到 ASRPRO 的 `/dev/serial/by-id/` 或 `/dev/serial/by-path/`，
  **不得占用 A/B 板的 `/dev/ttyACM*`**；
- 每帧以 `\n` 结束，兼容 `\r\n`；单帧最多 **127 字节**，超长、乱码、未知版本整帧丢弃；
- **一次只允许一个请求在途**；同一请求编号的重复帧按 §6 去重处理。

## 4. SH1（旧协议，保留）

```text
请求  SH1 <请求编号> <命令ID>
应答  SH1 <请求编号> <命令ID> <类型> <数值A> <数值B>
```

| 命令 ID | 口令 | 行为 | 应答类型 |
|---|---|---|---|
| 1 | 开灯 | 白光，亮度 255 | `OK` |
| 2 | 关灯 | 关闭灯光 | `OK` |
| 3 | 开门 | 执行开门指令 | `OK` |
| 4 | 开窗 | 执行开窗指令 | `OK` |
| 5 | 开风扇 | 风扇全速 | `OK` |
| 6 | 关风扇 | 停止风扇 | `OK` |
| 7 | 当前温度 | A 板最新温度 | `TEMP`（×100） |
| 8 | 当前湿度 | A 板最新湿度 | `HUM`（×100） |
| 9 | 现在几点 | 香橙派系统时间（UTC+8） | `TIME`（时/分） |

类型取值：`OK` / `ERR` / `TEMP` / `HUM` / `TIME`。温湿度为实际值 ×100，时间取整点/分。
传感器离线、无效值与网关错误一律返回 `ERR`，不播报成功。

## 5. SH2 请求帧

```text
SH2 <请求编号> <意图名> [<参数名>=<参数值> ...]
```

约束：

- 请求编号：`1..999999999`；
- 意图名：`[a-z][a-z0-9_]{0,31}`；
- 参数名：`[a-z][a-z0-9_]{0,15}`；
- 参数值：注册处理器声明的整数、枚举或布尔值，字符集 `[A-Za-z0-9_]`，**不接受自由文本**；
- 参数顺序不影响语义；重复参数、未知参数、缺少必填参数**整帧拒绝**。

合法示例：

```text
SH2 104 light action=white value=128
SH2 105 door action=open
SH2 106 ac mode=cool temperature=26 fan=mid
SH2 107 status
```

禁止（意图不在白名单 / 试图透传）：

```text
SH2 108 call_url url=...
SH2 109 raw_serial data=...
SH2 110 hardware_tool name=door action=open
```

## 6. SH2 应答帧

```text
SH2 <请求编号> <意图名> <结果码> [<参数名>=<参数值> ...]
```

| 结果码 | 含义 | ASRPRO 建议行为 |
|---|---|---|
| `OK` | 意图处理成功 | 播放对应成功音频 |
| `REJECTED` | 意图或参数不在白名单 | 播放"暂时无法执行" |
| `FAILED` | 网关明确返回失败 | 不播报成功 |
| `TIMEOUT` | 结果未知，可能已动作 | 提示未确认，**禁止自动重发** |
| `BUSY` | 上一请求尚未结束（**预留**，当前同步调度不会发出） | 播放"请稍后再试" |

示例：

```text
SH2 105 door OK
SH2 106 ac FAILED
SH2 107 status OK humidity=6000 sensor_online=1 temperature=2530
```

**去重**：香橙派按请求编号缓存最终结果。重复帧（同编号同意图）直接回放缓存应答，
**不会再次动作**；同编号但内容不同则返回 `REJECTED`。

## 7. 意图清单（第一批）

仅映射现有 A/B 板工具，不含场景意图。参数表列 `name`（类型，取值范围，是否必填）。

| 意图 | 网关工具 | 参数 | 示例 |
|---|---|---|---|
| `light` | `light` | `action`(enum: off/white/night/temp/red/green/blue/yellow/purple/cyan/rgb/pixels，必填)；`value`(int 0–255)；`r`/`g`/`b`(int 0–255)；`temp`(int 2700–6500)；`count`(int 1–8) | `SH2 1 light action=rgb r=255 g=128 b=64 value=200` |
| `door` | `door` | `action`(enum: open/close，必填) | `SH2 2 door action=open` |
| `window` | `window` | `action`(enum: open/close/normal，必填) | `SH2 3 window action=normal` |
| `fan` | `fan` | `action`(enum: on/off/set_speed，必填)；`value`(int 0–255) | `SH2 4 fan action=set_speed value=128` |
| `buzzer` | `buzzer` | `action`(enum: on/off/beep，必填)；`count`(int 1–100)；`on_ms`/`off_ms`(int 1–60000) | `SH2 5 buzzer action=beep count=2` |
| `ac` | `ac` | `power`(bool)；`mode`(enum: auto/cool/heat/dry/fan)；`temperature`(int 17–30)；`fan`(enum: auto/low/mid/high)；`swing_ud`/`swing_lr`(bool) | `SH2 6 ac mode=cool temperature=26` |
| `status` | 只读 `/api/status` | 无 | `SH2 7 status` |
| `list_intents` | 只读（无网关调用） | 无 | `SH2 8 list_intents` |

说明：

- 布尔值接受 `1/0`（也接受 `true/false`）；温度/湿度在应答中按 ×100 的整数返回（与 SH1 一致）；
- `status` 为只读：离线或无效样本会被**省略**，不伪造数值（例如仅回 `sensor_online=0`）；
- `light` 的 `pixels`、`ac` 等动作依赖对应固件版本，旧固件会返回 `FAILED`。

### 7.1 动态意图（配置驱动）

意图表在**启动时**从 JSON 载入，增改意图**无需改代码**。来源优先级：

1. `--intents <file>` 或环境变量 `ASRPRO_INTENTS_CONFIG` 指定的 JSON 文件；
2. 未指定、文件缺失、JSON 损坏或 schema 非法时**回退内置默认注册表**（上表 8 个意图，含只读发现），
   并记一条 warning。

配置格式（与内置结构一致）：

```json
{
  "intents": {
    "curtain": {
      "tool": "window",
      "arguments": {"action": {"kind": "enum", "required": true,
                               "choices": ["open", "close"]}}
    }
  }
}
```

约束与安全边界：

- 意图名须匹配 `[a-z][a-z0-9_]{0,31}`，参数名 `[a-z][a-z0-9_]{0,15}`；`kind` ∈ `int|enum|bool`，
  `enum` 必须有非空 `choices`；**任一条非法则整份配置作废并回退默认**；
- 每个意图要么指向一个**网关工具**（`tool`），要么指向**内置只读处理器**（`reader` ∈
  `status`/`list_intents`），二者只能取其一；
- **串口侧不能注册、修改或删除意图**；配置只由管理侧（香橙派本地）在启动时读取，
  运行时热重载**预留**（同样不经串口）。

### 7.2 意图发现（只读）

ASRPRO 可用只读意图 `list_intents` 查询当前注册表：

```text
请求  SH2 8 list_intents
应答  SH2 8 list_intents OK count=8 intents=ac,buzzer,door,fan,light,list_intents,status,window
```

`count` 为意图总数；`intents` 为**逗号分隔**的已排序意图名（应答无需遵守请求侧的
`[A-Za-z0-9_]` 值字符集）。注册表过大放不进单帧时，仅回 `count=`、省略 `intents=`。

## 8. 反向播报（预留）

场景需要香橙派**主动**让 ASRPRO 播报（如进门欢迎词、天气播报）时，预留下行帧：

```text
SH2 0 notify speech=<音频资源ID>
```

`0` 表示非请求编号（主动播报）；`speech` 是**预先烧录**的音频资源 ID，不是自由文本 TTS。
该帧需 ASRPRO 固件配合实现，暂未启用；动态文本（天气数值）应改用受限结构化字段或由
香橙派音频服务播放，不能把任意网络文本交给执行器协议。

## 9. 香橙派处理接口

桥接服务内的抽象（已在 `asrpro_bridge.py` 落地）：

- `DEFAULT_INTENTS` / `load_intents()`：内置默认注册表 + 启动时从 JSON 载入（见 §7.1）；
  `Intent(tool, arguments, reader)` + `Arg(kind, required, choices, minimum, maximum)`；
- `Bridge._handle_sh2()`：解析 → 去重 → 校验 → `_execute()` → 应答；
- `Bridge._execute()`：单次调用网关，`TimeoutError → TIMEOUT`，其余异常 → `FAILED`，**不重试**；
- `Bridge._validate()` / `_coerce()`：参数 schema 校验与类型转换。

处理器拿不到服务令牌、串口对象或任意 HTTP 客户端。注册表在启动载入后冻结；运行时只能
**发现**（`list_intents`），不能通过串口添加、修改或删除意图。

## 10. ASRPRO 侧集成示例（天问 Block C++）

以下片段与 [`firmware/asrpro/smart_home.cpp`](../firmware/asrpro/smart_home.cpp) 同风格，
可直接替换其 `requestCommand()` / `replyMatches()`：把"命令 ID"换成分意图名与参数。

```cpp
// 发送一条 SH2 意图并等待应答；超时只提示，不重发（结果可能未知）。
static void sendIntent(const char *intent, const char *args) {
    while (Serial.available()) Serial.read();
    if (++sequence > 999999999UL) sequence = 1;
    char request[128];
    snprintf(request, sizeof(request), "SH2 %lu %s%s\n", sequence, intent, args);
    Serial.print(request);

    char line[128];
    unsigned used = 0;
    bool dropping = false;
    uint32_t started = millis();
    while ((uint32_t)(millis() - started) < 8000UL) {
        while (Serial.available()) {
            int ch = Serial.read();
            if (ch == '\n') {
                line[used] = 0;
                if (!dropping) handleReply(line, sequence);   // 见下
                used = 0; dropping = false;
            } else if (!dropping && ch != '\r') {
                if (used < sizeof(line) - 1) line[used++] = (char)ch; else dropping = true;
            }
        }
        delay(5);
    }
    play_audio(214);   // 等待回复超时，执行结果未确认（禁止自动重发）
}

static void handleReply(char *line, unsigned long request) {
    unsigned long rid = 0; char intent[32], code[16];
    if (sscanf(line, "SH2 %lu %31s %15s", &rid, intent, code) != 3 || rid != request) return;
    if (!strcmp(code, "OK"))            play_audio(301);   // 成功提示
    else if (!strcmp(code, "REJECTED")) play_audio(302);   // 暂时无法执行
    else if (!strcmp(code, "TIMEOUT"))  play_audio(214);   // 结果未确认
    else                                play_audio(213);   // 执行失败
}
```

调用示例：`sendIntent("door", " action=open");`、`sendIntent("status", "");`。
`sequence`、`play_audio()`、`Serial` 均沿用现有固件定义；新增音频资源需在天问软件里
生成对应数字播报条目。

## 11. 安全与可靠性要求

- 执行动作必须经过现有 Web 服务鉴权、工具 schema 和审计记录；
- 串口设备路径固定，不得占用 A/B 板端口（见 §3）；
- 动作调用**不自动重试**；`TIMEOUT` 表示"结果未知"，不能等同失败后再开门；
- 用有界缓存记录 `(请求编号 → 最终结果)`，重复帧只回放缓存结果；同编号不同内容拒绝；
- 串口日志只记录版本、请求编号、意图名、结果码和耗时，不记录令牌、自由文本或完整 HTTP 响应；
- 开门、车库门等高影响动作应单独设置允许条件、冷却时间和传感器校验；
- 超声波"检测到车/人"不能只靠单次距离值，应使用连续样本、阈值回差和冷却时间。

## 12. 测试契约

`PC_Test/tests/test_asrpro_bridge.py` 覆盖（全部使用 fake gateway，不连真实串口）：

- SH2 合法动作意图正确调用网关并回 `OK`；
- 未知意图、缺失/重复/未知参数、枚举越界、数值越界 → `REJECTED` 且不调用网关；
- 网关明确失败 → `FAILED`；网关超时 → `TIMEOUT`，且**只调用一次不重试**；
- 重复请求编号回放缓存且不二次动作；同编号不同意图 → `REJECTED`；
- `status` 只读、离线和无效样本被省略；
- 配置驱动：无配置回退内置；缺失/损坏/schema 非法均回退内置；配置新增意图可直接调用；
  配置删减后未注册意图仍 `REJECTED`；
- `list_intents` 回 `count` 与逗号名单；注册表过大时省略名单且单帧不超上限；
- 超过旧 63 字节上限的合法长帧被接受，超长帧整帧丢弃；
- `SH1` 1–9 全量回归；
- 缺失/过短服务令牌 fail-closed。

运行：

```bash
PYTHONPATH=PC_Test python -m unittest discover -s PC_Test/tests -v
python -m compileall PC_Test/asrpro_bridge.py PC_Test/tests/test_asrpro_bridge.py
```

## 13. 场景规划（已确认方向，待另行实现）

接口已就绪；以下**场景不在本文件实现**，实现时注册为意图处理器：

1. **「我出门了」**：`SH2 <rid> leave_home` → 香橙派查配置地点（默认北京市海淀区）室外
   天气与温度 → 受限模板组句播报 → 可选执行离家动作（关灯/关风扇/关窗/关空调）。
   网络失败仍给基础道别，不阻塞本地动作。
2. **门禁进门欢迎词**：用户经门禁（人脸/RFID/密码）进入，触发**室内人体传感器**后，
   香橙派用 §8 的预留下行帧让 ASRPRO 播放欢迎词。
3. **不实现"车库门"**：本项目没有独立车库门执行器，参考话术仅作示意，不落地。

已确认决策：

- 采用兼容 `SH1` 的 `SH2` 文本协议 + 意图白名单（不允许串口直接指定任意工具）；
- 意图表**启动时从 JSON 配置载入**（可增改、无需改代码），失败回退内置默认；串口侧只读
  发现 `list_intents`，**不可注册意图**；
- 原有"内置大模型 API 语音助手"方案弃用，代码保留、默认不启动；
- 动态播报由 ASRPRO 预录音频组合，暂不引入香橙派自由文本 TTS。
