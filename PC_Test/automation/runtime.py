"""运行时解释器 —— 遍历 AST 执行。

职责:
    1. 维护状态上下文（A 板最新数据 + 用户变量）
    2. 计算条件表达式
    3. 执行等待（计时）、操作（映射为 B 板 JSON 命令）、状态设置
    4. 通过 "操作映射表" 把友好的动作名翻译成 Module B 命令

对外接口:
    Runtime(emitter)             — emitter 负责把 B 板命令发出去
    runtime.run(program)         — 执行整个脚本
    runtime.update_data(data)    — 更新 A 板传感器快照
    runtime.update_event(ev)     — 更新 A 板事件
"""

from typing import Any, Callable, Dict, Optional

from .parser import (
    Program, Rule, When, If, Wait, Do, SetState, Loop,
    Edge, Every, Timer,
    Literal, GetState, Cond, Not, And, Or,
)


# ==================== 操作映射 ====================
# 把 DSL 里友好的动作名（中英文、点号/冒号连接）映射成 Module B 的 JSON 命令。
# 键支持别名，值为 (cmd, action, 额外默认参数)。

# 动作名 -> 文本命令生成函数。
# 生成函数接收 args 字典（DSL 里 `执行 xxx(k=v, ...)` 的参数），返回 B 板文本命令字符串。
# 注意：B 板固件当前无法解析 JSON 命令（parse_error），因此统一降级为旧文本命令。

def _t_fixed(cmd):
    """无参文本命令。"""
    return lambda args: cmd


def _t_template(fmt, *keys, **defaults):
    """带参文本命令：fmt 为格式串，用 {key} 占位；keys 为必填参数名，defaults 为缺省值。"""
    def build(args):
        vals = dict(defaults)
        vals.update(args)
        return fmt.format(**vals)
    return build


ACTION_MAP: Dict[str, Callable[[Dict], str]] = {
    # 灯光
    "light.on": _t_fixed("B:LIGHT:ON"),
    "light.off": _t_fixed("B:LIGHT:OFF"),
    "light.red": _t_fixed("B:LIGHT:RED"),
    "light.green": _t_fixed("B:LIGHT:GREEN"),
    "light.blue": _t_fixed("B:LIGHT:BLUE"),
    "light.yellow": _t_fixed("B:LIGHT:YELLOW"),
    "light.purple": _t_fixed("B:LIGHT:PURPLE"),
    "light.cyan": _t_fixed("B:LIGHT:CYAN"),
    "light.white": _t_fixed("B:LIGHT:WHITE"),
    "开灯": _t_fixed("B:LIGHT:ON"),
    "关灯": _t_fixed("B:LIGHT:OFF"),
    "红灯": _t_fixed("B:LIGHT:RED"),
    "绿灯": _t_fixed("B:LIGHT:GREEN"),
    "蓝灯": _t_fixed("B:LIGHT:BLUE"),
    # 门
    "door.open": _t_fixed("B:DOOR:OPEN"),
    "door.close": _t_fixed("B:DOOR:CLOSE"),
    "开门": _t_fixed("B:DOOR:OPEN"),
    "关门": _t_fixed("B:DOOR:CLOSE"),
    # 窗
    "window.open": _t_fixed("B:WINDOW:OPEN"),
    "window.close": _t_fixed("B:WINDOW:CLOSE"),
    "window.normal": _t_fixed("B:WINDOW:NORMAL"),
    "开窗": _t_fixed("B:WINDOW:OPEN"),
    "关窗": _t_fixed("B:WINDOW:CLOSE"),
    "窗正常": _t_fixed("B:WINDOW:NORMAL"),
    # 风扇
    "fan.on": _t_fixed("B:FAN:ON"),
    "fan.off": _t_fixed("B:FAN:OFF"),
    "fan.set": _t_template("B:FAN:{value}", value=255),
    "开风扇": _t_fixed("B:FAN:ON"),
    "关风扇": _t_fixed("B:FAN:OFF"),
    # 蜂鸣器
    "buzzer.on": _t_fixed("B:BUZZER:ON"),
    "buzzer.off": _t_fixed("B:BUZZER:OFF"),
    "buzzer.beep": _t_template("B:BUZZER:BEEP:{count}:{on_ms}:{off_ms}",
                               count=1, on_ms=200, off_ms=200),
    "蜂鸣": _t_template("B:BUZZER:BEEP:{count}:{on_ms}:{off_ms}",
                        count=1, on_ms=200, off_ms=200),
    "蜂鸣器开": _t_fixed("B:BUZZER:ON"),
    "蜂鸣器关": _t_fixed("B:BUZZER:OFF"),
    "蜂鸣器.开": _t_fixed("B:BUZZER:ON"),
    "蜂鸣器.关": _t_fixed("B:BUZZER:OFF"),
    "蜂鸣器.beep": _t_template("B:BUZZER:BEEP:{count}:{on_ms}:{off_ms}",
                               count=1, on_ms=200, off_ms=200),
    # 显示
    "oled.text": _t_template("B:OLED:SHOW:{line}:{text}", line=0, text=""),
    "oled.clear": _t_fixed("B:OLED:CLEAR"),
    "display.time": _t_template("B:TIME:{hour}{minute}", hour="", minute=""),
    "display.number": _t_template("B:OLED:SHOW:0:{value}", value=""),
    "display.clear": _t_fixed("B:OLED:CLEAR"),
    # 红外（固件文本命令未暴露 send_nec，保留占位，实际会返回未知）
    "ir.send": _t_template("B:IR:{code}", code=0),
}


class Runtime:
    def __init__(self, emitter: Optional[Callable[[str], None]] = None,
                 on_log: Optional[Callable[[str], None]] = None):
        """
        emitter: 接收 B 板文本命令字符串的回调（发串口，如 "B:LIGHT:RED"）。
        on_log:  可选日志回调。
        """
        self.emitter = emitter or (lambda cmd: None)
        self.on_log = on_log or (lambda msg: None)

        # 状态上下文
        self.data: Dict[str, Any] = {}       # A 板传感器数据快照
        self.event: Dict[str, Any] = {}      # A 板最近一次事件
        self.vars: Dict[str, Any] = {}       # 用户变量（set 语句）

        # 边沿去重：记录各字段上一次的布尔值（None 表示尚未采样）
        self._edge_state: Dict[str, bool] = {}

        # 定时器：周期定时器记录"下次触发时刻"；一次性定时器记录"到期时刻"
        self._every_state: Dict[int, float] = {}
        self._timer_state: Dict[int, float] = {}
        self._timer_fired: Dict[int, bool] = {}

    # ---- 外部更新接口 ----
    def update_data(self, data: Dict[str, Any]):
        self.data = data or {}

    def update_event(self, ev: Dict[str, Any]):
        self.event = ev or {}

    def now(self) -> float:
        import time
        return time.time()

    # ---- 执行入口 ----
    def run(self, program: Program):
        for rule in program.rules:
            self._log(f"[规则] {rule.name}")
            self._exec_block(rule.body)

    # ---- 语句块 ----
    def _exec_block(self, stmts):
        for stmt in stmts:
            self._exec(stmt)

    def _exec(self, stmt):
        if isinstance(stmt, When):
            self._exec_when(stmt)
        elif isinstance(stmt, If):
            self._exec_if(stmt)
        elif isinstance(stmt, Wait):
            self._exec_wait(stmt)
        elif isinstance(stmt, Do):
            self._exec_do(stmt)
        elif isinstance(stmt, SetState):
            self._exec_set(stmt)
        elif isinstance(stmt, Loop):
            self._exec_loop(stmt)
        elif isinstance(stmt, Edge):
            self._exec_edge(stmt)
        elif isinstance(stmt, Every):
            self._exec_every(stmt)
        elif isinstance(stmt, Timer):
            self._exec_timer(stmt)
        else:
            raise RuntimeError(f"未知语句: {stmt!r}")

    def _exec_when(self, stmt: When):
        if self._eval_bool(stmt.cond):
            self._exec_block(stmt.body)

    def _exec_if(self, stmt: If):
        if self._eval_bool(stmt.cond):
            self._exec_block(stmt.body)
        else:
            self._exec_block(stmt.else_body)

    def _exec_wait(self, stmt: Wait):
        import time
        self._log(f"  等待 {stmt.seconds:.2f} 秒...")
        time.sleep(stmt.seconds)

    def _exec_set(self, stmt: SetState):
        # stmt.value 是 _parse_value 解析出的原生值（非 AST 节点）
        self.vars[stmt.name] = stmt.value
        self._log(f"  设置 {stmt.name} = {self.vars[stmt.name]!r}")

    def _exec_loop(self, stmt: Loop):
        for i in range(stmt.count):
            self._exec_block(stmt.body)

    def _exec_edge(self, stmt: Edge):
        """边沿触发：字段值发生指定变化时才执行 body（去重）。

        - 上升沿(rising=True)：上一次为假/未采样，本次为真 -> 触发
        - 下降沿(rising=False)：上一次为真，本次为假 -> 触发
        触发后更新内部记录，避免下一次轮询重复触发。
        """
        # key 需区分方向，避免上升沿/下降沿语句共享同一状态互相覆盖
        key = f"{stmt.path}#{'rise' if stmt.rising else 'fall'}"
        current = self._lookup(stmt.path)
        cur_bool = bool(current)
        prev = self._edge_state.get(key)

        if stmt.rising:
            # 上升沿：当前为真，且之前不是真
            fired = cur_bool and prev is not True
        else:
            # 下降沿：当前为假，且之前是真
            fired = (not cur_bool) and prev is True

        # 无论是否触发，都更新内部状态（记录最新布尔值）
        self._edge_state[key] = cur_bool

        if fired:
            direction = "上升" if stmt.rising else "下降"
            self._log(f"  [边沿·{direction}] {key} = {cur_bool}")
            self._exec_block(stmt.body)

    def _exec_every(self, stmt: Every):
        """周期定时器：距离上次执行已过 N 秒则执行一次。"""
        key = id(stmt)
        now = self.now()
        last = self._every_state.get(key)
        if last is None or now - last >= stmt.seconds:
            self._every_state[key] = now
            self._log(f"  [定时·每 {stmt.seconds:.2f} 秒]")
            self._exec_block(stmt.body)

    def _exec_timer(self, stmt: Timer):
        """一次性定时器：首次执行时记录到期时刻，之后到期触发一次。"""
        key = id(stmt)
        now = self.now()
        if key not in self._timer_state:
            # 首次：登记到期时刻
            self._timer_state[key] = now + stmt.seconds
            self._timer_fired[key] = False
            self._log(f"  [定时] 已启动，{stmt.seconds:.2f} 秒后触发")
            return
        if not self._timer_fired[key] and now >= self._timer_state[key]:
            self._timer_fired[key] = True
            self._log(f"  [定时] 触发")
            self._exec_block(stmt.body)

    def _exec_do(self, stmt: Do):
        action = stmt.action
        builder = ACTION_MAP.get(action)
        if builder is None:
            self._log(f"  [未知动作] {action}")
            return
        cmd = builder(stmt.args)
        self._log(f"  [执行] {cmd}")
        self.emitter(cmd)

    # ---- 表达式求值 ----
    def _eval(self, node) -> Any:
        if isinstance(node, Literal):
            return node.value
        if isinstance(node, GetState):
            return self._lookup(node.name)
        if isinstance(node, Not):
            return not self._eval_bool(node.expr)
        if isinstance(node, And):
            return self._eval_bool(node.left) and self._eval_bool(node.right)
        if isinstance(node, Or):
            return self._eval_bool(node.left) or self._eval_bool(node.right)
        if isinstance(node, Cond):
            left = self._eval(node.left)
            right = self._eval(node.right)
            return self._compare(node.op, left, right)
        raise RuntimeError(f"未知表达式: {node!r}")

    def _eval_bool(self, node) -> bool:
        return bool(self._eval(node))

    def _lookup(self, path: str) -> Any:
        """按 a.b.c 路径从 data / event / vars 取值。"""
        # 先查用户变量（最高优先级）
        if path in self.vars:
            return self.vars[path]
        # 再查 data.* 与 event.*
        root = self.data
        if path.startswith("data."):
            root = self.data
            keys = path.split(".")[1:]
        elif path.startswith("event."):
            root = self.event
            keys = path.split(".")[1:]
        else:
            # 无前缀：先 data 再 event 再顶层
            keys = path.split(".")
            cur = self._descend(self.data, keys)
            if cur is not None:
                return cur
            cur = self._descend(self.event, keys)
            if cur is not None:
                return cur
            return None
        return self._descend(root, keys)

    @staticmethod
    def _descend(obj, keys):
        cur = obj
        for k in keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return None
        return cur

    @staticmethod
    def _compare(op, left, right) -> bool:
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        # 数值比较：两边都转 float，失败则字符串比较
        try:
            l, r = float(left), float(right)
        except (TypeError, ValueError):
            l, r = left, right
        if op == ">":
            return l > r
        if op == ">=":
            return l >= r
        if op == "<":
            return l < r
        if op == "<=":
            return l <= r
        raise RuntimeError(f"未知比较操作符: {op}")

    def _log(self, msg):
        self.on_log(msg)


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)
