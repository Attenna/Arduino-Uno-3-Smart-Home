"""Web 内置自动化规则引擎（积木式「当触发 → 如果条件 → 执行动作 / 否则切换」）。

统一自动化入口：规则以积木 JSON 存储（见 schema.py），在 /automation 页面用 Blockly
可视化编排；传感器快照/事件经 hardware bridge 注入，执行器动作经 bridge
（MCP stdio → mcp_home_server）下发到 Module B。
"""
from .engine import AutomationEngine
from .schema import ValidationError, validate_rules

__all__ = ["AutomationEngine", "ValidationError", "validate_rules"]
