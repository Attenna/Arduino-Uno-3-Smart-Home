# 开发规范（Development Guide）

> 本文件是所有开发与 AI 修改代码时必须遵守的约束。**修改任何代码前，先阅读本节。**

## 0. 最高级架构约束

> **A 板不做决定，只报告；B 板不做决定，只执行；Orange Pi 负责协议转换；Home Assistant 负责决定做什么。**

- Module A 采集传感器，**不做任何业务判断**，只上报数据与事件。
- Module B 接收命令，**不做任何业务判断**，只执行硬件动作。
- 所有联动（如"温度>30 开风扇""下雨关窗""烟雾报警"）都在 Home Assistant 的 Automation/Scene/Script 中实现。
- 这条约束**高于一切其它规则**。若某条实现与之冲突，以本约束为准。

## 1. 数据流只能向前

```text
Module A: Sensor → Manager → Protocol → Serial
Module B: Serial → Protocol → Parser → Dispatcher → Driver → Hardware
```

**不要反过来。** 例如 Module B 不应访问 Module A。

## 2. 禁止跨层调用

```text
❌ Light -> Buzzer
❌ Door -> OLED
❌ Fan -> Display
❌ Sensor -> Fan
❌ Fan.cpp #include "CommandDispatcher.h"
```

所有联动由上层（Home Assistant）完成。

## 3. 依赖方向

```text
Module A:  main → SensorManager → Sensor Drivers → Arduino Hardware
Module B:  main → Protocol → Parser/Dispatcher → Drivers → Arduino Hardware
```

下层绝对不能反向依赖上层。

## 4. 命名规范

- **类名**：PascalCase —— `DHTSensor`、`CommandDispatcher`、`OLEDDisplay`
- **函数**：camelCase —— `readTemperature()`、`setBrightness()`、`showNumber()`
- **私有变量**：下划线前缀 —— `_currentSpeed`、`_lastReading`、`_initialized`
- **常量 / 宏**：全大写 —— `SERIAL_BAUD`、`DHT_PIN`、`MAX_BRIGHTNESS`

## 5. 文件规范

- 一个类一个 `.h` + `.cpp`，例如 `Fan.h` / `Fan.cpp`。
- 禁止巨型文件：不要 `all_drivers.cpp`、`everything.cpp`、`utils.cpp`。
- 目录结构：

```text
module-a-sensor/
├── module-a-sensor.ino   # Arduino IDE 入口（识别 Sketch 用）
├── src/
│   ├── main.cpp          # setup()/loop()
│   ├── Config.h
│   ├── Protocol.h / .cpp
│   ├── sensors/          # 每个传感器 .h/.cpp
│   └── core/             # SensorManager.h/.cpp
└── test/

module-b-output/
├── module-b-output.ino   # Arduino IDE 入口（识别 Sketch 用）
├── src/
│   ├── main.cpp          # setup()/loop()
│   ├── Config.h
│   ├── Protocol.h / .cpp
│   ├── drivers/          # 每个执行器 .h/.cpp
│   └── core/             # CommandParser / CommandDispatcher
└── test/
```

> 说明：Arduino IDE 只识别 `.ino` 文件，并自动递归编译 `src/` 下的 `.cpp/.c`、把 `src/` 加入头文件搜索路径；因此所有 `.h`/`.cpp` 放在 `src/` 下，`setup()/loop()` 放在 `src/main.cpp`，`.ino` 仅作为入口。PlatformIO 则直接编译 `src/`。

## 6. 配置全部集中

所有引脚、阈值、时间间隔集中在 `src/Config.h`，**不要**在驱动 `.cpp` 里硬编码引脚。

```cpp
// src/Config.h
#define SERIAL_BAUD 115200
#define FAN_PIN 6
#define DOOR_SERVO_PIN 9
```

## 7. Protocol 单独管理

不要把串口处理塞进 Driver。

```text
❌ Fan.cpp 中直接 Serial.read()
✅ Serial → Protocol → CommandDispatcher → Fan
```

## 8. Driver 只做硬件

```cpp
// ✅ 允许
fan.setSpeed(180); fan.stop(); fan.full();
light.off(); light.white(180); light.red(); light.rgb(255,0,0);
door.open(); door.close();

// ❌ 禁止（业务语义）
door.openAndWelcome();          // "欢迎"是业务
if (temperature > 30) { ... }   // 判断是业务
ALARM:SMOKE                      // 场景命令是业务
```

## 9. PC_Test（Python / Web / 前端）约定

下面每条都是踩过坑之后钉在 `pi-staging/` 回归里的硬约束，改 web 或前端前先照着过一遍。

1. **时间戳统一 UTC naive**。`web/database.py` 写入用 `datetime.now(timezone.utc)` 格式化，串里不带时区标记。所有前端显示必须过 `static/js/lang.js` 的 `serverDate(raw)`（它补上 `Z`），**不要**在页面脚本里直接 `new Date(row.timestamp)` —— 那会把 UTC 当本地时间，整页时间差一个时区。`test_frontend_blocks.py` 扫这条。
2. **新鲜度由后端算**。库里「最新一条」不等于「刚刚发生」。任何「实时判定」面板都要展示这条距今多久（后端给 `age_s`），超过窗口就宁可显示等待状态，也不能把很久以前的记录冒充成当前结果。参考 `GET /api/face/events/latest` 与 `access.js` 的 `FACE_FRESH_WINDOW_S`。
3. **i18n 键必须双语齐全**。模板里的每个 `data-i18n` 与 JS 里的每个 `t('key')` 都要同时存在于 `lang.js` 的 `zh` 和 `en`，带 `{0}` 占位的两边都要带；缺键不会报错，页面直接把键名显示出来。`test_frontend_blocks.py` 抓取全部模板做覆盖校验。
4. **改了 JS / CSS 必须抬缓存版本号**。各模板引用的 `?v=YYYYMMDDx` 要一起抬，且跨模板共享的 `lang.js` 版本号必须处处相等，否则部分页面吃旧缓存、新旧脚本混用。
5. **写库的联调脚本要自己擦干净**。用 curl 伪造识别/通行结果的脚本（如 `pi-staging/pi_face_door_check.sh`）落库后与真实事件完全同形，跑完必须删掉自己插入的行。
6. **浏览器验证只指向临时副本**。`web/config.py` 的 `DB_PATH` / `AUTHORIZED_DIR` 是从 `PC_TEST_DIR` 推出的常量，不认环境变量，直接 `run_web.py` 操作的就是真库和真人脸照片。做页面级验证要把 `PC_Test` 拷一份到临时目录再跑。

## 10. Git 开发规范

分支：

```text
main
├── develop
├── feature/module-a
├── feature/module-b
├── feature/gateway
└── feature/homeassistant
```

Commit 信息（Conventional Commits）：

```text
feat: add DHT11 sensor driver
fix: fix ultrasonic timeout
refactor: decouple command dispatcher
docs: update serial protocol
```

禁止：`改了一点`、`最终版`、`真的最终版`、`final_final`。

## 11. README 规范

每个模块必须有 `README.md`，至少包含：

1. 模块用途
2. 硬件清单
3. 引脚定义
4. Arduino 库依赖
5. 串口协议
6. 输入/输出示例
7. 编译方法
8. 烧录方法
9. 故障排查
