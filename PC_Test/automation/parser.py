"""语法解析器 —— 递归下降，把 Token 流解析成 AST。

AST 节点（dataclass）:
    Program(rules)
    Rule(name, body)
    When(cond, body)
    If(cond, body, else_body)
    Wait(seconds)
    Do(action)                # 操作（映射到 B 板命令）
    SetState(name, value)     # 设置本地状态变量
    Loop(count, body)
    GetState(name)            # 读取状态变量（表达式）

表达式节点:
    Cond(op, left, right)     # left op right
    Not(expr) / And(l, r) / Or(l, r)
    Literal(value)
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional

from .lexer import Lexer, Token, LexError


class ParseError(Exception):
    pass


# ==================== AST 节点 ====================

@dataclass
class Literal:
    value: Any


@dataclass
class GetState:
    name: str


@dataclass
class Cond:
    op: str
    left: Any
    right: Any


@dataclass
class Not:
    expr: Any


@dataclass
class And:
    left: Any
    right: Any


@dataclass
class Or:
    left: Any
    right: Any


@dataclass
class Wait:
    seconds: float


@dataclass
class Do:
    action: str
    args: dict = field(default_factory=dict)


@dataclass
class SetState:
    name: str
    value: Any


@dataclass
class If:
    cond: Any
    body: List[Any]
    else_body: List[Any] = field(default_factory=list)


@dataclass
class When:
    cond: Any
    body: List[Any]


@dataclass
class Loop:
    count: int
    body: List[Any]


@dataclass
class Edge:
    """边沿触发：字段从 false->true（或 true->false）时执行一次。"""
    path: str
    body: List[Any]
    rising: bool = True          # True=上升沿(变真)，False=下降沿(变假)


@dataclass
class Every:
    """周期定时器：每 N 秒执行一次。"""
    seconds: float
    body: List[Any]


@dataclass
class Timer:
    """一次性定时器：启动后 N 秒执行一次。"""
    seconds: float
    body: List[Any]


@dataclass
class Rule:
    name: str
    body: List[Any]


@dataclass
class Program:
    rules: List[Rule]


class Parser:
    def __init__(self, text: str):
        self.tokens = Lexer(text).tokenize()
        self.pos = 0

    # ---- 工具 ----
    def _peek(self, offset: int = 0) -> Token:
        i = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[i]

    def _advance(self) -> Token:
        tok = self._peek()
        self.pos += 1
        return tok

    def _expect(self, ttype: str, value: Optional[str] = None) -> Token:
        tok = self._peek()
        if tok.type != ttype or (value is not None and tok.value != value):
            got = f"{tok.type}:{tok.value!r}"
            raise ParseError(
                f"[{tok.line}:{tok.col}] 期望 {ttype}" +
                (f"({value!r})" if value else "") + f"，但得到 {got}")
        return self._advance()

    def _match(self, ttype: str, value: Optional[str] = None) -> Optional[Token]:
        tok = self._peek()
        if tok.type == ttype and (value is None or tok.value == value):
            return self._advance()
        return None

    # ---- 顶层 ----
    def parse(self) -> Program:
        rules = []
        while self._peek().type != "EOF":
            rules.append(self._parse_rule())
        return Program(rules)

    def _parse_rule(self) -> Rule:
        self._expect("RULE")
        name_tok = self._expect("STRING")
        self._expect("OP", "{")
        body = self._parse_block("}")
        self._expect("OP", "}")
        return Rule(name_tok.value, body)

    # ---- 语句块 ----
    def _parse_block(self, terminator: str) -> List[Any]:
        stmts = []
        while self._peek().type != "EOF" and not (
                self._peek().type == "OP" and self._peek().value == terminator):
            stmts.append(self._parse_statement())
        return stmts

    def _parse_statement(self) -> Any:
        tok = self._peek()

        if tok.type == "WHEN":
            self._advance()
            cond = self._parse_expr()
            self._expect("OP", "{")
            body = self._parse_block("}")
            self._expect("OP", "}")
            return When(cond, body)

        if tok.type == "IF":
            self._advance()
            cond = self._parse_expr()
            self._expect("OP", "{")
            body = self._parse_block("}")
            self._expect("OP", "}")
            else_body = []
            if self._match("ELSE"):
                if self._match("IF"):  # 支持 else if
                    # 简化处理：else if 折叠成嵌套 If
                    inner = self._parse_statement()
                    else_body = [inner]
                else:
                    self._expect("OP", "{")
                    else_body = self._parse_block("}")
                    self._expect("OP", "}")
            return If(cond, body, else_body)

        if tok.type == "WAIT":
            self._advance()
            seconds = self._parse_duration()
            return Wait(seconds)

        if tok.type == "DO":
            self._advance()
            return self._parse_action()

        if tok.type == "SET":
            self._advance()
            name = self._expect("IDENT").value
            self._expect("OP", "=")
            value = self._parse_value()
            return SetState(name, value)

        if tok.type == "LOOP":
            self._advance()
            count = self._expect("NUMBER").value
            self._expect("OP", "{")
            body = self._parse_block("}")
            self._expect("OP", "}")
            return Loop(int(count), body)

        if tok.type == "EDGE":
            self._advance()
            rising = True
            # 可选方向: 边沿 下降 / 边沿 上升（默认上升沿）
            if self._peek().type == "IDENT":
                direction = self._peek().value
                if direction in ("下降", "降", "falling", "fall"):
                    rising = False
                    self._advance()
                elif direction in ("上升", "升", "rising", "rise"):
                    rising = True
                    self._advance()
            # 字段路径: 可选 "当" 前缀
            self._match("WHEN")
            path = self._parse_path()
            self._expect("OP", "{")
            body = self._parse_block("}")
            self._expect("OP", "}")
            return Edge(path, body, rising)

        if tok.type == "EVERY":
            self._advance()
            seconds = self._parse_duration()
            self._expect("OP", "{")
            body = self._parse_block("}")
            self._expect("OP", "}")
            return Every(seconds, body)

        if tok.type == "TIMER":
            self._advance()
            seconds = self._parse_duration()
            self._expect("OP", "{")
            body = self._parse_block("}")
            self._expect("OP", "}")
            return Timer(seconds, body)

        raise ParseError(f"[{tok.line}:{tok.col}] 无法识别的语句: {tok.value!r}")

    def _parse_path(self) -> str:
        """解析 a.b.c 形式的路径，返回字符串。"""
        parts = [self._expect("IDENT").value]
        while self._match("OP", "."):
            parts.append(self._expect("IDENT").value)
        return ".".join(parts)

    def _parse_action(self) -> Do:
        # 动作名：标识符或字符串，支持 点号/冒号 连接（如 light.red / 蜂鸣器.开）
        parts = []
        while True:
            tok = self._peek()
            if tok.type in ("IDENT", "STRING"):
                parts.append(self._advance().value)
            elif tok.type == "OP" and tok.value in (".", ":"):
                self._advance()
            else:
                break
        if not parts:
            tok = self._peek()
            raise ParseError(f"[{tok.line}:{tok.col}] 执行后缺少动作名")

        action = ".".join(parts)
        args = {}

        # 可选参数列表: (key=value, ...)
        if self._match("OP", "("):
            if not (self._peek().type == "OP" and self._peek().value == ")"):
                while True:
                    key = self._expect("IDENT").value
                    self._expect("OP", "=")
                    args[key] = self._parse_value()
                    if not self._match("OP", ","):
                        break
            self._expect("OP", ")")

        return Do(action, args)

    def _parse_duration(self) -> float:
        tok = self._peek()
        # 形式: 2 秒 | 2秒 | 500 毫秒 | 1.5 分钟 | 3 (默认秒)
        if tok.type == "NUMBER":
            num = float(self._advance().value)
            nxt = self._peek()
            if nxt.type == "IDENT" and nxt.value in ("秒", "毫秒", "分钟", "小时",
                                                      "s", "ms", "min", "h"):
                unit = self._advance().value
                from .lexer import UNITS
                return num * UNITS[unit]
            return num  # 默认秒
        raise ParseError(f"[{tok.line}:{tok.col}] 期望时间数值")

    # ---- 表达式 ----
    def _parse_expr(self) -> Any:
        return self._parse_or()

    def _parse_or(self) -> Any:
        left = self._parse_and()
        while self._match("OP", "||"):
            right = self._parse_and()
            left = Or(left, right)
        return left

    def _parse_and(self) -> Any:
        left = self._parse_not()
        while self._match("OP", "&&"):
            right = self._parse_not()
            left = And(left, right)
        return left

    def _parse_not(self) -> Any:
        if self._match("OP", "!"):
            return Not(self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self) -> Any:
        left = self._parse_atom()
        tok = self._peek()
        if tok.type == "OP" and tok.value in ("==", "!=", ">", ">=", "<", "<="):
            op = self._advance().value
            right = self._parse_atom()
            return Cond(op, left, right)
        return left

    def _parse_atom(self) -> Any:
        tok = self._peek()

        if tok.type == "NUMBER":
            self._advance()
            num = tok.value
            return Literal(float(num) if "." in num else int(num))

        if tok.type == "STRING":
            self._advance()
            return Literal(tok.value)

        if tok.type == "TRUE":
            self._advance()
            return Literal(True)

        if tok.type == "FALSE":
            self._advance()
            return Literal(False)

        if tok.type == "IDENT":
            self._advance()
            # 支持点号路径，如 data.temperature
            path = tok.value
            while self._match("OP", "."):
                path += "." + self._expect("IDENT").value
            return GetState(path)

        if tok.type == "OP" and tok.value == "(":
            self._advance()
            expr = self._parse_expr()
            self._expect("OP", ")")
            return expr

        raise ParseError(f"[{tok.line}:{tok.col}] 无法识别的表达式: {tok.value!r}")

    def _parse_value(self) -> Any:
        # 用于参数值 / 设置语句的值
        tok = self._peek()
        if tok.type == "NUMBER":
            self._advance()
            num = tok.value
            return float(num) if "." in num else int(num)
        if tok.type == "STRING":
            self._advance()
            return tok.value
        if tok.type == "TRUE":
            self._advance()
            return True
        if tok.type == "FALSE":
            self._advance()
            return False
        raise ParseError(f"[{tok.line}:{tok.col}] 无法识别的值: {tok.value!r}")


def parse(text: str) -> Program:
    return Parser(text).parse()
