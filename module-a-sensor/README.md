# Module A — Sensor Node（传感器节点）

> **职责：只负责"观察世界"——采集传感器数据并上报，不做任何业务判断。**
>
> 🚀 部署/接线/调试/二次开发完整指南见 **[DEPLOYMENT.md](DEPLOYMENT.md)**。

---

## 1. 模块用途

Module A 是一块 Arduino Uno，负责环境感知与用户交互检测。**固件版本 `V2.1`**，经 2026-09 正式版硬件裁剪：

**现役传感器（9 类）**

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

**已裁剪（驱动文件保留，编译期开关关闭）**

| 传感器 | 原引脚 | 裁剪开关 |
|--------|--------|---------|
| HC-SR04 超声波 | A0/A1 | `ENABLE_ULTRASONIC=0`（引脚悬空） |
| 土壤湿度 YL-69/FC-28 | D4/A4 | `ENABLE_SOIL=0`（引脚改接矩阵键盘） |

数据通过 USB 串口以 JSON 形式上报，分两种：
- **周期状态**（`type: data`，默认 2s 一次）
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
| A0 | （悬空；原超声波 Trig） |
| A1 | （悬空；原超声波 Echo） |
| A2 | 雨滴（模拟） |
| A3 | 烟雾（模拟） |
| A4 | 矩阵键盘列读取（KEYPAD_COL_PIN，INPUT_PULLUP） |
| A5 | 光敏（模拟） |

> 所有引脚集中在 [src/Config.h](src/Config.h) 管理，并可通过裁剪开关调整。

---

## 4. Arduino 库依赖

| 库 | 用途 |
|----|------|
| DHT sensor library (Adafruit) | DHT11 |
| MFRC522 | RC522 RFID |
| IRremote | 红外解码 |

PlatformIO 已在 [platformio.ini](platformio.ini) 中声明，无需手动安装。

---

## 5. 串口协议

- 波特率：**115200**，每行一个 JSON，行结束符 `\n`。
- 完整协议见 [../docs/serial-protocol.md](../docs/serial-protocol.md)。

### 上行示例

周期状态（`V2.1`，无 distance/soil 字段）：
```json
{"module":"sensor","type":"data","timestamp":123456,"data":{"temperature":26.4,"humidity":61.0,"light":423,"smoke":false,"rain":false,"touch":false,"motion":false}}
```

事件：
```json
{"module":"sensor","type":"event","event":"rfid","uid":"AA 53 0C 07"}
{"module":"sensor","type":"event","event":"keypad","key":"1"}
```

### 下行（可选，纯文本）

| 命令 | 作用 |
|------|------|
| `REPORT` / `STATUS` | 立即上报一次 |
| `INTERVAL:<ms>` | 设置上报间隔（200~60000） |
| `WHO` | 返回设备标识 |

---

## 6. 输入/输出示例

**输出（上电）：**
```
{"module":"sensor","type":"ready","board":"MODULE_A","role":"SENSOR_NODE","version":"V2.1"}
```

**输入 `REPORT`，输出：**
```json
{"module":"sensor","type":"data","timestamp":5012,"data":{"temperature":26.4,"humidity":61.0,"light":423,"smoke":false,"rain":false,"touch":false,"motion":false}}
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
| 找不到 `distance` / `soil_*` 字段 | `V2.1` 已裁剪 | 属预期；如需恢复请在 [src/Config.h](src/Config.h) 打开对应开关 |
| 键盘无事件 | 接线/防抖问题 | 确认 D4 行驱动、A4 列读取；一次按压只发一次（含松开保持 120ms） |
| RFID 无刷卡事件 | 供电或接线问题 | RC522 需 3.3V，检查 SPI 与 RST/SS |
| 无任何串口输出 | 波特率/串口选择错误 | 确认 115200，检查 USB 线是否为数据线 |
