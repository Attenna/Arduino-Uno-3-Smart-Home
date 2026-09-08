# Module A — 传感器板 部署与二次开发指南

> 面向：在 **Linux 主机（PC 或 Orange Pi）** 上编译烧录 Module A 固件、安装接线、调试、扩展新传感器。
> 基础信息（用途/引脚/协议）见 [README.md](README.md) 与 [docs/serial-protocol.md](../docs/serial-protocol.md)。

**功能一句话**：Module A 是一块 Arduino Uno + 10 类传感器，只采集、上报（`data` 周期 + `event` 事件），不做业务判断。

---

## 1. Linux 部署（编译与烧录）

### 1.1 安装 PlatformIO CLI（推荐）

```bash
# 安装（任选其一）
pip3 install platformio                # 需要 pip3
# 或独立安装
curl -fsSL https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py -o get-platformio.py
python3 get-platformio.py

# 加入 PATH（追加到 ~/.bashrc）
echo 'export PATH=$PATH:$HOME/.platformio/penv/bin' >> ~/.bashrc
source ~/.bashrc

# 验证
pio --version
```

### 1.2 串口权限（Linux 关键步骤）

普通用户默认无权访问 `/dev/ttyUSB*`，否则烧录会报 `Permission denied`：

```bash
# 把当前用户加入 dialout 组（需要重新登录生效）
sudo usermod -a -G dialout $USER

# 或写 udev 规则（临时）：
sudo chmod 666 /dev/ttyUSB0
```

> 拔插 Arduino 后设备名通常是 `/dev/ttyUSB0`（CH340/CH341 驱动）。若用板载 USB（ATmega16U2）则是 `/dev/ttyACM0`。

### 1.3 编译与烧录

```bash
cd module-a-sensor

# 编译（自动拉取 lib_deps 声明的库）
pio run

# 烧录到 Arduino（默认用自动检测的串口，也可 --upload-port 指定）
pio run -t upload --upload-port /dev/ttyUSB0

# 打开串口监视器（实时查看传感器 JSON）
pio device monitor --port /dev/ttyUSB0 --baud 115200
```

### 1.4 验证部署成功

烧录后串口应立即输出一行就绪 JSON：

```json
{"module":"sensor","type":"ready","board":"MODULE_A","role":"SENSOR_NODE","version":"V2.0"}
```

随后每 2 秒输出一条 `{"type":"data","data":{...}}` 周期数据。在监视器手动输入 `REPORT` 可立即触发一次上报。

---

## 2. 设备安装与接线

### 2.1 供电要求

- **Arduino Uno 供电**：USB 5V 即可（传感器耗电小）；若用外接电源需 7~12V DC 接 Vin。
- **模块供电**：所有传感器模块用 Uno 的 **5V/GND**（RC522 RFID 除外，见下）。各模块 VCC 接 5V、GND 接 GND、信号接对应引脚。

### 2.2 接线总表（引脚以 `src/Config.h` 为准）

| 传感器 | 信号接 Uno | 供电 | 备注 |
|--------|-----------|------|------|
| DHT11 温湿度 | D7 | 5V/GND | 数据脚需接 5k~10k 上拉（模块一般已带） |
| HC-SR04 超声波 | Trig=A0, Echo=A1 | 5V/GND | Echo 输出 5V 可直连；距离长线建议分压 |
| TTP223 触摸 | D6 | 3.3~5V/GND | 高电平=按下 |
| 光敏模块 | A5（模拟） | 5V/GND | 输出随光照变化 |
| MQ-2 烟雾 | 数字=D5, 模拟=A3 | 5V/GND | 需预热；灵敏度调板上电位器 |
| 雨滴模块 | A2（模拟） | 5V/GND | 板上比较器阈值电位器可调 |
| 红外接收 VS1838B | D3 | 5V/GND | 信号脚接 D3，勿接反（面朝接收面） |
| RC522 RFID | RST=D9, SS=D10, MOSI=D11, MISO=D12, SCK=D13 | **3.3V**/GND | RFID 必须 3.3V！5V 会烧毁 |
| PIR 人体红外 | D8 | 5V/GND | SR602/HC-SR501；板上可调灵敏度与延时 |
| 土壤湿度 YL-69/FC-28 | 数字=D4, 模拟=A4 | 5V/GND | 模拟值越高越干（视模块） |

> ⚠️ **RC522 只能接 3.3V**，绝不能接 5V。
> ⚠️ 所有模块 GND 与 Uno 共地（必须）。

### 2.3 烧录前检查清单

1. 板型选 **Arduino Uno**；
2. 串口选对（Windows 为 COMx，Linux 为 /dev/ttyUSB*）；
3. 传感器逐个核对信号脚与 Config.h 一致；
4. DHT11 初次读数需间隔 >2s（固件已内置 2100ms 间隔）。

---

## 3. 调试方法

### 3.1 串口监视器看数据

```bash
# PlatformIO
pio device monitor --port /dev/ttyUSB0 --baud 115200

# 或 minicom
sudo minicom -D /dev/ttyUSB0 -b 115200

# 或直接用 Python 读（临时验证）
python3 -c "import serial,time; s=serial.Serial('/dev/ttyUSB0',115200); [print(s.readline().decode().strip()) for _ in range(5)]"
```

正常应周期性看到 `data` JSON、事件触发时看到 `event` JSON。

### 3.2 下行命令（调试辅助）

| 命令 | 作用 |
|------|------|
| `REPORT` / `STATUS` | 立即上报一次完整状态 |
| `INTERVAL:5000` | 把上报间隔改为 5000ms（200~60000） |
| `WHO` | 返回设备标识 |

### 3.3 常见问题速查

| 现象 | 排查 |
|------|------|
| 无任何输出 | 波特率/串口选错；USB 线是否为数据线；`Permission denied` → dialout 组 |
| `temperature: null` | DHT11 接线/上拉；需间隔 >2s |
| `distance: null` | 超声波超出量程或 Trig/Echo 接反 |
| RFID 无事件 | 供电须 3.3V；天线对准；卡片是否为 13.56MHz |
| 反复输出 ready（重启） | 供电不足复位 → 换 USB 口或加独立 5V |

---

## 4. 二次开发定义

### 4.1 架构约束（不可违反）

> **A 板不做决定，只报告。** 传感器驱动内**禁止**出现业务判断（如 `if(温度>30) 通知`）。全部联动在 Home Assistant 完成。

### 4.2 新增一个传感器（5 步）

以新增一个「风速传感器」为例：

**① 建类文件**：`src/sensors/AnemometerSensor.h` / `.cpp`

```cpp
// AnemometerSensor.h
#include <Arduino.h>
class AnemometerSensor {
public:
    void begin();
    bool read();                 // 采样一次，返回是否成功
    float speed() const;         // getter：风速
private:
    float _speed;
};
```

**② 实现硬件读写**（参照 `src/sensors/` 下其它驱动风格，引脚从 Config.h 取）：

```cpp
// AnemometerSensor.cpp
#include "AnemometerSensor.h"
#include "../Config.h"
void AnemometerSensor::begin() { pinMode(ANEMO_PIN, INPUT); }
bool AnemometerSensor::read() { _speed = analogRead(ANEMO_PIN) / 1023.0 * 30.0; return true; }
float AnemometerSensor::speed() const { return _speed; }
```

**③ 加引脚宏**：`src/Config.h` 增加 `#define ANEMO_PIN A6`（集中配置，勿硬编码）。

**④ 注册进管理器**：`src/core/SensorManager.h` 加成员 `AnemometerSensor _anemo;`；`SensorManager.cpp` 的 `begin()` 调用 `_anemo.begin()`、`readAll()` 调用 `_anemo.read()`，并加 getter `float windSpeed() const`。

**⑤ 写入上报**：`src/Protocol.cpp` 的 `sendReport()` 里拼进 JSON `"wind": xxx`。

> 若新增的是**事件型**（刷卡/触摸边沿）：在 `SensorManager.h` 的 `EventType` 枚举加新类型，在 `pollEvent()` 里做边沿/防抖后投递 `Event`，`Protocol.cpp` 的 `sendEvent()` 里对应输出字段。

### 4.3 修改上报间隔 / 波特率

- 周期默认 2000ms：`Config.h` 的 `REPORT_INTERVAL_MS`；运行时也可用下行 `INTERVAL:<ms>` 改。
- 波特率：`Config.h` 的 `SERIAL_BAUD`（改后需同步改所有对端）。

### 4.4 相关文档

- 开发规范（命名/依赖方向/文件规范）：[docs/development-guide.md](../docs/development-guide.md)
- 串口协议（上下行格式/事件字段）：[docs/serial-protocol.md](../docs/serial-protocol.md)
- 事件/上报实际 JSON 样本：[README.md](README.md)
