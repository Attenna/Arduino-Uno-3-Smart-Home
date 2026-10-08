# 变更记录（CHANGELOG）

记录对系统行为 / 接口有影响的变更。新条目置于顶部。

## 未发布 · 积木自动化风险修复（R1–R10）

分支：`fix/automation-risks`。规格：`.trae/documents/issue-blocks-automation-risks.md`（高/中危条目）。

### 变更
- **R1 空调风速枚举统一**：规则保存期接入执行层真源 `midea_ac.FAN_LEVELS`（`auto/low/mid/high`），旧 6 档数值（20/40/60/80/100）由 `ac_state.normalize_fan_level` 折算；`turbo` 之类非法值直接报错，不再出现「选低/中/高保存失败」。
- **R7 条件/触发按数据源类型校验**：数值源只接受真数字并按量程校验（温度 -40~125、湿度 0~100、光照 0~1023、转速/亮度 0~100、空调温度 17~30、距离 2~400）；布尔/枚举只允许 `==`/`!=`，枚举值必须在 `choices` 内。引擎读盘走宽松模式（只归一不拒绝），历史脏数据不会让整表被丢弃。
- **R8「设置全局状态」动作按变量定义校验**：enum 取值越界、对非数字变量 `add`、对非双项变量 `toggle` 在保存期即报错。
- **R9 事件触发块 payload 契约**：`EVENT_TRIGGERS` 每项必须有 `payload.event`（导入期断言），运行期空 payload 不再退化成「匹配任意事件」。
- **R2 手动优先对窗户生效**：`window_normal` 补 `g:手动优先_窗 == false` 条件；门/空调保留 mark/clear 变量（仅对自定义规则有效）。**安全动作不让位**（雨烟关窗、蜂鸣、门禁开门）。
- **R3 `g:` 触发的规则随滴答求值**：传感器板离线时「手动优先到期释放」不再被永久卡住。
- **R4 预设迁移只覆盖未改动过的预设**：`light_dark` / `light_off` / `window_normal` 与内置旧版逐字段一致才替换，用户改过的一律保留并记迁移告警；`PRESETS_VERSION` 8→9。
- **R5 关键安全动作有界重试**：关门/关窗/蜂鸣失败重试 2 次（间隔 1 秒），仍失败记「部分成功」并告警；非安全动作保持 fail-fast。
- **R6 `_fire` 返回是否入队**：「持续 N 秒」只在真正入队后才记已触发，冷却未到不再静默吞掉整轮。
- **R10 计时统一单调时钟**：hold / interval / cooldown 改用 `time.monotonic()`；定时触发允许在 300 秒窗口内补触发一次（按当日 key 去重）。

### 验收
- 单测：`test_home_automation.py` 新增 R1–R10 定向用例，`test_home_automation.py`/`test_doorway_linkage.py` 全绿；全量套件仅剩与 `main` 基线一致的 8 项环境依赖错误（缺 `mcp`/`sounddevice` 等）。
- 真机：待分支验收。

## 未发布 · B 板串口帧断流修复（主机侧）

分支：`fix/b-serial-frame-stall`

### 背景
- 现象：前端 `/access` 页长期显示「门口超声波距离：暂无有效距离（检查回波或连接）」，
  `get_distance` 与 `/api/camera/distance` 都取不到值。
- 实测定位：**B 板串口每帧只吐约 96~146 字节就停住**，余下字节要等固件再解析到
  「一整行」命令（裸 `\n`/`\r` 空行不算，任意完整命令都算）才发完。
  距离帧（~146B）、`state` 帧（103B）、V2.9 起带 `state` 快照的 `response` 帧都超过该
  长度 → 必然拆成两段。传感器本身正常：`echo_us` ~700、`valid:true`、随目标移动
  （距离 ~12.1~12.3 cm）。
- 后果链：`get_distance` 等不到归属帧 → 前端文案；心跳 `system/status` 一直失败 →
  连续 3 次重开串口（DTR 复位 B 板，执行器被打回默认，实测 30 分钟内重开 38~41 次）；
  `window`/`door` 命令响应也超时（`window/normal 失败 6202ms`）。

### 变更（仅主机侧，不改固件 / 硬件）
- **接收按 JSON 对象跨块重组**：`_read_b_loop` 由 `readline()` 改为按字节 `read()`，
  新增 `_take_b_frames()` / `_json_object_end()`，用花括号配对（含字符串内 `{}` 与转义
  跟踪）把被断流拆成两段的帧拼回；超 `_B_RX_MAX_BYTES`（8192）丢弃重新同步，
  重开串口时清空重组缓冲（避免复位前的半个对象与后复位数据拼出假帧）。
- **断流补发只读 nudge**：`_send_b_once` 首次等待宽限 `_B_STALL_NUDGE_AFTER`（0.25s），
  宽限内没等到响应就补发一条**只读** `{"cmd":"system","action":"status"}` 把断流顶开，
  再在剩余超时内继续等响应；补发命令不动任何执行器。

### 未改动
- 固件 / 接线不变，`main` 在分支验收前保持不动；`docs/ultrasonic.md` 协议示例不变。

### 验收
- 单测：`tests/test_ultrasonic.py` 新增 `BFrameReassemblyTests` / `BStallNudgeTests`，
  15 项全绿；全量 117 项仅 5 项因缺 `cv2` / `sounddevice` / 人脸模型在 import 阶段报错，
  与 `main` 基线一致，非本次引入。
- 真机（分支部署，未动 `main`）：
  - `POST /api/hardware/tool {"name":"get_distance"}` 连续 6 次成功：
    `valid:true`、`distance_cm` 12.1~12.3、`echo_us` 704~712；id 每次 +4（每轮 = ultrasonic + nudge）。
  - `GET /api/camera/distance` = `{"distance_cm":12.1,"status":"ok","valid":true}`
    （即前端 `/access` 使用的通道，文案被真实读数替代）。
  - 日志近 3 分钟：`非JSON行` = 0（修复前 1038 条 / 30 分钟）；
    `串口已重开` / `心跳失败` / `读线程异常` / `丢弃非本次响应` = 0；
    出现 `[B] window/normal ok 264ms | 固件回读 {'door':'closed','window':'normal',...}`。
  - `get_serial_health`（uptime 65.5s）：`reopen_count=0, reset_count=0,
    heartbeat_fails=0, cmd_timeouts=0, read_err_streak=0`。

## 未发布 · 光照历史前端呈现（反转轴 + 亮/暗标注）

分支：`fix/light-history-viz`

### 背景
- 历史页把光敏 ADC 原值直接画成高度：值越大画得越高，但实际越暗，视觉上与直觉相反；
  且数据点没有任何「亮/暗」说明。

### 变更
- **接口**：`GET /api/light-level/history` 每个采样点新增布尔字段 `light_dark`
  （`true`=暗），由后端按与引擎同款回差逐点标注（raw≥730 判暗、raw≤670 判亮、
  区间内沿用上一点；窗口首个点落在区间时用中点兜底），口径与积木 `light_dark` 能力源一致。
- **前端（历史页光照视图）**：Y 轴反转（刻度仍是原始 ADC，值越大越靠下=越暗）；
  数据点按亮/暗着色（亮=暖黄、暗=夜蓝）；tooltip 与数据表补「亮/暗」标注；
  统计块标签改为「最暗读数 / 最亮读数 / 平均 ADC」，避免「最高=最亮」的误读。
- **文档**：`api.md` 补录 `light_dark` 字段语义。

### 未改动
- raw 入库 / 归档链路不变；`light`（数值源）与既有自定义规则不受影响。

## 未发布 · 光照传感器二分逻辑修正

分支：`fix/light-sensor-binary`

### 背景
- 实测确认光敏 ADC 极性与旧假设相反：**读数越大越暗**（捂住≈918、环境光≈479）。
- 旧默认规则 `light<400` 开灯 / `light>700` 关灯在实际读数下完全错位（亮时不触发开灯、暗时反而触发关灯），光照自动化此前基本失效。

### 变更
- **默认规则**：两条光照预设改为按暗/亮二态联动，`PRESETS_VERSION` 7→8；v8 迁移只强制更新 `light_dark` / `light_off` 两条预设，其余预设的用户配置原样保留。
  - `light_dark`：`light_dark == true`（暗）→ 开灯 100%
  - `light_off`：`light_dark == false`（亮）→ 关灯
- **新布尔源**：自动化引擎新增 `light_dark`（`true`=暗），按回差判定 raw≥730 判暗 / raw≤670 判亮 / 中间维持上一状态（防灯光回照自激）。原始数值源 `light`（0–1023）保留，标签补充「越大越暗」提示。
- **接口**：`GET /api/light-level/history` 返回字段规范化——`timestamp` 改为 ISO-8601 UTC 秒级带 `Z`，`light_raw` 由浮点均值改为取整整数，`samples` 保留；顶层仍为数组。前端 `history.js` 无需改动。
- **文档**：新增本 CHANGELOG，`api.md` 补录 `/api/light-level/history`，`home-automation.md` 更新光照描述。

### 未改动（影响检查结论）
- raw 入库 / 归档链路不变：固件仍上报原始 `light` → `light_raw`（0–1023），`sensor_history` 保留 7 天后按小时 `AVG` 归档进 `sensor_hourly`。明 / 暗为运行期派生，不单独入库。
- 已引用 `light` 的自定义规则不受影响（数值源保留）。

### 验收
- 单测：`test_home_automation.py`、`test_sensor_pipeline.py` 全绿（缺 `mcp` 等环境依赖的 import 错误与 `main` 基线一致，非本次引入）。
- 真机：捂住传感器 → `light_dark=true` → 灯亮；松开 → `false` → 灯灭；阈值附近不抖动。
