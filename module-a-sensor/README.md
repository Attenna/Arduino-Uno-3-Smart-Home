# Module A — Sensor Node（传感器节点）

> **职责：只负责"观察世界"——采集传感器数据并上报，不做任何业务判断。**
>
> 🚀 部署/接线/调试/二次开发完整指南见 **[DEPLOYMENT.md](DEPLOYMENT.md)**。

---

## 1. 模块用途

Module A 是一块 Arduino Uno，整合 10 类传感器，负责环境感知与用户交互检测：

| # | 传感器 | 类型 | 说明 |
|---|--------|------|------|
| 1 | DHT11 温湿度 | 数字 | 温度 + 湿度 |
| 2 | HC-SR04 超声波 | 数字 | 测距 2~400cm |
| 3 | TTP223 触摸 | 数字 | 按下/松开 |
| 4 | 光敏传感器 | 模拟 | 光照原始值 0~1023 |
| 5 | MQ-2 烟雾 | 数字+模拟 | 报警（数字）+ 浓度（模拟） |
| 6 | 雨滴传感器 | 模拟 | 有雨/无雨 |
| 7 | 红外遥控接收 | 数字 | 红外码解码 |
| 8 | RC522 RFID | SPI | 刷卡 UID |
| 9 | PIR 人体红外 | 数字 | 运动检测（SR602/HC-SR501） |
| 10 | 土壤湿度 | 数字+模拟 | 干燥（数字）+ 湿度（模拟，YL-69/FC-28） |

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
| HC-SR04 超声波模块 | 1 |
| TTP223 触摸模块 | 1 |
| 光敏传感器模块 | 1 |
| MQ-2 烟雾模块 | 1 |
| 雨滴传感器模块 | 1 |
| 红外接收头（VS1838B） | 1 |
| RC522 RFID 模块 | 1 |
| PIR 人体红外模块（SR602/HC-SR501） | 1 |
| 土壤湿度模块（YL-69/FC-28） | 1 |

---

## 3. 引脚定义

| 引脚 | 设备 |
|------|------|
| D3 | 红外遥控接收（IRremote，Timer1） |
| D4 | 土壤湿度（数字） |
| D5 | 烟雾数字输出 |
| D6 | 触摸传感器 |
| D7 | DHT11 温湿度 |
| D8 | PIR 人体红外 |
| D9 | RFID RST |
| D10 | RFID SS |
| D11/D12/D13 | SPI（MOSI/MISO/SCK，RFID） |
| A0 | 超声波 Trig |
| A1 | 超声波 Echo |
| A2 | 雨滴（模拟） |
| A3 | 烟雾（模拟） |
| A4 | 土壤湿度（模拟） |
| A5 | 光敏（模拟） |

> 所有引脚集中在 [src/Config.h](src/Config.h) 管理。

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

周期状态：
```json
{"module":"sensor","type":"data","timestamp":123456,"data":{"temperature":26.4,"humidity":61.0,"light":423,"smoke":false,"rain":false,"distance":25,"touch":false,"motion":false,"soil_moisture":680,"soil_dry":false}}
```

事件：
```json
{"module":"sensor","type":"event","event":"rfid","uid":"AA 53 0C 07"}
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
{"module":"sensor","type":"ready","board":"MODULE_A","role":"SENSOR_NODE","version":"V2.0"}
```

**输入 `REPORT`，输出：**
```json
{"module":"sensor","type":"data","timestamp":5012,"data":{"temperature":26.4,"humidity":61.0,"light":423,"smoke":false,"rain":false,"distance":25,"touch":false,"motion":false,"soil_moisture":680,"soil_dry":false}}
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
| `distance` 为 `null` | 超声波超时 | 检查 Trig/Echo 接线，A0/A1 需对应 |
| RFID 无刷卡事件 | 供电或接线问题 | RC522 需 3.3V，检查 SPI 与 RST/SS |
| 无任何串口输出 | 波特率/串口选择错误 | 确认 115200，检查 USB 线是否为数据线 |
