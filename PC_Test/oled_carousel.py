"""OLED 多行轮播显示 —— 按时间间隔轮换显示传感器/执行器状态。

设计:
    - OLED 有 8 行(0~7)，每行 16 字符。
    - 把显示内容组织成多个"页面"，每页是一组多行文本（可含占位符）。
    - 按固定间隔切换到下一页，循环轮播。
    - 占位符从统一的数据源取值（A 板 data + B 板 state + 用户变量）。

用法示例:
    from oled_carousel import OledCarousel

    carousel = OledCarousel(
        pages=[
            {"title": "环境", "lines": [
                "T:{temperature}C H:{humidity}%",
                "光:{light} 距离:{distance}",
            ]},
            {"title": "安防", "lines": [
                "烟:{smoke} 雨:{rain}",
                "人:{motion} 土:{soil_dry}",
            ]},
            {"title": "执行器", "lines": [
                "门:{door} 窗:{window}",
                "扇:{fan} 灯:{light_lv}",
            ]},
        ],
        interval=3.0,          # 每页停留秒数
        emitter=send_oled,     # 发 OLED 命令的回调
    )

    carousel.set_data(a_data, b_state)   # 更新数据源
    carousel.tick()                       # 在循环里调用，自动轮播
"""

import time
from typing import Any, Callable, Dict, List, Optional


# 默认页面模板（覆盖常见传感器 + 执行器状态）
DEFAULT_PAGES: List[Dict[str, Any]] = [
    {
        "title": "环境",
        "lines": [
            "温度 {temperature}C",
            "湿度 {humidity}%",
            "光 {light}",
        ],
    },
    {
        "title": "安防",
        "lines": [
            "烟 {smoke} 雨 {rain}",
            "人 {motion} 距 {distance}",
            "土 {soil_dry}",
        ],
    },
    {
        "title": "执行器",
        "lines": [
            "门 {b_door} 窗 {b_window}",
            "扇 {b_fan} 灯 {light_lv}",
            "蜂 {b_buzzer}",
        ],
    },
]


class OledCarousel:
    def __init__(
        self,
        emitter: Callable[[int, str], None],
        pages: Optional[List[Dict[str, Any]]] = None,
        interval: float = 3.0,
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

        self._page_idx = 0
        self._next_switch = time.time()  # 首次 tick 立即显示第一页

        # 数据源（统一扁平字典，占位符键在此取值）
        self._data: Dict[str, Any] = {}
        # 记录上次渲染的每行文本，用于去重（OLED 驱动本身也去重，这里再优化）
        self._last_lines: List[str] = []

    # ---- 数据源 ----
    def set_data(self, a_data: Optional[Dict], b_state: Optional[Dict]):
        """更新数据源。a_data=A板周期数据，b_state=B板状态。

        字段冲突处理：B 板字段默认加 b_ 前缀（如 b_door、b_fan），
        同时保留无前缀别名（仅当不与 A 板字段冲突时）。
        特例：B 板 light(灯光亮度) 用 light_lv 表示，避免与 A 板光敏 light 冲突。
        """
        d: Dict[str, Any] = {}
        if a_data:
            d.update(a_data)
        if b_state:
            for k, v in b_state.items():
                # 若与 A 板字段冲突，仅保留 b_ 前缀版本；否则同时保留无前缀别名
                if k not in d:
                    d[k] = v
                d["b_" + k] = v
            # 别名：B 板灯光亮度
            if "light" in b_state:
                d["light_lv"] = b_state["light"]
        self._data = d

    def update_var(self, name: str, value: Any):
        self._data[name] = value

    # ---- 格式化 ----
    def _fmt(self, template: str) -> str:
        """替换 {key} 占位符，统一用 _str 格式化；key 不存在则留空。"""
        import re
        def repl(m):
            key = m.group(1)
            if key in self._data:
                return self._str(self._data[key])
            return ""
        return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, template)

    @staticmethod
    def _str(v: Any) -> str:
        if v is None:
            return "--"
        if isinstance(v, bool):
            return "是" if v else "否"
        if isinstance(v, float):
            return f"{v:.1f}"
        return str(v)

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
        self.on_log(f"[OLED] 显示页: {page.get('title', self._page_idx)}")
        rendered = [self._fmt(l) for l in lines]
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
