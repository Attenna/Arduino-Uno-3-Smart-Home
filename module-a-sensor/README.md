# Module A — Sensor Node（传感器节点）

> **职责：采集传感器数据并上报；另负责灯带（A0）与风扇（A1）两个低风险输出。业务判断仍全部在香橙派。**
>
> 🚀 部署/接线/调试/二次开发完整指南见 **[DEPLOYMENT.md](DEPLOYMENT.md)**。

---

## 1. 模块用途

Module A 是一块 Arduino Uno，负责环境感知、用户交互检测，以及灯带/风扇输出。**固件版本 `V2.5-UNIFIED`**（2026-11 风扇从 B 板迁到 A1），经 2026-09 正式版硬件裁剪：

**现役传感器（9 类）与输出**

| # | 传感器 | 类型 | 说明 |
|---|--------|------|------|
| 1 | DHT11 温湿度 | 数字 | 温度 + 湿度 |
| 2 | TTP223 触摸 | 数字 | 按下/松开 |
| 3 | 光敏传感器 | 模拟 | 光照原始值 0~1023 |
| 4 | MQ-2 烟雾 | 数字+模拟 | 报警（数字）+ 浓度（模拟） |
| 5 | 雨滴传感器 | 模拟 | 有雨/无雨 |
| 6 | 红外遥控接收 | 数字 | 红外码解码 |
| 7 | RC522 RFID | SPI | 刷卡 UID |
| 8 | PIR 人体红外 | 数字 | 运动检测（SR602/HC-SR501） |
| 9 | 矩阵键盘 | 数字 | 当前硬件 1×1，仅按键 `"1"` |
| — | NeoPixel 灯带 | 数字输出 | A0，8 颗 |
| — | 直流风扇（单线开关） | 数字输出 | A1 → 驱动板 INA；INB 接 GND；电机独立 5V |

**已裁剪（驱动文件保留，编译期开关关闭）**

| 传感器 | 原引脚 | 裁剪开关 |
|--------|--------|---------|
| HC-SR04 超声波 | A0/A1 | `ENABLE_ULTRASONIC=0`（A0 改接灯带，A1 改接风扇） |
| 土壤湿度 YL-69/FC-28 | D4/A4 | `ENABLE_SOIL=0`（引脚改接矩阵键盘） |

数据通过 USB 串口以 JSON 形式上报，分两种：
- **周期状态**（`type: data`，默认 1s 一次）
- **事件**（`type: event`，边沿触发即时推送）

> 传感器驱动遵循统一的 `begin()` / `read()` / getter 接口，新增传感器只需按同样模式新增一个类，并在 `SensorManager` 中登记即可。

---

## 2. 硬件清单

| 硬件 | 数量 |
|------|------|
| Arduino Uno | 1 |
| DHT11 温湿度模块 | 1 |
| TTP223 触摸模块 | 1 |
| 光敏传感器模块 | 1 |
| MQ-2 烟雾模块 | 1 |
| 雨滴传感器模块 | 1 |
| 红外接收头（VS1838B） | 1 |
| RC522 RFID 模块 | 1 |
| PIR 人体红外模块（SR602/HC-SR501） | 1 |
| 矩阵键盘（当前 1×1） | 1 |
| NeoPixel 灯带（8 颗，接 A0） | 1 |
| 直流风扇 + 驱动（L298N/TB6612） | 1（INA 接 A1，INB 接 GND，电机独立 5V） |

---

## 3. 引脚定义

| 引脚 | 设备 |
|------|------|
| D3 | 红外遥控接收（IRremote，Timer1） |
| D4 | 矩阵键盘行驱动（KEYPAD_ROW_PIN，持续输出 LOW） |
| D5 | 烟雾数字输出 |
| D6 | 触摸传感器 |
| D7 | DHT11 温湿度 |
| D8 | PIR 人体红外 |
| D9 | RFID RST |
| D10 | RFID SS |
| D11/D12/D13 | SPI（MOSI/MISO/SCK，RFID） |
| A0 | NeoPixel 灯带数据线（数字 D14，8 颗） |
| A1 | 风扇 INA（数字 D15；INB 接 GND，电机独立 5V） |
| A2 | 雨滴（模拟） |
| A3 | 烟雾（模拟） |
| A4 | 矩阵键盘列读取（KEYPAD_COL_PIN，INPUT_PULLUP） |
| A5 | 光敏（模拟） |

> 所有引脚集中在 [src/Config.h](src/Config.h) 管理，并可通过裁剪开关调整。

> D0/D1 保留给 USB 串口，禁止接灯带。灯带使用独立稳压 5V 电源并与 A 板共地；
> 数据线建议串联 330–470Ω 电阻。
>
> 风扇 2026-11 从 B 板迁到 A1：`A1 → 驱动板 INA`，`INB → GND`，驱动板 GND 与 A 板共地；
> 电机电源用独立 5V（不要接 A 板 5V）。建议在驱动板 INA 对 GND 加 10k（或 4.7k）下拉，
> 避免 A 板复位/高阻时风扇误导通。

---

## 4. Arduino 库依赖

| 库 | 用途 |
|----|------|
| DHT sensor library (Adafruit) | DHT11 |
| MFRC522 | RC522 RFID |
| IRremote | 红外解码 |
| Adafruit NeoPixel | A0 的 8 颗灯带 |

PlatformIO 已在 [platformio.ini](platformio.ini) 中声明，无需手动安装。

---

## 5. 串口协议

- 波特率：**115200**，每行一个 JSON，行结束符 `\n`。
- 完整协议见 [../docs/serial-protocol.md](../docs/serial-protocol.md)。

### 上行示例

周期状态（`V2.5-UNIFIED`，无 distance/soil 字段；`fan` 为 1=转 / 0=停）：
```json
{"module":"sensor","type":"data","timestamp":123456,"data":{"temperature":26.4,"humidity":61.0,"light":423,"smoke":false,"rain":false,"touch":false,"motion":false,"fan":0}}
```

事件：
```json
{"module":"sensor","type":"event","event":"rfid","uid":"AA 53 0C 07"}
{"module":"sensor","type":"event","event":"keypad","key":"1"}
```

### 下行命令

**控制命令（灯光，A0 8 颗 NeoPixel）**：网关下发的 `light` 恒路由到 A 板，固件接受两种等价格式：

```json
{"cmd":"light","action":"white","value":200,"id":7}
{"cmd":"light","action":"rgb","r":255,"g":80,"b":10,"value":128,"count":4}
```

以及等价的紧凑文本帧（避开 Uno 64 字节串口接收缓冲）：
```text
L,<code>,<value>,<r>,<g>,<b>,<count>,<id>
```
`<code>`：`O`=关灯、`W`=白光、`P`=指定 RGB。支持的 `action`：`off` / `white` / `night` /
`red` / `green` / `blue` / `yellow` / `purple` / `cyan` / `rgb` / `pixels`（无 `temp`）。
响应回 `{"module":"sensor","type":"response","result":"ok","cmd":"light",...,"state":{"light":..,"lit":..}}`。

**控制命令（风扇，A1 单线开关）**：`fan` 命令已从 B 板改路由到 A 板。固件接受：

```json
{"cmd":"fan","action":"on","id":8}
{"cmd":"fan","action":"off","id":9}
{"cmd":"fan","action":"set_speed","value":180,"id":10}
```

以及紧凑帧（MCP 实际使用）：
```text
F,<0|1>,<id>
```
`set_speed` 的 `value>0` 映射为开、`0` 为关（A1 非 PWM，只做开关）。响应回
`{"module":"sensor","type":"response","result":"ok","cmd":"fan","action":"on","id":8,"state":{"fan":1}}`。

**调试命令（纯文本）**：

| 命令 | 作用 |
|------|------|
| `REPORT` / `STATUS` | 立即上报一次 |
| `INTERVAL:<ms>` | 设置上报间隔（200~60000，默认 1000） |
| `WHO` | 返回设备标识 |

> 命令不区分大小写。开门密码（如 `1111`）的业务校验在香橙派 MCP 侧完成，不在固件内。

---

## 6. 输入/输出示例

**输出（上电）：**
```
{"module":"sensor","type":"ready","board":"MODULE_A","role":"SENSOR_NODE","version":"V2.5-UNIFIED"}
```

**输入 `REPORT`，输出：**
```json
{"module":"sensor","type":"data","timestamp":5012,"data":{"temperature":26.4,"humidity":61.0,"light":423,"smoke":false,"rain":false,"touch":false,"motion":false,"fan":0}}
```

---

## 7. 编译与烧录

### 方式一：Arduino IDE（推荐）

1. 用 Arduino IDE 打开 [module-a-sensor.ino](module-a-sensor.ino)（或本文件夹）。
2. 工具 → 开发板 → **Arduino Uno**；选择正确端口。
3. 库管理器安装依赖：**DHT sensor library**、**MFRC522**、**IRremote**。
4. 点击「上传」，即可自动编译并烧录。

### 方式二：PlatformIO

```bash
cd module-a-sensor
pio run -t upload
# 指定串口：
pio run -t upload --upload-port COM3
```

---

## 8. 故障排查

| 现象 | 原因 | 处理 |
|------|------|------|
| `temperature` 为 `null` | DHT11 读数失败 | 检查 D7 接线与 5V/GND，DHT11 需间隔 ≥2s |
| 找不到 `distance` / `soil_*` 字段 | `V2.2` 已裁剪 | 属预期；如需恢复请在 [src/Config.h](src/Config.h) 打开对应开关 |
| 键盘无事件 | 接线/防抖问题 | 确认 D4 行驱动、A4 列读取；一次按压只发一次（含松开保持 120ms） |
| RFID 无刷卡事件 | 供电或接线问题 | RC522 需 3.3V，检查 SPI 与 RST/SS |
| 无任何串口输出 | 波特率/串口选择错误 | 确认 115200，检查 USB 线是否为数据线 |
