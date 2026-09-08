# 串口 JSON 协议

所有串口通信均为**行分隔的 JSON**（每行一个 JSON 对象），波特率 `115200`，行结束符 `\n`（兼容 `\r\n`）。

- Module A / Module B 都通过 USB 串口连接 Orange Pi。
- 两块板之间**不直接通信**，全部经 Orange Pi + Home Assistant 中转。

---

## 1. Module A（Sensor Node）→ 上行

### 1.1 就绪

上电时发送一次：

```json
{"module":"sensor","type":"ready","board":"MODULE_A","version":"V2.0"}
```

### 1.2 周期状态上报（默认每 2s）

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
    "distance": 25,
    "touch": false,
    "motion": false,
    "soil_moisture": 680,
    "soil_dry": false
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | number | 上电运行毫秒数（无 RTC，非 wall-clock） |
| `temperature` | number/null | 摄氏度，读取失败为 `null` |
| `humidity` | number/null | 百分比，读取失败为 `null` |
| `light` | number | 光敏模拟量 0~1023 |
| `smoke` | boolean | 烟雾报警（MQ-2 数字输出） |
| `rain` | boolean | 是否检测到雨 |
| `distance` | number/null | 超声波距离(cm)，超范围/无回波为 `null` |
| `touch` | boolean | 是否触摸按下 |
| `motion` | boolean | PIR 是否检测到人体运动 |
| `soil_moisture` | number | 土壤湿度模拟量 0~1023（越高越干） |
| `soil_dry` | boolean | 土壤是否干燥（数字输出） |

### 1.3 事件推送（即时，边沿触发）

事件与周期数据分离。示例：

```json
{"module":"sensor","type":"event","event":"rfid","uid":"AA 53 0C 07"}
{"module":"sensor","type":"event","event":"touch","state":true}
{"module":"sensor","type":"event","event":"smoke","state":true}
{"module":"sensor","type":"event","event":"rain","state":true}
{"module":"sensor","type":"event","event":"motion","state":true}
{"module":"sensor","type":"event","event":"soil","state":true}
{"module":"sensor","type":"event","event":"ir","protocol":2,"address":0,"command":10}
```

| `event` 值 | 附加字段 | 说明 |
|-----------|---------|------|
| `rfid` | `uid` | 刷卡 UID（十六进制，字节以空格分隔） |
| `touch` | `state` | `true`=按下，`false`=松开 |
| `smoke` | `state` | `true`=报警，`false`=解除 |
| `rain` | `state` | `true`=有雨，`false`=雨停 |
| `motion` | `state` | `true`=检测到运动，`false`=无人 |
| `soil` | `state` | `true`=干燥，`false`=湿润 |
| `ir` | `protocol`/`address`/`command` | 红外遥控解码结果 |

### 1.4 响应（对下行的回复）

```json
{"module":"sensor","type":"response","result":"ok","interval":5000}
{"module":"sensor","type":"who","board":"MODULE_A","role":"SENSOR_NODE","version":"V2.0"}
```

---

## 2. Module A ← 下行（可选，纯文本控制命令）

Module A 原则上"只报告"，下行仅支持少量**无业务含义**的控制命令（不改变其"不做决定"的定位）：

| 命令 | 作用 |
|------|------|
| `REPORT` 或 `STATUS` | 立即上报一次完整状态 |
| `INTERVAL:<毫秒>` | 设置周期上报间隔（200~60000ms） |
| `WHO` | 返回设备标识 |

---

## 3. Module B（Output Node）← 下行（JSON 命令）

命令格式统一为 `{cmd, action, ...}`：

```json
{"cmd":"fan","action":"set_speed","value":180}
```

### 3.1 命令一览

| `cmd` | `action` | 附加字段 | 说明 |
|-------|----------|---------|------|
| `door` | `open` / `close` | - | 门舵机 90° / 0° |
| `window` | `open` / `close` / `normal` | - | 窗舵机 120° / 0° / 45° |
| `fan` | `set_speed` | `value` 0~255 | PWM 调速 |
| `fan` | `on` / `full` | - | 全速 |
| `fan` | `off` / `stop` | - | 停止 |
| `light` | `white` | `value` 0~255 | 白光亮度 |
| `light` | `red` / `green` / `blue` / `yellow` / `purple` / `cyan` | - | 预设颜色 |
| `light` | `rgb` | `r`,`g`,`b` | 自定义颜色 |
| `light` | `off` | - | 关灯 |
| `buzzer` | `on` / `off` | - | 持续响 / 停止 |
| `buzzer` | `beep` | `count`,`on_ms`,`off_ms` | 间歇蜂鸣 |
| `display` | `show_time` | `hour`,`minute` | 数码管显示时钟 |
| `display` | `show_number` | `value` | 数码管显示数字 |
| `display` | `clear` | - | 数码管清屏 |
| `oled` | `show_text` | `line`(0~7), `text` | OLED 指定行显示 |
| `oled` | `clear` | - | OLED 清屏 |
| `ir` | `send_nec` | `code`(32 位十进制) | V1221 发射 NEC 码（38kHz） |
| `ir` | `repeat` | - | 发送 NEC 重复帧（长按） |
| `system` | `status` | - | 查询执行器状态 |
| `system` | `who` | - | 返回设备标识 |

### 3.2 命令示例

```json
{"cmd":"door","action":"open"}
{"cmd":"window","action":"close"}
{"cmd":"fan","action":"set_speed","value":180}
{"cmd":"light","action":"rgb","r":255,"g":0,"b":0}
{"cmd":"buzzer","action":"beep","count":3,"on_ms":200,"off_ms":200}
{"cmd":"display","action":"show_time","hour":14,"minute":30}
{"cmd":"oled","action":"show_text","line":2,"text":"T: 25.3 C"}
{"cmd":"ir","action":"send_nec","code":16712445}
{"cmd":"system","action":"status"}
```

### 3.3 OLED 冒号命令（兼容格式）

不区分大小写，与 JSON 命令等效（响应格式相同）：

| 命令 | 作用 |
|------|------|
| `B:OLED:CLEAR` | OLED 清屏 |
| `B:OLED:SHOW:0:HELLO` | OLED 第 0 行显示文本（`line` 0~7，文本保留大小写） |

### 3.4 编码兼容

固件收到命令时会自动把全角 `“”` / `：` / `，` 转成半角 `"` / `:` / `,`，
因此从聊天软件、中文输入法复制的命令也能正常解析，不会报 `parse_error`。

---

## 4. Module B → 上行

### 4.1 就绪

```json
{"module":"output","type":"ready","board":"MODULE_B","version":"V2.0"}
```

### 4.2 命令响应

```json
{"module":"output","type":"response","result":"ok","cmd":"fan","action":"set_speed"}
{"module":"output","type":"response","result":"error","error":"parse_error"}
```

### 4.3 状态查询结果

```json
{"module":"output","type":"state","door":"closed","window":"normal","fan":0,"light":0,"buzzer":"off"}
```

---

## 5. MQTT 主题（Orange Pi 网关）

| 主题 | 方向 | 内容 |
|------|------|------|
| `smarthome/sensor/data` | A → HA | Module A 周期数据 JSON |
| `smarthome/sensor/event` | A → HA | Module A 事件 JSON |
| `smarthome/output/command` | HA → B | Module B 命令 JSON |
| `smarthome/output/response` | B → HA | Module B 响应 JSON |
| `smarthome/output/state` | B → HA | Module B 状态 JSON |
