# 变更记录（CHANGELOG）

记录对系统行为 / 接口有影响的变更。新条目置于顶部。

## 2026-10-09 · ASRPRO 串口控制接口（SH2 意图白名单）+ 旧 LLM 语音弃用

分支：`feat/asrpro-serial-control`

### 变更
- **串口桥接（`PC_Test/asrpro_bridge.py`）**：在保留 `SH1` 1–9 号命令的前提下新增 `SH2`
  协议 `SH2 <请求编号> <意图名> [name=value ...]`，应答 `SH2 <请求编号> <意图名>
  <OK|REJECTED|FAILED|TIMEOUT> [name=value ...]`。意图来自**启动时载入的 JSON 白名单**
  （`--intents` / `ASRPRO_INTENTS_CONFIG`；未指定、缺失、损坏或 schema 非法一律回退内置默认），
  带参数 schema 校验（整数/枚举/布尔，拒绝自由文本、重复/未知/缺参）、请求编号去重缓存
  （重复帧回放结果、不二次动作）、`TimeoutError → TIMEOUT` 且**不自动重试**。
- **动态意图与发现**：内置默认 7 个业务意图（`light`/`door`/`window`/`fan`/`buzzer`/`ac`/
  `status`）加只读发现 `list_intents`（回 `count` 与逗号名单，过大则省略名单）。增改意图只需
  改配置、**无需改代码**；**串口侧只读，不可注册/修改/删除意图**，保留白名单安全边界。
- **帧长**：单帧上限由 63 提升到 127 字节（容纳带多参数的 `ac` 帧），仍整帧丢弃超长/乱码。
- **接口文档**：设计稿转正为 [asrpro-serial-control.md](asrpro-serial-control.md)（帧格式、
  意图清单、**配置驱动的动态意图与发现**、结果码、反向播报预留帧、ASRPRO 侧天问 C++ 收发示例、
  接线与安全要求）。
- **旧 LLM 语音助手**：`README`/`api.md`/`architecture.md` 标注**已弃用**；`docker-compose.yml`
  的 `voice` 服务加 `profiles: ["voice"]`，`docker compose up -d` **默认不再启动**语音容器；
  `local-llm`/`dashscope`/`desktop` 三个覆盖文件显式重置该 profile 以保持原用法。

### 未改动 / 影响
- 不改 A/B 板固件、不改接线、不改 `SH1` 行为；ASRPRO 板载固件仍只发 `SH1`，升级到 `SH2`
  随场景一并实施（见接口文档 §13）。
- 不涉及场景实现（出门天气、门禁欢迎词），仅预留接口；不实现"车库门"（无独立执行器）。
- Web 侧 `/api/voice/*` 代理在语音容器未启动时返回 502/503，不影响硬件链路与面板。

### 验收
- 单测：`PC_Test/tests/test_asrpro_bridge.py` 扩到 23 项（`SH2` 合法/未知意图/坏参数/去重/
  编号冲突/`status` 只读/长帧/超长丢弃 + 配置加载、缺失/损坏/非法回退、`list_intents` 发现、
  配置不能越权 + `SH1` 全量回归），全部通过；`compileall` 通过。
- Compose：`docker compose config --services` 验证基础编排只输出 `web/camera`（语音需
  `--profile voice`），三个覆盖文件仍含 `voice`。
- 真机：**未验证**（本机无法连通香橙派；按仓库流程需在分支上做真机验收后再并入 `main`）。

## 2026-10-09 · OLED 多页轮播下移 B 板固件（B 主动拉取）

分支：`feat/oled-b-pull-carousel`

### 背景
- 旧实现的 OLED 多页轮播跑在**香橙派**侧：每 15s 切页、逐行调用 `oled` 工具，每页向 B 板下发 4~8 条串口命令。这种持续的「Pi 逐行推送 + B 逐行 SPI 刷新」串口流量，是此前怀疑「OLED 刷新导致 B 板复位」的来源。
- 前置核查：仓库固件**并未禁用 OLED**（`CommandDispatcher::begin()` 无条件 `_oled.begin()`），引脚定义正确（CS=D10 / DC=A0 / RES=A1，SCK=D13 / MOSI=D11 硬件 SPI）；真正关闭的是香橙派侧轮播（`engine.oled_enabled` 默认 `False`）。

### 变更
- **固件（Module B `V2.12`）**：新增 `src/core/OledCarousel.{h,cpp}`，把 3 页（Environment/Devices/Safety）排版与 15s 轮播硬编码进固件，全部文案走 PROGMEM；`Protocol` 每拍发一帧上行 `{"module":"output","type":"oled_req","id":N}`，并新增按首字符 `@` 分流的紧凑数据帧解析（早于 JSON 解析，不触发 `parse_error`）。
- **上位机（MCP）**：`mcp_home_server.py` 新增 `_compose_oled_frame` / `_push_oled_frame` 与 `oled_req` 分支；回帧为 8 段逗号分隔的紧凑文本 `@D<id>,<t10>,<h10>,<light>,<smoke>,<rain>,<touch>,<motion>`（温度/湿度 ×10，读不到用 `-32768`，帧长恒 <64B）。写帧用非阻塞 `_b_lock`：拿不到锁即丢帧（B 15s 后重试），绝不阻塞读线程。
- **上位机（Web）**：停用 `engine` 的逐行轮播线程 `_oled_loop`（`start()` 不再起 `automation-oled` 线程）；OLED 配置与 `oled_carousel` 保留仅作存档与 `{}` 占位符格式化。`automation.html` OLED 面板文案同步说明。
- **线协议**：新增上行 `oled_req` 与下行 `@D...` 紧凑帧，记录于 `docs/serial-protocol.md`。

### 影响与迁移
- 串口流量从「每页 4~8 帧」降到「每 15s 2 帧」，从根本上规避逐行 SPI 刷新风险。
- `oled/show_text`、`oled/clear` 命令保留但会被下一拍切页覆盖（仅调试用）。
- 需烧录 B 板固件 V2.12 方可见屏上轮播；未升级时上位机收到 `oled_req` 也只回一帧、不影响旧行为。

### 验收
- 单测：新增 `test_oled_pull.py`（9 项）、`test_oled_startup.py` 新增 1 项；全量套件仅剩与基线一致的 6 项环境 ImportError。
- 固件：`pio run` 编译通过（RAM 80.9% / Flash 86.1%）。
- 真机（2026-10-09，分支验收通过后并入 `main`，香橙派）：B 板烧录 V2.12 后启动帧 `READY version=V2.12 role=OUTPUT_NODE`；`oled_req` 每 15s 一次，回帧 `@D2,272,280,1017,0,0,0,1`（27.2℃/28.0%/光 1017/有人）与 A 板快照一致；稳态 180s 内 0 复位（`b_reset_count=1` 仅启动）；逐行 `MCP -> oled` 调用数 0；屏上人工确认「正常轮播，数值合理」。合并 PR [#80](https://github.com/Attenna/Arduino-Uno-3-Smart-Home/pull/80)。

## 2026-10-09 · 人脸识别历史记录入库修复（#75）

分支：`fix/75-face-event-persistence`。Issue：#75「人脸识别历史记录入库不及时、有丢失」。

### 变更
- **去抖与写库解耦**：`AccessGuard.handle_face_result` 每轮识别都各自写一条 `face_events`
  （含陌生人，不再因空 `face_id` 合并互相顶掉）；`merge_repeat` 只抑制重复的开门动作与
  通行日志。同一人站 30 秒的事件条数 = 识别轮数。
- **判定一次落终态**：单条 `INSERT` 写入最终 `status`/`verified`/`deny_reason`，不再先插
  `pending` 再更新；放行瞬间 `/api/face/events/latest` 即为 `granted`，也不会留下永久
  `pending` 行。删除已无调用方的 `update_face_event_status`。
- **观测轮次留痕**：新增 `AccessGuard.record_observation`；哨兵 `inspect_once` 的太远/
  节流/无脸/未唤醒/摄像头失败/出错分支写一条 `status='observed'` 记录（`deny_reason`
  存轮次种类）。环境类（`idle`/`no_camera`/`no_identity`）只在状态变化时写一行防刷屏。
- **冷却期仍记录**：哨兵在 `cooldown` 内认出同一人改用 `record_only=True` 补记历史，
  不再重复开门。
- **单帧接口留痕**：`POST /api/face/recognize` 写 `device_source='web'` 的 `face_events`
  行（`record_only`，不开门、不广播），与 `docs/api.md` 一致。
- **前端三态**：`observed`/`pending` 渲染为灰色「已记录 / 判定中」，不再一律显示「已拒绝」；
  轮询按 `id + status` 去重，状态改写会重新渲染。
- **配置**：新增 `face.watcher.repeat_window`（默认 `8.0` 秒，`0` 不去抖）。

### 验收
- 单测：新增 `PC_Test/tests/test_face_event_persistence.py`（逐轮留痕、陌生人各成行、去抖只挡
  动作、终态一次写入、观测留痕与环境去抖、`/recognize` 留痕不开门）；`test_face_latency.py`
  的测试替身同步新增 `record_observation`。
- 真机（2026-10-09，分支部署后并入 `main`，香橙派）：每轮都有记录（30 秒窗口 16 行，相邻轮次
  最大间隔 2 秒＝取帧间隔）；连续陌生人 `unmatched_face` 各自成行；网页路径命中已录身份 `B`
  （score 0.998）单条写入 `granted`/`verified=1`/`deny_reason=NULL`，全表 `pending=0`；
  `/api/face/recognize` 行 `device_source='web'` 且 `access_logs`、门状态不变（`record_only`）；
  去抖只挡动作日志（同窗口 `access_logs` 约每 8 秒一条，`face_events` 每轮都写）。
- 影响：不改数据库结构、不改人脸库、无需重建模型；部署只需重建 Web 容器。

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
