# 光照传感器二分逻辑 · 收尾方案（API 格式 / 积木 / 归档影响 / 变更文档）

## Context（为什么做）

* 已实测确认光敏 ADC 极性为「读数越大越暗」：捂住≈918，环境光≈479。仓库旧默认规则（`light<400` 开灯 / `light>700` 关灯）在实际读数下完全错位——亮时不触发开灯、暗时反而触发关灯，光照自动化此前基本失效。

* 已在分支 `fix/light-sensor-binary`（worktree `smarthome-fix-light-sensor`，**尚未提交**）把两条默认预设改为 `light>730` 开灯 / `light<670` 关灯，`PRESETS_VERSION` 7→8，v8 迁移只强更这两条光照预设、保留其余用户配置。

* 本轮收尾：① 修复 `/api/light-level/history` 返回格式；② 积木侧提供「暗/亮」简单二态并检查影响；③ 把影响与变更写进文档并新建 changelog。raw 入库/归档链路确认**无需改动**。

## 已确认决策

1. **API**：只规范化字段，保持顶层数组（不包元数据）。
2. **积木**：保留 raw `light` 数值源（补极性提示）+ 新增布尔源 `light_dark`（暗/亮），带回差（暗 `raw≥730` / 亮 `raw≤670` / 中间维持上一状态）。
3. **raw 入库归档**：不改，仅记录。
4. **文档**：更新现有 docs + 新建 `docs/CHANGELOG.md`。

***

## 变更清单

### 1) API 规范化 — `PC_Test/web/database.py` → `get_light_level_history()`

现状缺陷：`timestamp = MIN(received_at)` 带微秒且无时区标记（前端要靠 `serverDate()` 补 `Z`）；`light_raw` 是 `AVG()` 浮点噪音。

* `timestamp` 统一为 ISO-8601 UTC 秒级带 `Z`：

  * 秒级分支：`strftime('%Y-%m-%dT%H:%M:%SZ', MIN(received_at))`

  * 归档分支：`strftime('%Y-%m-%dT%H:00:00Z', hour_start / received_at)`

* `light_raw` 取整：秒级 `CAST(ROUND(AVG(light_raw)) AS INTEGER)`，归档 `CAST(ROUND(light_raw) AS INTEGER)`。

* 保留 `samples`，顶层仍是数组。

* 前端 `history.js` **无需改**：`serverDate()`（lang.js:817-820）对带 `Z` 的串原样接受。

* `docs/api.md` 补该端点文档（当前完全未收录）。

### 2) 积木「暗/亮」布尔源

* `PC_Test/web/automation/capabilities.py`

  * `light` label 改为「光照（原始 ADC，越大越暗）」，`unit` 保持 `0-1023`。

  * 新增 `light_dark`，`kind: bool`，label「光照状态（暗/亮）」（true=暗）。

* `PC_Test/web/automation/engine.py`

  * 在 `on_snapshot()`（engine.py:511-520）按 730/670 窗口维护实例状态 `self._light_dark`。

  * 在 `_context()`（engine.py:785-808）暴露 `ctx["light_dark"]`；传感器过期时并入现有的 pop 名单（engine.py:791）。

* `PC_Test/web/automation/default_rules.py`：两条光照预设改用布尔源

  * `light_dark`（预设）：条件 `{'sensor':'light_dark','op':'==','value':True}` → 开灯 100%

  * `light_off`（预设）：条件 `{'sensor':'light_dark','op':'==','value':False}` → 关灯

  * 回差逻辑从「两条 raw 阈值」收敛到 engine 一处，`PRESETS_VERSION` 维持 8。

* 前端 `automation.js` **无需改**：`boolSourceOptions` / `sourceKind()` 由 `CAPS.sources` 按 `kind` 数据驱动（automation.js:104-113、963、1850/1888），新增 bool 源自动出现在布尔触发/条件积木。

* 注意：预设 id `light_dark`（暗→开灯）与新数据源 `light_dark`（当前是暗）同名但语义一致，文档中说明避免混淆。

### 3) raw 入库 / 归档 — 不改

* `ingest_sensor()` 把固件 `light`→`light_raw`（0..1023 清洗，database.py:301-325）；`sensor_history` 保留 7 天后按小时 `AVG(light_raw)` 归档进 `sensor_hourly`（database.py:327-367）。与新业务逻辑零耦合，无需改动。

* 仅在文档说明：明/暗是**运行期派生**，不单独入库；需要审计时可另开需求。

### 4) 文档

* `docs/api.md`：新增 `### GET /api/light-level/history?hours=24` 段落 + 字段表（timestamp/light\_raw/samples）。

* `docs/home-automation.md`：补充积木新增 `light_dark` 暗/亮布尔、阈值 730/670、raw 不变（已有极性/实测描述，本轮补布尔源）。

* `docs/CHANGELOG.md`（**新建**）：记录本次（语义反转、阈值改 730/670、`PRESETS_VERSION` 8、`light_dark` 数据源、`/api/light-level/history` 字段规范化）。

* `docs/README.md`：文档索引加入 CHANGELOG。

***

## 影响检查结论

* **blocks 逻辑**：raw 数值源仍在 → 已有自定义规则（引用 `light`）不受影响、不破坏校验；新增布尔源是纯增量。默认预设改布尔后回差唯一收敛到 engine。

* **归档处理**：无影响，raw 链路不动。

* **兼容性**：`timestamp` 改带 `Z` 仅 `history.js` 消费且已兼容；`light_raw` 由浮点改整数（ADC 本就整数），精度损失可忽略。

## 测试与验收

* 单测：`PYTHONPATH=PC_Test python -m unittest discover -s PC_Test/tests -v`

  * `test_sensor_pipeline.py`：`get_light_level_history` 断言 light\_raw 为整数、timestamp 形如 `YYYY-MM-DDTHH:MM:SSZ`。

  * `test_home_automation.py`：光照用例改布尔口径；新增 `_light_dark` 回差单测（900→暗 / 700→维持 / 479→亮）；迁移用例断言布尔条件且 `presets_version==8`。

  * `test_blocks_flat_ui.js`：确认布尔源下拉含 `light_dark`（有断言则更新）。

* 与 `main` 基线比对全量套件，确认无新增失败（当前失败均为缺 `mcp`/`serial`/`sounddevice` 的环境问题）。

* 真机：捂传感器→`light_dark=true`→灯亮；松开→`false`→灯灭；阈值附近不抖动（灯光回照不自激）。

## 涉及文件

* `PC_Test/web/database.py`

* `PC_Test/web/automation/capabilities.py`

* `PC_Test/web/automation/engine.py`

* `PC_Test/web/automation/default_rules.py`

* `PC_Test/tests/test_home_automation.py`

* `PC_Test/tests/test_sensor_pipeline.py`

* `PC_Test/tests/test_blocks_flat_ui.js`（如需）

* `docs/api.md`、`docs/home-automation.md`、`docs/CHANGELOG.md`（新）、`docs/README.md`

