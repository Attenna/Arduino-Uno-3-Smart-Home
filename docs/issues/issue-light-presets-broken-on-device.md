# 光照联动在真机不生效：内置 light_dark 被禁用、light_off 被改成 light>300 开灯

> 本地 issue 草稿（GitHub 暂时不可用，恢复后搬运为正式 Issue）。

## 问题与复现

香橙派 runtime 的 `data/automation_rules.json` 中，两条内置光照预设被人工改动：

- `preset=light_dark`（`id=9a4be958`）：`enabled=false`，条件为 `light < 400`（旧错误极性，真实读数下永不触发）。
- `preset=light_off`（`id=f744b908`）：`enabled=true`，条件被改成 `light > 300`，动作被改成「开灯」，名称改为「有人：光照高于300开灯」。

现场实测光敏 ADC **读数越大越暗**（捂住≈918、环境光≈479）。因此：

- `light > 300` 在环境光与遮盖下恒为真 → 灯被该规则持续压为「开」；
- `light < 400` 恒为假 → 开灯规则永不触发。

即使固件/服务端二态逻辑已修正（`fix/light-sensor-binary`，`PRESETS_VERSION` 8），只要这两条预设维持现状，光照联动仍不工作。全局状态同时为 `g:有人在家=false`、`g:手动优先_灯=true`，进一步阻断两条预设的触发。

复现：登录 web 后看 `GET /api/automation/rules` 或 `GET /api/automation/preview`，观察上述两条规则的条件与 enabled。

## 计划修改

- 明确策略：恢复内置预设语义（`light_dark` 开灯 / `light_off` 关灯），还是保留当前自定义。
- 若恢复：启用 `light_dark`；把 `light_off` 的动作改回 `off`、条件改回布尔 `light_dark == false`、名称复原。
- 复核 `g:有人在家` / `g:手动优先_灯` 的期望语义与自动置位规则，确认不会长期挡住联动。

## 验收条件

- 捂住传感器 → 灯亮（100%）；松开 → 灯灭；阈值附近不抖动。
- `GET /api/automation/preview` 中两条预设的 `conditions_hold` 随明暗正确翻转。

## 影响

涉及 `PC_Test/web/automation/default_rules.py` 的预设语义，以及运行数据 `data/automation_rules.json`；不涉及数据库结构变更。需真机复核。
