# 串口 JSON 协议

所有串口通信均为**行分隔的 JSON**（每行一个 JSON 对象），波特率 `115200`，行结束符 `\n`（兼容 `\r\n`）。

- Module A / Module B 都通过 USB 串口连接上位机（Orange Pi 或 PC）。
- 两块板之间**不直接通信**，全部经上位机（网关 + Home Assistant，或 MCP server）中转。

> **当前固件版本**
>
> | 板 | 固件版本 | 说明 |
> |----|---------|------|
> | Module A | `V2.1` | 移除超声波 / 土壤湿度，新增矩阵键盘 |
> | Module B | `V2.6` | 移除 TM1637 数码管；红外支持 NEC + 美的空调长码；风扇引脚每 loop 自愈；响应回显请求 `id` |
>
> 下文中，被裁剪的字段/命令均以 **「（已裁剪）」** 标注。

---

## 1. Module A（Sensor Node）→ 上行

### 1.1 就绪

上电时发送一次（**含 `role` 字段**）：

```json
{"module":"sensor","type":"ready","board":"MODULE_A","role":"SENSOR_NODE","version":"V2.1"}
```

### 1.2 周期状态上报（默认每 2s）

`V2.1` 默认裁剪配置下的实际上报（**不含** `distance` / `soil_*` 字段）：

```json
{
  "module": "sensor",
  "type": "data",
  "timestamp": 123456,
  "data": {
    "temperature": 26.4,
    "humidity": 61.0,
    "light": 423,
    "smoke": false,
    "rain": false,
    "touch": false,
    "motion": false
  }
}
```

字段说明：

| 字段 | 类型 | 状态 | 说明 |
|------|------|------|------|
| `timestamp` | number | 必有 | 上电运行毫秒数（无 RTC，非 wall-clock） |
| `temperature` | number/null | 必有 | 摄氏度，读取失败为 `null` |
| `humidity` | number/null | 必有 | 百分比，读取失败为 `null` |
| `light` | number | 必有 | 光敏模拟量 0~1023 |
| `smoke` | boolean | 必有 | 烟雾报警（MQ-2 数字输出） |
| `rain` | boolean | 必有 | 是否检测到雨 |
| `touch` | boolean | 必有 | 是否触摸按下 |
| `motion` | boolean | 必有（`ENABLE_PIR=1`） | PIR 是否检测到人体运动 |
| `distance` | number/null | **已裁剪**（`ENABLE_ULTRASONIC=0`） | 超声波距离(cm)，超范围/无回波为 `null` |
| `soil_moisture` | number | **已裁剪**（`ENABLE_SOIL=0`） | 土壤湿度模拟量 0~1023（越高越干） |
| `soil_dry` | boolean | **已裁剪**（`ENABLE_SOIL=0`） | 土壤是否干燥（数字输出） |

> 字段按编译期裁剪开关条件输出。消费端应容忍字段缺省，而不是假定其存在。
> 裁剪开关定义在 [module-a-sensor/src/Config.h](../module-a-sensor/src/Config.h)。

### 1.3 事件推送（即时，边沿触发）

事件与周期数据分离。示例：

```json
{"module":"sensor","type":"event","event":"rfid","uid":"AA 53 0C 07"}
{"module":"sensor","type":"event","event":"touch","state":true}
{"module":"sensor","type":"event","event":"smoke","state":true}
{"module":"sensor","type":"event","event":"rain","state":true}
{"module":"sensor","type":"event","event":"motion","state":true}
{"module":"sensor","type":"event","event":"keypad","key":"1"}
{"module":"sensor","type":"event","event":"ir","protocol":2,"address":0,"command":10}
```

| `event` 值 | 附加字段 | 状态 | 说明 |
|-----------|---------|------|------|
| `rfid` | `uid` | 保留 | 刷卡 UID（十六进制，字节以空格分隔） |
| `touch` | `state` | 保留 | `true`=按下，`false`=松开 |
| `smoke` | `state` | 保留 | `true`=报警，`false`=解除 |
| `rain` | `state` | 保留 | `true`=有雨，`false`=雨停 |
| `motion` | `state` | 保留 | `true`=检测到运动，`false`=无人 |
| `keypad` | `key` | **V2.1 新增** | 矩阵键盘按键字符（当前硬件为 1×1，仅 `"1"`） |
| `ir` | `protocol`/`address`/`command` | 保留 | 红外遥控解码结果 |
| `soil` | `state` | **已裁剪** | `true`=干燥，`false`=湿润 |

### 1.4 响应（对下行的回复）

```json
{"module":"sensor","type":"response","result":"ok","interval":5000}
{"module":"sensor","type":"who","board":"MODULE_A","role":"SENSOR_NODE","version":"V2.1"}
```

---

## 2. Module A ← 下行（可选，纯文本控制命令）

Module A 原则上"只报告"，下行仅支持少量**无业务含义**的控制命令（不改变其"不做决定"的定位）：

| 命令 | 作用 |
|------|------|
| `REPORT` 或 `STATUS` | 立即上报一次完整状态 |
| `INTERVAL:<毫秒>` | 设置周期上报间隔（200~60000ms） |
| `WHO` | 返回设备标识 |

> 命令不区分大小写。开门密码（如 `1111`）的业务校验在香橙派 MCP 侧完成，不在固件内。

---

## 3. Module B（Output Node）← 下行（JSON 命令）

命令格式统一为 `{cmd, action, ...}`：

```json
{"cmd":"fan","action":"set_speed","value":180}
```

**可选字段 `id`**（V2.6 起）：客户端可携带任意整数 `id`，固件会在对应的 `response`
里原样回显。服务端据此把响应归属到具体命令，**迟到/串味的响应 id 对不上就能直接丢弃**，
不会被误当成本次命令的结果。不带 `id` 时行为与旧版完全一致（响应不含 `id` 字段）。

```json
{"cmd":"fan","action":"set_speed","value":180,"id":7}
→ {"module":"output","type":"response","result":"ok","cmd":"fan","action":"set_speed","id":7}
```

> `system/status` 回的是 `state` 帧（不带 `id`），`system/who` 回 `ready` 帧。

### 3.1 命令一览

| `cmd` | `action` | 附加字段 | 状态 | 说明 |
|-------|----------|---------|------|------|
| `door` | `open` / `close` | - | 保留 | 门舵机 90° / 0° |
| `window` | `open` / `close` / `normal` | - | 保留 | 窗舵机 120° / 0° / 45° |
| `fan` | `set_speed` | `value` 0~255 | 保留 | PWM 调速；D8 非 PWM，退化为开关（0=停，>0=全速） |
| `fan` | `on` / `full` | - | 保留 | 全速 |
| `fan` | `off` / `stop` | - | 保留 | 停止 |
| `light` | `white` | `value` 0~255 | 保留 | 白光亮度 |
| `light` | `red` / `green` / `blue` / `yellow` / `purple` / `cyan` | - | 保留 | 预设颜色 |
| `light` | `rgb` | `r`,`g`,`b` | 保留 | 自定义颜色 |
| `light` | `off` | - | 保留 | 关灯 |
| `buzzer` | `on` / `off` | - | 保留 | 持续响 / 停止 |
| `buzzer` | `beep` | `count`,`on_ms`,`off_ms` | 保留 | 间歇蜂鸣 |
| `oled` | `show_text` | `line`(0~7), `text` | 保留 | OLED 指定行显示（文本最多 16 字符） |
| `oled` | `clear` | - | 保留 | OLED 清屏 |
| `ir` | `send_nec` | `code`(32 位十进制) | 保留（`ENABLE_IR_TX=1`） | V1221 发射 NEC 码（38kHz） |
| `ir` | `repeat` | - | 保留 | 发送 NEC 重复帧（长按） |
| `ir` | `send_midea` | `hex`(6 个十六进制字符) | 保留 | 发射美的 RN02G(X) 空调状态帧：`hex` 是 3 字节 A,B,C（如 `B2BF00`），固件补出 `[A,~A,B,~B,C,~C]` 全 MSB-first 并整帧重复 2 遍。帧内容由 Linux 侧 [PC_Test/midea_ac.py](../PC_Test/midea_ac.py) 生成 |
| `display` | `show_time` | `hour`,`minute` | **已裁剪**（`ENABLE_TM1637=0`） | 数码管显示时钟（命令将返回 error） |
| `display` | `show_number` | `value` | **已裁剪** | 数码管显示数字 |
| `display` | `clear` | - | **已裁剪** | 数码管清屏 |
| `system` | `status` | - | 保留 | 查询执行器状态 |
| `system` | `who` | - | 保留 | 返回设备标识 |

### 3.2 命令示例

```json
{"cmd":"door","action":"open"}
{"cmd":"window","action":"close"}
{"cmd":"fan","action":"set_speed","value":180}
{"cmd":"light","action":"rgb","r":255,"g":0,"b":0}
{"cmd":"buzzer","action":"beep","count":3,"on_ms":200,"off_ms":200}
{"cmd":"oled","action":"show_text","line":2,"text":"T: 25.3 C"}
{"cmd":"ir","action":"send_nec","code":16712445}
{"cmd":"ir","action":"send_midea","hex":"B2BF00"}
{"cmd":"system","action":"status"}
```

### 3.3 OLED 冒号命令（兼容格式）

不区分大小写，与 JSON 命令等效（响应格式相同）：

| 命令 | 作用 |
|------|------|
| `B:OLED:CLEAR` | OLED 清屏 |
| `B:OLED:SHOW:0:HELLO` | OLED 第 0 行显示文本（`line` 0~7，文本保留大小写） |

> OLED 冒号命令文本里的冒号只保留第一个 `:` 作为行号分隔，之后内容（含冒号）都视为文本，
> 例如 `B:OLED:SHOW:1:T:25.3C` 会在第 1 行显示 `T:25.3C`。

### 3.4 编码兼容

固件收到命令时会自动把全角 `“”` / `：` / `，` 转成半角 `"` / `:` / `,`，
因此从聊天软件、中文输入法复制的命令也能正常解析，不会报 `parse_error`。

---

## 4. Module B → 上行

### 4.1 就绪

```json
{"module":"output","type":"ready","board":"MODULE_B","role":"OUTPUT_NODE","version":"V2.6"}
```

### 4.2 命令响应

```json
{"module":"output","type":"response","result":"ok","cmd":"fan","action":"set_speed"}
{"module":"output","type":"response","result":"error","error":"parse_error"}
```

> 下行带了 `id` 时，响应末尾会多一个 `,"id":<值>`（V2.6 起）。

### 4.3 状态查询结果

```json
{"module":"output","type":"state","door":"closed","window":"normal","fan":0,"light":0,"buzzer":"off"}
```

> 由于风扇引脚为非 PWM，`fan` 实际只会是 `0`（停）或 `255`（全速）。

---

## 5. MQTT 主题（Orange Pi 网关）

| 主题 | 方向 | 内容 |
|------|------|------|
| `smarthome/sensor/data` | A → HA | Module A 周期数据 JSON |
| `smarthome/sensor/event` | A → HA | Module A 事件 JSON |
| `smarthome/output/command` | HA → B | Module B 命令 JSON |
| `smarthome/output/response` | B → HA | Module B 响应 JSON |
| `smarthome/output/state` | B → HA | Module B 状态 JSON |
