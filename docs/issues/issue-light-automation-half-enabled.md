# 光敏读数正常但光照联动失效：内置暗/亮预设只启用了一条

> 本地 issue 草稿（GitHub 暂时不可用，恢复后搬运为正式 Issue）。

## 问题与复现

真机 `GET /api/status` 与 `sensor_history` 显示光敏每秒上报，环境光 raw≈810、
捂住≈985，ADC 与接线正常；但捂住光敏灯没有任何反应。

运行数据 `data/automation_rules.json`（`presets_version=10`）：

- 内置 `light_dark`（暗→开灯）**enabled=false**；
- 内置 `light_off`（亮→关灯）enabled=true；
- 另有两条早前手工建立的「原始光照 ≥600 开灯 / <600 关灯」规则，均 enabled。

传感器触发规则只在上升沿执行一次，Web 重启后条件已成立也不会补发动作，因此灯停在
最后一次状态。页面没有提示「光照预设只启用一半」，也没有提示原始光照规则会与暗/亮
预设抢同一个灯，用户只能看到「光敏不工作」。

## 计划修改

- `PRESETS_VERSION` 10 → 11：首次启动发现光照两条预设只启用一条时，按内置内容恢复并
  成对启用；两条都停用视为有意关闭，不处理。
- 「恢复内置」重新启用内容未被改过的停用预设；改过内容的保留停用。
- 自动化页新增「光照只启用一半」「原始光照规则与暗/亮预设抢灯」提示。
- `/api/status` 暴露引擎同源 `light_dark`；水彩首页光照显示 `raw · 暗/亮`。
- 历史页数据类型/时间范围下拉改为逐项 `data-i18n`（原 `data-i18n-options` 生成的键不存在，
  整组选项一直不翻译）。

## 验收条件

- 环境光 raw≈810（暗）时灯在 2 秒内开至 100%；遮住光敏保持开灯；
- 亮态（raw≤670）时灯关；阈值附近不抖动；
- 自动化页不再出现「只启用一半」与「原始光照抢灯」提示；
- `test_home_automation`、`test_sensor_pipeline`、`test_watercolor_ui.js`、
  `test_history_ui.js` 通过。

## 影响

涉及 `default_rules.py`、`engine.py`、`api/status.py`、`automation.js`、
`watercolor-home.js`、`history.html`、`lang.js` 与文档；不改串口协议、数据库结构、
A/B 固件与 Docker 编排。升级会重写一次 `automation_rules.json`，需真机复核。
