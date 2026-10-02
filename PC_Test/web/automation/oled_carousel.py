"""OLED 多行轮播显示（web/automation 版）。

移植自 ``PC_Test/oled_carousel.py``，精简为**扁平 dict** 数据源，
字段与 V2.1 一致（已移除 distance/soil_dry）：

    - A 板：temperature / humidity / light / smoke / rain / touch / motion
    - B 板执行器：b_door / b_window / b_fan / light_lv / b_buzzer
    - 全屋状态（来自全局状态 g: 变量）：home_mode / presence / fan_auto
    - 附加：recent_auto（"最近自动化"占位，由 set_data 传入）

OLED 为 8 行(0~7)×16 字符，仅文本。核心行为：
按间隔切页、占位符替换、逐行调用 emitter（内容变化才发）、清掉多余行。
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional

__all__ = ["OledCarousel", "DEFAULT_PAGES", "DEFAULT_PAGES_V5",
           "DEFAULT_PAGES_V4", "DEFAULT_PAGES_V3",
           "DEFAULT_PAGES_OLD", "DEFAULT_PAGES_V0", "PAGES_VERSION",
           "is_legacy_default_pages", "to_oled_text"]

# 默认页面版本：升级后自动替换磁盘上的旧默认页（避免老配置卡住新文案）
# v4：B 板字库（u8x8_font_chroma48medium8_r）只有 ASCII 字形，汉字上屏是乱码，
#     默认文案全部改为英文。
# v5：全屋模式页新增 Person 行（有人在家时自动调节会暂停，便于用户理解）。
# v6：「全屋模式」引擎状态机拆除，home_mode/presence/home_fan/home_light
#     占位符改由全局状态供数（g:全屋模式 / g:有人在家 / g:允许自动开风扇；
#     覆盖档位已不存在，换成风扇安全线一行）。
PAGES_VERSION = 6

# 默认页面模板（覆盖常见传感器 + 全屋状态 + 执行器状态 + 最近自动化）
# 每行 16 个 ASCII 列宽，务必只用英文/数字/符号。
DEFAULT_PAGES: List[Dict[str, Any]] = [
    {
        "title": "Environment",
        "lines": [
            "= ENVIRONMENT =",
            "Temp: {temperature}C",
            "Hum:  {humidity}%",
            "Light:{light}",
        ],
    },
    {
        "title": "Home Mode",
        "lines": [
            "= HOME MODE =",
            "Mode: {home_mode}",
            "Person:{presence}",
            "FanAuto:{fan_auto}",
        ],
    },
    {
        "title": "Devices",
        "lines": [
            "= DEVICES =",
            "Door: {b_door}",
            "Wind: {b_window}",
            "Fan:  {b_fan}%",
            "Light:{light_lv}%",
        ],
    },
    {
        "title": "Safety",
        "lines": [
            "= SAFETY =",
            "Smoke:{smoke}",
            "Rain: {rain}",
            "PIR:  {motion}",
        ],
    },
    {
        "title": "Last Auto",
        "lines": [
            "= LAST AUTO =",
            "{recent_auto}",
        ],
    },
]

# v5 默认页（Home Mode 页读的是已拆除的引擎状态机占位符）。
# 磁盘上是这份说明用户没自定义过 → PAGES_VERSION=6 起自动替换。
DEFAULT_PAGES_V5: List[Dict[str, Any]] = [
    {"title": "Environment", "lines": ["= ENVIRONMENT =", "Temp: {temperature}C",
                                       "Hum:  {humidity}%", "Light:{light}"]},
    {"title": "Home Mode", "lines": ["= HOME MODE =", "Mode: {home_mode}",
                                     "Person:{presence}", "Fan:  {home_fan}",
                                     "Light:{home_light}"]},
    {"title": "Devices", "lines": ["= DEVICES =", "Door: {b_door}",
                                   "Wind: {b_window}", "Fan:  {b_fan}%",
                                   "Light:{light_lv}%"]},
    {"title": "Safety", "lines": ["= SAFETY =", "Smoke:{smoke}", "Rain: {rain}",
                                  "PIR:  {motion}"]},
    {"title": "Last Auto", "lines": ["= LAST AUTO =", "{recent_auto}"]},
]

# v4 默认页（已全英文，但全屋模式页还没有 Person 行）。
# 磁盘上是这份说明用户没自定义过 → PAGES_VERSION=5 起自动替换。
DEFAULT_PAGES_V4: List[Dict[str, Any]] = [
    {"title": "Environment", "lines": ["= ENVIRONMENT =", "Temp: {temperature}C",
                                       "Hum:  {humidity}%", "Light:{light}"]},
    {"title": "Home Mode", "lines": ["= HOME MODE =", "Mode: {home_mode}",
                                      "Fan:  {home_fan}", "Light:{home_light}"]},
    {"title": "Devices", "lines": ["= DEVICES =", "Door: {b_door}",
                                    "Wind: {b_window}", "Fan:  {b_fan}%",
                                    "Light:{light_lv}%"]},
    {"title": "Safety", "lines": ["= SAFETY =", "Smoke:{smoke}", "Rain: {rain}",
                                   "PIR:  {motion}"]},
    {"title": "Last Auto", "lines": ["= LAST AUTO =", "{recent_auto}"]},
]

# v3 默认页（中文文案）。B 板字库显示不了汉字，PAGES_VERSION=4 起改成英文，
# 磁盘上仍是这份说明用户没自定义过 → 自动替换为英文默认页。
DEFAULT_PAGES_V3: List[Dict[str, Any]] = [
    {"title": "环境", "lines": ["【环境状态】", "当前温度：{temperature}度",
                                "当前湿度：{humidity}%", "当前光照：{light}"]},
    {"title": "全屋模式", "lines": ["【全屋模式】", "当前模式：{home_mode}",
                                    "风扇：{home_fan}", "灯光：{home_light}"]},
    {"title": "设备", "lines": ["【设备状态】", "门：{b_door}", "窗：{b_window}",
                                "风扇：{b_fan}%", "灯光：{light_lv}%"]},
    {"title": "安防", "lines": ["【安全状态】", "烟雾：{smoke}", "雨水：{rain}",
                                "人体：{motion}"]},
    {"title": "最近自动化", "lines": ["【最近自动化】", "{recent_auto}"]},
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
    return pages in (DEFAULT_PAGES_V5, DEFAULT_PAGES_V4, DEFAULT_PAGES_V3,
                     DEFAULT_PAGES_OLD, DEFAULT_PAGES_V0)


# 把状态值翻译成友好英文（open/closed、on/off、True/False 等）
_VALUE_LABELS = {
    "open": "OPEN", "closed": "SHUT", "opening": "OPENING", "closing": "CLOSING",
    "normal": "HALF45", "on": "ON", "off": "OFF", "true": "YES", "false": "NO",
}

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_NON_ASCII = re.compile(r"[^\x20-\x7e]")


def to_oled_text(text: Any, cols: int = 16) -> str:
    """裁剪成 B 板 OLED 能显示的文本（纯 ASCII，最多 16 列）。

    B 板字库 ``u8x8_font_chroma48medium8_r`` 只有 ASCII 字形，且固件
    ``showText`` 只取前 16 个字节：UTF-8 汉字会被硬切成半截字节，上屏就是
    花屏乱码。这里直接丢弃非 ASCII 字符并截断，保证任何数据源都不会把
    汉字送到屏上。
    """
    return _NON_ASCII.sub("", str(text))[:cols]


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
        """替换 {key} 占位符，统一用 _str 格式化；key 不存在则留空。

        结果再过一遍 to_oled_text：非 ASCII（汉字）丢弃 + 截断 16 列。
        """
        return to_oled_text(self._substitute(template))

    def format_plain(self, template: str) -> str:
        """同样的占位符替换，但不做 OLED 裁剪。

        HTTP 出站动作用它：正文可能是中文，也远超 16 列。
        """
        return self._substitute(template)

    def _substitute(self, template: str) -> str:
        def repl(m):
            key = m.group(1)
            return self._str(self._data[key]) if key in self._data else ""
        return _PLACEHOLDER.sub(repl, str(template))

    @staticmethod
    def _str(v: Any) -> str:
        if v is None:
            return "--"
        if isinstance(v, bool):
            return "YES" if v else "NO"
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
        rows = 8                       # 屏幕整屏行数
        rendered = [self.format_text(ln) for ln in lines]
        # 按「整屏 8 行」对账，而不是只对当前页的行对账：上一页比当前页多出来的行
        # 补成 ""，于是「清多余行」只在它真的从有内容变成空时才下发一次。
        #
        # 旧实现只把当前页的行记进 _last_lines，越界行永远读到 None（≠ ""），
        # 所以每次切页都把多余行重清一遍——实测每 5s 白发 3~7 条 oled 命令，
        # 白占 relay 与串口（用户命令被挤在后面）。
        prev = (self._last_lines + [""] * rows)[:rows]
        target = (rendered + [""] * rows)[:rows]
        for line_no in range(rows):
            if target[line_no] != prev[line_no]:
                self.emitter(line_no, target[line_no])
                time.sleep(self.line_delay)
        self._last_lines = target

    def _advance(self):
        self._page_idx = (self._page_idx + 1) % len(self.pages)

    def reset(self):
        """重置轮播计时（如数据大幅变化想立即刷新时调用）。"""
        self._next_switch = time.time() + self.interval