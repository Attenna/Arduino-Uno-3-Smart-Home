"""OLED 多行轮播显示（web/automation 版）。

移植自 ``PC_Test/oled_carousel.py``，精简为**扁平 dict** 数据源，
字段与 V2.1 一致（已移除 distance/soil_dry）：

    - A 板：temperature / humidity / light / smoke / rain / touch / motion
    - B 板执行器：b_door / b_window / b_fan / light_lv / b_buzzer
    - 附加：recent_auto（"最近自动化"占位，由 set_data 传入）

OLED 为 8 行(0~7)×16 字符，仅文本。核心行为：
按间隔切页、占位符替换、逐行调用 emitter（内容变化才发）、清掉多余行。
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional

__all__ = ["OledCarousel", "DEFAULT_PAGES", "DEFAULT_PAGES_OLD",
           "DEFAULT_PAGES_V0", "PAGES_VERSION", "is_legacy_default_pages"]

# 默认页面版本：升级后自动替换磁盘上的旧默认页（避免老配置卡住新文案）
PAGES_VERSION = 3

# 默认页面模板（覆盖常见传感器 + 全屋模式 + 执行器状态 + 最近自动化）
# OLED 每行 16 个 ASCII 列宽，1 个汉字约占 2 列，故每行控制在 ~8 个汉字。
DEFAULT_PAGES: List[Dict[str, Any]] = [
    {
        "title": "环境",
        "lines": [
            "【环境状态】",
            "当前温度：{temperature}度",
            "当前湿度：{humidity}%",
            "当前光照：{light}",
        ],
    },
    {
        "title": "全屋模式",
        "lines": [
            "【全屋模式】",
            "当前模式：{home_mode}",
            "风扇：{home_fan}",
            "灯光：{home_light}",
        ],
    },
    {
        "title": "设备",
        "lines": [
            "【设备状态】",
            "门：{b_door}",
            "窗：{b_window}",
            "风扇：{b_fan}%",
            "灯光：{light_lv}%",
        ],
    },
    {
        "title": "安防",
        "lines": [
            "【安全状态】",
            "烟雾：{smoke}",
            "雨水：{rain}",
            "人体：{motion}",
        ],
    },
    {
        "title": "最近自动化",
        "lines": [
            "【最近自动化】",
            "{recent_auto}",
        ],
    },
]

# v1 默认页（旧文案，无「全屋模式」页）。磁盘配置与之完全一致说明用户没自定义过，
# 升级到 PAGES_VERSION=2 时自动替换为新默认页。
DEFAULT_PAGES_OLD: List[Dict[str, Any]] = [
    {"title": "环境", "lines": ["【环境状态】", "当前温度：{temperature}度",
                                "当前湿度：{humidity}%", "当前光照：{light}"]},
    {"title": "安防", "lines": ["【安全状态】", "烟雾：{smoke}", "雨水：{rain}",
                                "人体：{motion}"]},
    {"title": "执行器", "lines": ["【设备状态】", "门：{b_door}", "窗：{b_window}",
                                  "风扇：{b_fan}%", "灯光：{light_lv}%"]},
    {"title": "最近自动化", "lines": ["【最近自动化】", "{recent_auto}"]},
]

# v0 默认页（最早的 web 版短文案，3 页，无全屋模式页）。
DEFAULT_PAGES_V0: List[Dict[str, Any]] = [
    {"title": "环境", "lines": ["温度 {temperature}C", "湿度 {humidity}%",
                                "光照 {light}", "烟 {smoke} 雨 {rain}",
                                "人 {motion} 触 {touch}"]},
    {"title": "执行器", "lines": ["门 {b_door} 窗 {b_window}",
                                  "扇 {b_fan} 灯 {light_lv}",
                                  "蜂鸣 {b_buzzer}"]},
    {"title": "最近自动化", "lines": ["{recent_auto}"]},
]


def is_legacy_default_pages(pages: Any) -> bool:
    """判断磁盘上的页面是否就是历史版本的「默认页」（说明用户没自定义过）。"""
    return pages in (DEFAULT_PAGES_OLD, DEFAULT_PAGES_V0)

# 把状态值翻译成友好中文（open/closed、on/off、True/False 等）
_VALUE_LABELS = {
    "open": "全开", "closed": "关", "opening": "开中", "closing": "关中",
    "normal": "半开45", "on": "开", "off": "关", "true": "是", "false": "否",
}

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class OledCarousel:
    def __init__(
        self,
        emitter: Callable[[int, str], None],
        pages: Optional[List[Dict[str, Any]]] = None,
        interval: float = 5.0,
        line_delay: float = 0.03,
        on_log: Optional[Callable[[str], None]] = None,
    ):
        """
        emitter: 发 OLED 命令的回调 (line:int, text:str) -> None
        pages:   页面列表，每项 {"title":str, "lines":[...]}；缺省用 DEFAULT_PAGES
        interval: 每页停留秒数
        line_delay: 逐行发送间隔(秒)，避免 B 板串口命令错位
        """
        self.emitter = emitter
        self.pages = pages or DEFAULT_PAGES
        self.interval = interval
        self.line_delay = line_delay
        self.on_log = on_log or (lambda m: None)

        self._data: Dict[str, Any] = {}
        self._page_idx = 0
        self._next_switch = time.time()  # 首次 tick 立即显示第一页
        self._last_lines: List[str] = []

    # ---- 数据源（扁平 dict） ----
    def set_data(self, data: Optional[Dict[str, Any]]) -> None:
        """更新占位符数据源。字段见模块 docstring。"""
        self._data = dict(data or {})

    def update_var(self, name: str, value: Any) -> None:
        """单独更新某个占位符（如动态的最近自动化）。"""
        self._data[name] = value

    # ---- 格式化 ----
    def format_text(self, template: str) -> str:
        """替换 {key} 占位符，统一用 _str 格式化；key 不存在则留空。"""
        def repl(m):
            key = m.group(1)
            return self._str(self._data[key]) if key in self._data else ""
        return _PLACEHOLDER.sub(repl, template)

    @staticmethod
    def _str(v: Any) -> str:
        if v is None:
            return "--"
        if isinstance(v, bool):
            return "是" if v else "否"
        if isinstance(v, float):
            return f"{v:.1f}"
        return _VALUE_LABELS.get(str(v).lower(), str(v))

    # ---- 轮播 ----
    def tick(self):
        """在主循环中调用。到期自动切页并渲染当前页。"""
        now = time.time()
        if now >= self._next_switch:
            self._render_current()
            self._advance()
            self._next_switch = now + self.interval

    def _render_current(self):
        page = self.pages[self._page_idx]
        lines = page.get("lines", [])
        title = page.get("title", str(self._page_idx))
        self.on_log(f"[OLED] 显示页: {title}")
        rendered = [self.format_text(ln) for ln in lines]
        # 逐行下发，仅在内容变化时发送，并加节流避免命令错位
        for line_no, text in enumerate(rendered):
            prev = self._last_lines[line_no] if line_no < len(self._last_lines) else None
            if text != prev:
                self.emitter(line_no, text)
                time.sleep(self.line_delay)
        # 清掉当前页未用到的多余行，避免残留上一页内容
        for line_no in range(len(rendered), 8):
            prev = self._last_lines[line_no] if line_no < len(self._last_lines) else None
            if prev != "":
                self.emitter(line_no, "")
                time.sleep(self.line_delay)
        self._last_lines = rendered

    def _advance(self):
        self._page_idx = (self._page_idx + 1) % len(self.pages)

    def reset(self):
        """重置轮播计时（如数据大幅变化想立即刷新时调用）。"""
        self._next_switch = time.time() + self.interval