"""Web 内置自动化规则引擎（积木式「当触发 → 如果条件 → 执行动作 / 否则切换」）。

与旧 automation/ 目录下的 .auto 文本 DSL 的区别：
- 旧 DSL 是直连串口的独立程序，不适用 Docker 部署（串口由 voice 容器独占）；
- 本引擎运行在 web 容器内，传感器快照/事件经 hardware bridge 注入，
  执行器动作经 bridge（relay → voice /tool）下发到 Module B。
"""
from .engine import AutomationEngine
from .schema import ValidationError, validate_rules

__all__ = ["AutomationEngine", "ValidationError", "validate_rules"]
