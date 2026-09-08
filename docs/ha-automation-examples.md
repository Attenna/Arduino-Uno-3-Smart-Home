# Home Assistant 自动化示例（Module B 联动）

> 业务逻辑全部由 Home Assistant 完成，Module B 只执行命令。
> 本页示例基于仓库内已有的 `homeassistant/` 配置（`scripts.yaml` 已定义可复用脚本）。

## 1. 前置约定

- MQTT Broker：`localhost:1883`（Orange Pi 上的 Mosquitto）
- Module B 命令主题：`smarthome/output/command`
- Module B 状态主题：`smarthome/output/state`
- 响应主题：`smarthome/output/response`
- 传感器主题：`smarthome/sensor/data`（周期）/ `smarthome/sensor/event`（事件）

所有对 Module B 的驱动都通过 `mqtt.publish` 发 JSON 命令，或调用 `scripts.yaml` 里封装的脚本。

---

## 2. 已内置的自动化（automations.yaml）

| 自动化 | 触发条件 | 动作 |
|--------|---------|------|
| 温度过高开风扇 | `sensor.temperature > 30` | `fan.turn_on` + `script.set_fan_speed(100)` |
| 下雨关窗 | `binary_sensor.rain` → `on` | `script.window_close` |
| 烟雾报警 | `binary_sensor.smoke` → `on` | 蜂鸣 `beep` + 红灯 |
| 烟雾解除 | `binary_sensor.smoke` → `off` | 蜂鸣 `off` |
| 刷卡开门 | 收到 `rfid` 事件 | `script.door_open` |

---

## 3. 可复用脚本一览（scripts.yaml）

| 脚本 | 参数 | 作用 |
|------|------|------|
| `script.door_open` / `door_close` | - | 开门 / 关门 |
| `script.window_open` / `close` / `normal` | - | 开窗 / 关窗 / 常态 |
| `script.set_fan_speed` | `speed` 0~255 | 风扇调速 |
| `script.set_light_rgb` | `r`,`g`,`b` | 灯光颜色 |
| `script.display_time` | `hour`,`minute` | 数码管显示时间 |
| `script.oled_show_text` | `line`,`text` | OLED 显示文本 |

---

## 4. 新增示例（可复制到 automations.yaml）

### 4.1 定时关门（防盗）

每天 22:00 自动关门、关窗：

```yaml
- id: "night_lock"
  alias: "夜间自动锁门关窗"
  trigger:
    - platform: time
      at: "22:00:00"
  action:
    - service: script.door_close
    - service: script.window_close
```

### 4.2 OLED 显示室温 + 时间

每 30 秒用 Module A 的温湿度刷新 OLED 第 0 行，第 1 行显示当前时间：

```yaml
- id: "oled_show_temp"
  alias: "OLED 显示室温与时间"
  trigger:
    - platform: time_pattern
      seconds: "/30"
  action:
    - service: script.oled_show_text
      data:
        line: 0
        text: "T:{{ states('sensor.temperature') }}C"
    - service: script.oled_show_text
      data:
        line: 1
        text: "{{ now().strftime('%H:%M') }}"
```

> 注意：`text` 最多 16 字符，超长会被截断。

### 4.3 温度分层联动（风扇）

温度越高风速越大，降到阈值以下自动停：

```yaml
- id: "fan_speed_by_temp"
  alias: "按温度调节风扇"
  trigger:
    - platform: numeric_state
      entity_id: sensor.temperature
      above: 26
  action:
    - choose:
        - conditions:
            - condition: numeric_state
              entity_id: sensor.temperature
              above: 32
          sequence:
            - service: script.set_fan_speed
              data:
                speed: 255
        - conditions:
            - condition: numeric_state
              entity_id: sensor.temperature
              above: 29
          sequence:
            - service: script.set_fan_speed
              data:
                speed: 160
      default:
        - service: script.set_fan_speed
          data:
            speed: 100

- id: "fan_off_when_cool"
  alias: "温度回落关风扇"
  trigger:
    - platform: numeric_state
      entity_id: sensor.temperature
      below: 24
  action:
    - service: mqtt.publish
      data:
        topic: "smarthome/output/command"
        payload: '{"cmd":"fan","action":"off"}'
```

### 4.4 一键离家 / 回家（脚本组合）

把多设备动作封装成脚本，放进 `scripts.yaml`：

```yaml
# 一键离家
leave_home:
  alias: "一键离家"
  sequence:
    - service: script.door_close
    - service: script.window_close
    - service: mqtt.publish
      data:
        topic: "smarthome/output/command"
        payload: '{"cmd":"light","action":"off"}'
    - service: mqtt.publish
      data:
        topic: "smarthome/output/command"
        payload: '{"cmd":"fan","action":"off"}'
    - service: mqtt.publish
      data:
        topic: "smarthome/output/command"
        payload: '{"cmd":"oled","action":"clear"}'

# 一键回家
come_home:
  alias: "一键回家"
  sequence:
    - service: script.window_normal
    - service: mqtt.publish
      data:
        topic: "smarthome/output/command"
        payload: '{"cmd":"light","action":"white","value":255}'
```

### 4.5 红外遥控联动（Module B 发射 NEC 码控制家电）

例如烟雾报警时，用 Module B 的红外发射管给空调发「关机」NEC 码：

```yaml
- id: "smoke_ir_ac_off"
  alias: "烟雾时红外关空调"
  trigger:
    - platform: state
      entity_id: binary_sensor.smoke
      to: "on"
  action:
    - service: mqtt.publish
      data:
        topic: "smarthome/output/command"
        payload: '{"cmd":"ir","action":"send_nec","code":16712445}'
```

> NEC 码需先用 Module A 的红外接收解码（`type:event`，`event:ir` 含 `protocol/address/command`），
> 再用 `address<<16 | (~address&0xFF)<<8 | command<<0 | (~command&0xFF)` 拼成 32 位完整码填入 `code`。

---

## 5. 在 HA 里直接发命令（调试用）

Developer Tools → Services → `mqtt.publish`，或 dashboard 里直接调：

```yaml
service: mqtt.publish
data:
  topic: "smarthome/output/command"
  payload: '{"cmd":"light","action":"blue"}'
```

---

## 6. 常见问题

| 问题 | 原因 | 处理 |
|------|------|------|
| 自动化不触发 | entity_id 未匹配 | 确认 `configuration.yaml` 中 sensor 名称生成的 entity_id（如 `sensor.temperature`） |
| 命令发出但无响应 | 网关未订阅 | 确认 `output_gateway.py` 在运行，串口 `/dev/ttyUSB1` 正确 |
| 状态显示错误 | state 模板 | 核对 `smarthome/output/state` 的字段名（`door`/`window`/`fan`/`light`/`buzzer`） |
| OLED 文本被截断 | 超 16 字符 | `text` 最多 16 字符，`line` 0~7 |
