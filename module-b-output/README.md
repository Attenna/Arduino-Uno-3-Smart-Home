# Module B — Output Node（执行器节点）

> **职责：只负责"改变世界"——接收命令并驱动执行器，不做任何业务判断。**
>
> 🚀 部署/接线/调试/二次开发完整指南见 **[DEPLOYMENT.md](DEPLOYMENT.md)**。

---

## 1. 模块用途

Module B 是一块 Arduino Uno，负责执行硬件动作并驱动显示设备：

| # | 执行器 | 类型 | 说明 |
|---|--------|------|------|
| 1 | 门舵机（SG90） | PWM | 开门 90° / 关门 0° |
| 2 | 窗舵机（SG90） | PWM | 开 120° / 关 0° / 正常 45° |
| 3 | 直流风扇 | 开关 | 开关控制（D8 非 PWM） |
| 4 | NeoPixel RGB 灯带 | 数字 | 8 颗，颜色/亮度 |
| 5 | 蜂鸣器 | 数字 | 持续 / 间歇蜂鸣 |
| 6 | TM1637 数码管 | 数字 | 显示时钟 / 数字 |
| 7 | SH1106 OLED | SPI | 8 行 × 16 列文本 |
| 8 | V1221 红外发射管 | 数字 | NEC 协议 38kHz，遥控家电 |

所有命令由 Home Assistant 经 Orange Pi 网关下发，Module B 只执行、不做决定。

> 注意：旧版的门"10 秒自动关门"、`ALARM:SMOKE`、`HOUSE:EMPTY` 等**业务逻辑已全部移除**，
> 改由 Home Assistant 的 Automation 实现（例如 HA 定时发送 `{"cmd":"door","action":"close"}`）。

> 相关文档：
> [../docs/ha-automation-examples.md](../docs/ha-automation-examples.md)（HA 自动化实战）、
> [../docs/hardware-debug-notes.md](../docs/hardware-debug-notes.md)（硬件调试备忘）。

---

## 2. 硬件清单

| 硬件 | 数量 |
|------|------|
| Arduino Uno | 1 |
| SG90 舵机 | 2 |
| 直流风扇 + 驱动（L298N/TB6612） | 1 |
| NeoPixel 灯带（8 颗） | 1 |
| 有源/无源蜂鸣器 | 1 |
| TM1637 四位数码管 | 1 |
| SH1106 OLED 128×64（SPI 4 线） | 1 |
| V1221 红外发射管（TSAL1221，940nm） | 1 |

---

## 3. 引脚定义

| 引脚 | 设备 |
|------|------|
| D2 | 门舵机 |
| D3 | 窗舵机 |
| D4 | NeoPixel RGB 灯带（数据线） |
| D5 | TM1637 CLK |
| D6 | TM1637 DIO |
| D7 | 风扇 INB（方向） |
| D8 | 风扇 INA（开关控制） |
| D9 | 蜂鸣器 |
| D10 | OLED CS |
| D11 | OLED SDA（=SPI MOSI） |
| D12 | V1221 红外发射管（NEC 38kHz） |
| D13 | OLED SCK（=SPI SCK） |
| A0（D14） | OLED DC |
| A1（D15） | OLED RES |

> OLED 为 **SPI 4 线接口**（SCK/SDA/RES/DC/CS 共 5 根），不是 I2C。SCK、SDA 走 Uno 硬件 SPI 固定引脚 D13/D11。
> 所有引脚集中在 [src/Config.h](src/Config.h) 管理。

---

## 4. Arduino 库依赖

| 库 | 用途 |
|----|------|
| Servo | 舵机 |
| Adafruit NeoPixel | RGB 灯带 |
| U8g2 (U8x8) | OLED |
| ArduinoJson | 命令解析 |

PlatformIO 已在 [platformio.ini](platformio.ini) 中声明。

---

## 5. 串口协议

- 波特率：**115200**，每行一个 JSON，行结束符 `\n`（兼容 `\r\n`）。
- 命令格式统一为 `{cmd, action, ...}`。
- **全角自动兼容**：固件收到命令时会自动把全角 `“”`/`：`/`，` 转成半角 `"`/`:`/`,`，因此从聊天软件、中文输入法复制的命令也能正常执行，不会报 `parse_error`。
- 完整协议见 [../docs/serial-protocol.md](../docs/serial-protocol.md)。

### 5.1 JSON 命令一览

| `cmd` | `action` | 附加字段 | 说明 |
|-------|----------|---------|------|
| `door` | `open` / `close` | - | 门舵机 90° / 0° |
| `window` | `open` / `close` / `normal` | - | 窗舵机 120° / 0° / 45° |
| `fan` | `set_speed` | `value` 0~255 | 调速（D8 非 PWM，退化为开关：0=停，>0=全速） |
| `fan` | `on` / `full` | - | 全速 |
| `fan` | `off` / `stop` | - | 停止 |
| `light` | `white` | `value` 0~255 | 白光亮度 |
| `light` | `red` / `green` / `blue` / `yellow` / `purple` / `cyan` | - | 预设颜色 |
| `light` | `rgb` | `r`,`g`,`b` | 自定义颜色 |
| `light` | `off` | - | 关灯 |
| `buzzer` | `on` / `off` | - | 持续响 / 停止 |
| `buzzer` | `beep` | `count`,`on_ms`,`off_ms` | 间歇蜂鸣 |
| `display` | `show_time` | `hour`,`minute` | 数码管显示时钟（自动走秒） |
| `display` | `show_number` | `value` | 数码管显示数字（支持负数） |
| `display` | `clear` | - | 数码管清屏 |
| `oled` | `show_text` | `line`(0~7), `text` | OLED 指定行显示（最多 16 字符） |
| `oled` | `clear` | - | OLED 清屏 |
| `ir` | `send_nec` | `code`(32 位十进制) | V1221 发射 NEC 码（38kHz） |
| `ir` | `repeat` | - | 发送 NEC 重复帧（长按） |
| `system` | `status` | - | 查询执行器状态 |
| `system` | `who` | - | 返回设备标识 |

### 5.2 命令示例

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

### 5.3 OLED 冒号命令（兼容格式）

不区分大小写，与 JSON 命令等效（响应格式相同）：

| 命令 | 作用 |
|------|------|
| `B:OLED:CLEAR` | OLED 清屏 |
| `B:OLED:SHOW:0:HELLO` | OLED 第 0 行显示文本（`line` 0~7，文本保留大小写） |

> 注意：OLED 冒号命令文本里的冒号只保留第一个 `:` 作为行号分隔，之后内容（含冒号）都视为文本，例如 `B:OLED:SHOW:1:T:25.3C` 会在第 1 行显示 `T:25.3C`。

### 响应示例

```json
{"module":"output","type":"response","result":"ok","cmd":"fan","action":"set_speed"}
{"module":"output","type":"state","door":"closed","window":"normal","fan":0,"light":0,"buzzer":"off"}
```

---

## 6. 输入/输出示例

**上电输出：**
```json
{"module":"output","type":"ready","board":"MODULE_B","role":"OUTPUT_NODE","version":"V2.0"}
```

**输入 `{"cmd":"light","action":"red"}`，输出：**
```json
{"module":"output","type":"response","result":"ok","cmd":"light","action":"red"}
```

---

## 7. 编译与烧录

### 方式一：Arduino IDE（推荐）

1. 用 Arduino IDE 打开 [module-b-output.ino](module-b-output.ino)（或本文件夹）。
2. 工具 → 开发板 → **Arduino Uno**；选择正确端口。
3. 库管理器安装依赖：**Adafruit NeoPixel**、**U8g2**、**ArduinoJson**（Servo 为内置）。
4. 点击「上传」，即可自动编译并烧录。

### 方式二：PlatformIO

```bash
cd module-b-output
pio run -t upload
# 指定串口：
pio run -t upload --upload-port COM4
```

---

## 8. 配置项（src/Config.h）

| 配置宏 | 默认值 | 说明 |
|--------|--------|------|
| `SERIAL_BAUD` | `115200` | 串口波特率 |
| `LED_COUNT` | `8` | 灯带颗数 |
| `LIGHT_BRIGHTNESS` | `60` | 灯带整体亮度 0~255 |
| `LIGHT_BOOT_ON` | `0` | `1`=上电默认点亮，`0`=上电熄灭 |
| `LIGHT_BOOT_LEVEL` | `20` | 上电点亮时的亮度（越小越省电） |
| `OLED_IS_SH1106` | `1` | `1`=SH1106，`0`=SSD1306 |
| `BUZZER_ACTIVE_LOW` | `1` | `1`=低电平触发，`0`=高电平触发 |
| `BUZZER_DEFAULT_OFF` | `1` | `1`=上电静音，`0`=上电响 |

> 门/窗舵机角度、风扇引脚、数码管引脚等其余参数也都在此文件集中管理。

---

## 9. 故障排查

| 现象 | 原因 | 处理 |
|------|------|------|
| 板子反复重启（监视器刷多条 `ready`） | **供电不足导致欠压复位** | 舵机/灯带/风扇驱动改用独立 5V 电源供电，GND 与 Uno 共地 |
| 上电灯带打乱 / 复位 | 灯带上电默认点亮拉低 5V | 将 `LIGHT_BOOT_ON` 设为 `0`；确需点亮请先解决独立供电 |
| 舵机不动 | 供电不足 | SG90 需独立 5V 供电，勿仅靠 Uno 5V |
| 风扇无调速 | D8 非 PWM 引脚 | 风扇为开关控制；如需调速请改用 PWM 引脚（3/5/6/9/10/11） |
| OLED 无显示 | 接口类型/型号错误 | 本屏为 **SPI 4 线**（非 I2C），检查接线与 `OLED_IS_SH1106` |
| OLED 白屏/显示错乱 | 型号不匹配 | SH1106 与 SSD1306 互换 `OLED_IS_SH1106`（`1`↔`0`）后重烧 |
| OLED 刷新打乱灯带 | I2C 与 NeoPixel 时序冲突 | 已改为 SPI 驱动解决；确认灯带数据线 D4 与 OLED 线分开走 |
| 命令报 `parse_error` | 全角引号/冒号 | 已内置全角转半角兼容；仍报错则检查 JSON 是否单行、字段是否完整 |
| 数码管乱码 | 时序/接线 | 检查 CLK/DIO 与上拉电阻 |
| 命令无响应 | JSON 格式错误 | 确认单行 JSON，`cmd`/`action` 必填 |
