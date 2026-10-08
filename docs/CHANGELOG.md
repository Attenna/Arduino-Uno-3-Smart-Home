# 变更记录（CHANGELOG）

记录对系统行为 / 接口有影响的变更。新条目置于顶部。

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
