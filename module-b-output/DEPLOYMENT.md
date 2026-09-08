# Module B — 执行器板 部署与二次开发指南

> 面向：在 **Linux 主机** 上编译烧录 Module B 固件、安装接线、调试、扩展新执行器。
> 基础信息（用途/引脚/命令表）见 [README.md](README.md) 与 [docs/serial-protocol.md](../docs/serial-protocol.md)。

**功能一句话**：Module B 是一块 Arduino Uno + 8 类执行器/显示设备，接收命令并执行硬件动作，不做业务判断。

---

## 1. Linux 部署（编译与烧录）

### 1.1 安装 PlatformIO CLI

```bash
pip3 install platformio
# 或独立安装后加入 PATH（追加到 ~/.bashrc）
echo 'export PATH=$PATH:$HOME/.platformio/penv/bin' >> ~/.bashrc && source ~/.bashrc
pio --version
```

### 1.2 串口权限

```bash
sudo usermod -a -G dialout $USER   # 重新登录生效
# 临时：sudo chmod 666 /dev/ttyUSB0
```

### 1.3 编译与烧录

```bash
cd module-b-output

pio run                       # 编译（自动安装 Servo/NeoPixel/U8g2/ArduinoJson）
pio run -t upload --upload-port /dev/ttyUSB0
pio device monitor --port /dev/ttyUSB0 --baud 115200
```

### 1.4 验证部署成功

烧录后串口应立即输出：

```json
{"module":"output","type":"ready","board":"MODULE_B","role":"OUTPUT_NODE","version":"V2.0"}
```

发送命令测试（**推荐先测纯文本命令**，见下节「已知问题」）：

```bash
echo 'B:LIGHT:RED' > /dev/ttyUSB0        # 红灯
echo 'B:DOOR:OPEN' > /dev/ttyUSB0        # 开门
echo 'B:STATUS' > /dev/ttyUSB0           # 查状态
```

若返回 `{"type":"response","result":"ok",...}` 即链路正常。

---

## 2. 设备安装与接线

### 2.1 供电要求（本板最重要的注意事项）

| 负载 | 供电 | 说明 |
|------|------|------|
| Arduino Uno | USB 5V | 仅逻辑供电 |
| **2× SG90 舵机** | **独立 5V 电源** | 舵机峰值电流大，仅靠 Uno 5V 会导致欠压复位 |
| **直流风扇（L298N/TB6612）** | **独立电源**（5~12V） | 驱动器 VCC 单独供，**GND 与 Uno 共地** |
| NeoPixel 灯带（8 颗） | 建议独立 5V | 全亮电流 >400mA，易拉低 5V |
| 蜂鸣器/OLED/TM1637 | Uno 5V | 小电流 |

> ⚠️ 电源共地是硬性要求：所有独立电源的 **GND 必须与 Uno GND 相连**。
> ⚠️ 灯带数据线 D4 与供电地线尽量分开走，避免刷新 OLED 时打乱灯带。

### 2.2 接线总表（引脚以 `src/Config.h` 为准）

| 执行器 | 信号接 Uno | 电源 | 备注 |
|--------|-----------|------|------|
| 门舵机 SG90 | D2 | 独立 5V | 开=90° / 关=0° |
| 窗舵机 SG90 | D3 | 独立 5V | 开=120° / 关=0° / 正常=45° |
| NeoPixel 灯带 | D4 | 5V | 8 颗，需加 300Ω 串联电阻防上电毛刺 |
| TM1637 数码管 | CLK=D5, DIO=D6 | 5V | — |
| 风扇驱动（L298N/TB6612） | INA=D8, INB=D7 | 独立电源 | **D8/D7 非 PWM**，退化为开关（0=停，非 0=全速） |
| 蜂鸣器 | D9 | 5V | `BUZZER_ACTIVE_LOW=1` 时低电平触发（有源蜂鸣器） |
| SH1106 OLED（SPI 4 线） | SCK=D13, MOSI=D11, CS=D10, DC=A0, RES=A1 | 5V/3.3V | **SPI 接口非 I2C** |
| V1221 红外发射管 | D12 | 5V | NEC 38kHz；发射管正负极勿接反（阳极接电阻到 D12） |

> ⚠️ OLED 是 **SPI 4 线**（U8x8 驱动），不是 I2C。接线错误会白屏。
> ⚠️ 风扇调速需要 PWM 引脚（3/5/6/9/10/11），当前 D8/D7 仅支持开关；如需调速需改板/改线。

### 2.3 烧录前检查清单

1. 板型 Arduino Uno、端口正确；
2. 舵机/风扇/灯带确认独立供电且共地；
3. OLED 型号：SH1106 还是 SSD1306 —— 在 `Config.h` 设 `OLED_IS_SH1106`（1/0）；
4. 蜂鸣器类型：有源低电平触发用默认配置；若高电平触发改 `BUZZER_ACTIVE_LOW=0`。

---

## 3. 调试方法

### 3.1 串口监视 / 手动发命令

```bash
# PlatformIO monitor
pio device monitor --port /dev/ttyUSB0 --baud 115200

# 另一个终端手动发文本命令（B 板兼容格式）
echo 'B:LIGHT:RED' > /dev/ttyUSB0
echo 'B:BUZZER:BEEP:3:200:200' > /dev/ttyUSB0
echo 'B:OLED:SHOW:0:HELLO' > /dev/ttyUSB0
echo 'B:STATUS' > /dev/ttyUSB0
```

### 3.2 查询状态

`B:STATUS`（或 JSON `{"cmd":"system","action":"status"}`）会返回全部执行器状态：

```json
{"module":"output","type":"state","door":"closed","window":"normal","fan":0,"light":0,"buzzer":"off"}
```

> ⚠️ 状态 JSON 较长，串口读取时若行被截断，多为对端缓冲太小（见 README 已知问题），用 `cat /dev/ttyUSB0` 流式看可确认完整内容。

### 3.3 已知问题（务必先读）

> **固件当前 JSON 命令解析存在 bug**：`{"cmd":"..."}` 形式命令会返回 `parse_error`，
> 而纯文本命令 `B:XXX` 全部正常。排查时可先用 `B:XXX` 文本命令（功能等价）。
> 涉及 PC 端工具时，DSL 已自动降级为文本命令发送，无需人工干预。
> （该 bug 定位在 `Protocol.cpp` 的 JSON 分支，可对照 `handleLegacy` 文本命令修固件。）

### 3.4 常见问题速查

| 现象 | 排查 |
|------|------|
| 反复重启（刷多条 ready） | 供电不足欠压复位 → 舵机/灯带/风扇独立供电 |
| 舵机不动 | 独立 5V + 共地；SG90 扭矩不足时减负载 |
| 上电灯带打乱/复位 | `LIGHT_BOOT_ON=0`；或独立供电 |
| 风扇无调速 | D8 非 PWM，只能开关 |
| OLED 白屏/错乱 | 接线（SPI 非 I2C）+ `OLED_IS_SH1106` 型号 |
| 命令无响应 | JSON 需单行、`cmd`/`action` 必填 |

---

## 4. 二次开发定义

### 4.1 架构约束（不可违反）

> **B 板不做决定，只执行。** 驱动内**禁止**业务逻辑（如自动关门、ALARM 场景、`if(温度>30)`）。
> 一切联动由 Home Assistant 的自动化/脚本实现。

### 4.2 新增一个执行器（5 步）

以新增「继电器（Relay）」为例：

**① 建驱动类**：`src/drivers/Relay.h` / `.cpp`

```cpp
// Relay.h
#include <Arduino.h>
class Relay {
public:
    void begin();
    void on();
    void off();
    bool isOn() const;
private:
    bool _on;
};
```

**② 实现硬件动作**（引脚从 Config.h 取）：

```cpp
// Relay.cpp
#include "Relay.h"
#include "../Config.h"
void Relay::begin() { pinMode(RELAY_PIN, OUTPUT); off(); }
void Relay::on()  { _on = true;  digitalWrite(RELAY_PIN, HIGH); }
void Relay::off() { _on = false; digitalWrite(RELAY_PIN, LOW);  }
bool Relay::isOn() const { return _on; }
```

**③ 加引脚/配置宏**：`Config.h` 加 `#define RELAY_PIN A2` 等。

**④ 注册进分发器**：
- `core/CommandDispatcher.h` 加成员 `Relay _relay;`；
- `CommandDispatcher.cpp` 的 `begin()` 加 `_relay.begin()`，`dispatch()` 加分支：

```cpp
else if (strcmp(cmd.device, "relay") == 0) {
    if (strcmp(cmd.action, "on") == 0)  { _relay.on();  return true; }
    if (strcmp(cmd.action, "off") == 0) { _relay.off(); return true; }
}
```

- 若需在 `B:STATUS` 里反映：在 `buildStatus()` 里拼 `"relay":"on/off"`。

**⑤ （可选）补文本命令别名**：`Protocol.cpp` 的 `handleLegacy()` 加 `RELAY:ON` / `RELAY:OFF`。

> 若新执行器带 `update()`（如舵机释放、蜂鸣器异步），记得在 `CommandDispatcher::update()` 中调用。

### 4.3 修改行为参数

- 舵机角度：`Config.h` 的 `*_ANGLE` 宏。
- 灯带亮度/上电行为：`LIGHT_BRIGHTNESS`、`LIGHT_BOOT_ON`、`LIGHT_BOOT_LEVEL`。
- 蜂鸣器触发极性：`BUZZER_ACTIVE_LOW`。
- OLED 型号：`OLED_IS_SH1106`。

### 4.4 相关文档

- 开发规范（依赖方向/驱动只做硬件/禁止跨层调用）：[docs/development-guide.md](../docs/development-guide.md)
- 串口命令全表（JSON + 文本兼容格式）：[docs/serial-protocol.md](../docs/serial-protocol.md)
- HA 侧如何调用本板命令做联动：[docs/ha-automation-examples.md](../docs/ha-automation-examples.md)
- 硬件调试备忘：[docs/hardware-debug-notes.md](../docs/hardware-debug-notes.md)
