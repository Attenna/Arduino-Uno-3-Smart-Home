"""web 仪表盘服务包。

启动：py -3.13 run_web.py
"""
from .app import create_app

__all__ = ["create_app"]
