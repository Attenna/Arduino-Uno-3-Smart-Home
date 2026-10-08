# Blocks 积木自动化潜在风险清单

> 本地 issue 草稿（GitHub 恢复后搬运为正式 Issue）。来源：对 `PC_Test/web/automation/` 的
> 只读静态审计。标注「已核验」的条目经二次抽查确认；其余为静态阅读所得，行号以当前
> `main` 为准。

## 结论摘要（优先修）

1. **R1（高）** 空调风速枚举在「能力清单 / 前端 / 校验 / 执行」四层不一致，用户**无法保存**
   任何含风速的空调规则 —— 唯一「功能直接不可用」项，改动面小。
2. **R2 + R3（高）** `g:手动优先_门/窗/空调` 是**只写不读**的死变量，「手动优先」是误导性
   承诺；且让位释放规则依赖 A 板快照，传感器板离线时灯/风扇自动控制会被**永久抑制**。
3. **R5 + R4（中）** 安全类动作（开关门/窗）无重试补偿、动作序列 fail-fast；加上用户改过的
   `light_dark`/`light_off` 预设会在迁移时被静默覆盖 —— 长期运行最易被投诉的两类问题。

---

## 高优先级

### R1 空调风速四层枚举不一致 → 空调动作无法保存（已核验）
- **涉及**：`PC_Test/web/automation/capabilities.py:203`、`PC_Test/web/static/js/automation.js:792-793`、
  `PC_Test/web/automation/schema.py:285`、`PC_Test/midea_ac.py:45`、`PC_Test/midea_ac.py:142-145`
- **问题**：能力清单与前端下拉提供 `low/mid/high`；`schema.validate_rule` 只接受
  `auto/20/40/60/80/100`；而引擎实际下发的 `midea_ac.FAN_LEVELS` 又是 `auto/low/mid/high`。三处口径互斥。
- **复现**：自动化页新建规则 → 动作选「空调」→ 风速选「低/中/高」→ 保存 →
  `ValidationError("空调风速只能是 auto/20/40/60/80/100")`，HTTP 400，规则存不下去。
  反向手改 JSON 写 `fan:"60"` 能过校验，但执行时 `apply_overrides` 抛 `ValueError`。
- **建议**：以 `midea_ac.FAN_LEVELS` 为唯一真源，schema 改为 `("auto","low","mid","high")`，
  旧数值经 `_LEGACY_FAN` 兼容映射。

### R2 「手动优先」对门/窗/空调只写不读，让位承诺不成立（已核验）
- **涉及**：`PC_Test/web/automation/global_state.py:54-58`、`default_rules.py:35-93`、
  `default_rules.py:101/113/124/135`、`default_rules.py:167-185`
- **问题**：门/窗/灯/风扇/空调都定义了 `g:手动优先_x` 并配了 `manual_mark_x`（置 True）+
  `manual_clear_x`（hold 30s 清 False）；但**只有灯和风扇**的自动规则真正读取该条件作为抑制开关。
  `g:手动优先_门 / _窗 / _空调` 全仓库无任何规则读取。
- **复现**：面板手动把窗户全开 → `window_normal`（interval 2s）立刻按 rain/smoke 把它压回 45°；
  手动操作门/空调同样无让位效果。
- **建议**：要么给门/窗/空调自动规则补 `g:手动优先_x == false` 条件（与灯/风扇对齐），
  要么删掉无效的 mark/clear 预设与变量，避免误导。

### R3 手动优先到期释放依赖 A 板快照：传感器板离线时自动控制被永久抑制（已核验）
- **涉及**：`default_rules.py:65-69/77-81`、`engine.py:514-526`、`engine.py:611-631`、`engine.py:812-814`
- **问题**：`manual_clear_light/fan` 是 **sensor 触发**（`sensor: g:手动优先_灯`，hold 30s），
  而 sensor 触发只在 `on_snapshot()` 里求值；`_tick_loop` 只处理 interval/time。
  `_context()` 在数据陈旧时只清 A 板传感器键，**不清 `g:` 变量**。
- **复现**：手动开灯（置 `g:手动优先_灯=True`）后拔掉 A 板串口 → 30s 到期规则永不触发 →
  `light_dark/light_off` 持续被抑制，自动灯光长期失效，直到快照恢复。
- **建议**：把「手动优先到期」改为 time/interval 触发，或让引擎对 `g:` 型 sensor 触发也随 tick 求值。

---

## 中优先级

### R4 预设迁移覆盖用户对 light 预设的修改；<6 版本更会整体替换所有同名预设
- **涉及**：`engine.py:343-354`、`default_rules.py:7`（`PRESETS_VERSION=8`）
- **问题**：`_migrate_legacy_rules` 对 `pid in {light_dark, light_off}` 整体替换，只保留 `enabled`；
  用户改过的阈值/附加条件/名称/冷却全部丢失。`presets_version < 6` 时保留分支不生效，
  **所有**同名预设都被新内容覆盖。
- **建议**：迁移前备份「被替换且与默认版不一致」的规则并提示，或仅当内容等于旧默认版才替换。

### R5 动作序列 fail-fast 且无重试/补偿，安全联动可能半途失败
- **涉及**：`engine.py:991-997`、`default_rules.py:13-15`、`default_rules.py:190-193`
- **问题**：`_run_actions` 逐动作执行，任一动作 `ok=False` 即 `break`，不重试、无补偿。
  典型规则 `access_open_door`（开门→延时 10s→关门）若关门时桥离线/503，门会一直开着。
- **建议**：对关键安全动作（关门/关窗、烟雾蜂鸣）引入有界重试或失败后二次补偿；
  或在日志/界面把「部分成功」标红告警。

### R6 hold_sec 与 cooldown/动作锁冲突时，本轮「持续触发」永久丢失
- **涉及**：`engine.py:912-914`、`engine.py:955`、`engine.py:965`
- **问题**：满足持续时长后**先**置 `_hold_fired[rid]=True`，**再** `_fire`；而 `_fire` 若因
  冷却未到或动作锁被占直接 return，`_hold_fired` 已置位，本轮不再触发，只有等条件转假重新计时。
- **建议**：`_fire` 返回是否真正执行，成功入队后再置 `_hold_fired`。

### R7 条件/触发数值缺范围与类型匹配校验，可能保存出「永远不成立」的规则
- **涉及**：`schema.py:88-91`、`schema.py:144-152`、`engine.py:833-854`
- **问题**：除 `distance_cm` 外不做阈值范围校验；sensor/cond 触发块允许阈值为任意字符串。
  而 `_compare` 在「数值源 vs 字符串阈值」时进入字符串分支，`>/</>=/<=` 一律返回 False；
  比较符也不按源 `kind`（number/bool/enum）匹配。手写 `temperature > "abc"` 保存通过、运行恒假、无告警。
- **建议**：按 `CONDITION_SOURCES[sensor]["kind"]` 约束比较符集合与阈值类型并做量程校验。

### R8 state 动作的 enum 取值 / toggle / add 目标类型未在保存期校验
- **涉及**：`schema.py:344-386`、`global_state.py:323-350`、`global_state.py:384-394`
- **问题**：`_validate_state_action` 对 enum/text 直接 `str(value)`，不校验是否属于该变量 choices；
  `toggle`/`add` 也不校验类型可组合性，真正的拒绝发生在运行期。
- **建议**：严格模式（页面保存，`var_types` 存在）下按变量定义校验 choices 与 op/类型可组合性。

### R9 事件 payload 全等匹配的「缺 payload → 任意事件触发」隐患（当前无实例）
- **涉及**：`engine.py:923-924`、`capabilities.py:96-135`
- **问题**：`want = EVENT_TRIGGERS[trig["event"]].get("payload", {})`，payload 缺失时空 payload 使
  `all(...)` 恒真 → 该事件触发块匹配**任意**事件。当前 12 个事件项都带含 `event` 键的 payload，现状安全，
  但契约仅靠注释约束，新增事件极易漏写。
- **建议**：模块导入时断言 `EVENT_TRIGGERS` 每项都含 `payload.event`，或在事件求值中对空 payload 直接拒绝。

### R10 时间/持续判定用系统墙钟（非单调时钟）
- **涉及**：`engine.py:907`、`engine.py:611-631`
- **问题**：仅 `distance_cm` 的 hold 用 `time.monotonic`，其余 hold/interval 用 `time.time()`，
  定时触发用 `datetime.now()`；NTP 回拨/DST 会导致计时抖动。定时触发靠「当日 key 去重」，
  若该分钟内 tick 被阻塞或进程暂停，当天不再补触发。
- **建议**：hold/interval 统一改用 `time.monotonic`；定时触发用绝对时间并允许窗口内补触发。

---

## 低优先级

- **R11 引擎锁内做 DB/文件 IO**：`engine.py:866-870/952-957/816/827` 持锁期间访问 SQLite 与全局状态锁；
  `save_rules` 也在锁内校验写盘。建议上下文快照在锁外一次性构建。
- **R12 HTTP 出站 SSRF 残余**：`webhook.py:40-56/128-132`，无点主机名/`.local`/`.internal`/`.lan`
  一律判内网放行，且请求时才解析 DNS（TOCTOU/rebinding）。默认本就近放行 loopback/private，
  仅在云元数据场景有意义。建议解析后校验实际 IP。
- **R13 `automation_logs` 无保留/清理策略**：`database.py:383-393` 只增不删，`detail_json` 记录完整动作序列，
  长期运行膨胀（对比传感器历史有 7 天保留）。
- **R14 `_perform` 循环无整体异常兜底**：`engine.py:982-1006` 动作循环只有 `finally`，
  某分支抛异常会静默终止动作线程且不落执行日志。建议调用点包 `try/except` 并记失败日志。
- **R15 引擎层事件去重对无 `ts` 事件不生效**：`engine.py:537-545` 仅对带 `ts/timestamp` 的事件去重；
  门禁事件不带 ts，仅靠 `access_guard` 的 8s 去抖。建议 `broadcast` 补 `ts` 复用引擎去重。
- **R16 迁移落盘条件偏窄**：`engine.py:214-218/369-370`，仅当有新增或 `migrated>0` 才落盘；
  纯「删除已废预设」或纯 warning 映射不会刷新 `presets_version`，下次启动重跑同一迁移（有 backup 保护）。
  建议只要有迁移行为（含 dropped）就落盘刷新版本号。

---

## 需进一步验证（静态审计未定论）

- **P1（推测）** 红外回声抑制与事件求值依赖 `address`/`command` 为整数
  （`engine.py:595-598/935-938`）；若某链路把它上报成 `"0x45"` 字符串，`int(...)` 失败，
  红外规则静默失效。需以真实硬件帧确认类型。
- **P2（推测）** `distance_cm` 规则在 `on_distance` 中无条件 `_armed.add`，首帧即可触发；
  但 `capabilities.py:7-9` 称超声波在 A 板编译期关闭。若确无 distance 事件，则这些规则恒不生效。
  需确认固件是否仍上报。

---

## 核验状态

- 已二次核验：R1、R2、R3（读取源码确认四层枚举、只写不读变量、sensor 触发求值路径）。
- 其余条目为静态阅读所得，实施前建议按各自 `file:line` 复核。
- 本清单为**只读审计产出**，未修改任何代码。
