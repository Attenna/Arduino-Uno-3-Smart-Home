# 系统架构

## 1. 总体边界

整个系统被严格划分为四层，各层职责单一、方向单向：

```text
┌─────────────────────────────────────────┐
│             Home Assistant              │
│                                         │
│ Automation / Scene / Script / State     │
│              业务逻辑                   │
└───────────────────┬─────────────────────┘
                    │
                   MQTT
                    │
┌───────────────────▼─────────────────────┐
│              Orange Pi                  │
│                                         │
│        Serial ↔ MQTT Gateway            │
│              协议转换                   │
└───────────────┬───────────────┬─────────┘
                │               │
              USB             USB
                │               │
        ┌───────▼──────┐ ┌─────▼────────┐
        │   Module A   │ │   Module B   │
        │ Sensor Node  │ │ Output Node  │
        │              │ │              │
        │ 只负责采集   │ │ 只负责执行   │
        └──────────────┘ └──────────────┘
```

## 2. 各层职责

| 层 | 职责 | 禁止做的事 |
|----|------|-----------|
| Module A | 采集传感器数据，向上报告 | 做业务判断（如"温度太高"）、控制执行器 |
| Module B | 接收命令，驱动执行器 | 做业务判断、访问传感器、命令其它驱动 |
| Orange Pi | USB↔MQTT 协议转换 | 做业务决策 |
| Home Assistant | 业务逻辑、联动、场景 | 直接访问硬件 |

## 3. Module A（Sensor Node）

原则：**只负责"观察世界"**。

```text
Sensor
   ↓
SensorManager
   ↓
Protocol (JSON)
   ↓
USB Serial
   ↓
Orange Pi
```

- 每个传感器驱动只做：`begin()` / `read()` / 读取结果。
- 驱动内**禁止**出现 `if (temperature > 30)` 之类的业务判断，**更禁止** `fan.turnOn()`。
- `SensorManager` 负责读取所有传感器、组织数据、交给 `Protocol`，同样不做业务判断。
- 输出为 JSON：周期性状态（`type: data`）+ 事件（`type: event`），**数据与事件不混用**。

## 4. Module B（Output Node）

原则：**只负责"改变世界"**。

```text
USB Serial
   ↓
Protocol (JSON)
   ↓
CommandParser
   ↓
CommandDispatcher
   ↓
Driver
   ↓
Hardware
```

- 驱动只做硬件动作，例如 `fan.setSpeed(180)`、`door.open()`、`light.rgb(255,0,0)`。
- 禁止业务命令，如 `ALARM:SMOKE`、`door.openAndWelcome()`。
- `CommandDispatcher` 负责把 `{cmd, action, value}` 路由到对应驱动，仅此而已。
- 驱动之间**禁止**互相调用（如 `Door -> OLED`、`Light -> Buzzer`）。

## 5. 数据流只能向前

```text
Module A: Sensor → Manager → Protocol → Serial
Module B: Serial → Protocol → Parser → Dispatcher → Driver → Hardware
```

**不要反过来。** Module B 不访问 Module A；驱动不反向依赖上层（`Fan.cpp` 不得 `#include "CommandDispatcher.h"`）。

## 6. 依赖方向

```text
Module A:  main → SensorManager → Sensor Drivers → Arduino Hardware
Module B:  main → Protocol → Parser/Dispatcher → Drivers → Arduino Hardware
```

下层绝对不能反向依赖上层。
