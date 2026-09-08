"""词法分析器 —— 把脚本文本切成 Token 流。

Token 类型:
    RULE / WHEN / IF / ELSE / DO / WAIT / SET / STATE / LOOP
    IDENT / NUMBER / STRING / TRUE / FALSE
    操作符: == != > >= < <= && || ! = ( ) { } : , 等
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Token:
    type: str
    value: str
    line: int
    col: int

    def __repr__(self):
        return f"Token({self.type}, {self.value!r}, {self.line}:{self.col})"


# 关键字 -> token 类型
KEYWORDS = {
    "规则": "RULE",
    "rule": "RULE",
    "当": "WHEN",
    "when": "WHEN",
    "如果": "IF",
    "if": "IF",
    "否则": "ELSE",
    "else": "ELSE",
    "执行": "DO",
    "do": "DO",
    "等待": "WAIT",
    "wait": "WAIT",
    "设置": "SET",
    "set": "SET",
    "状态": "STATE",
    "state": "STATE",
    "循环": "LOOP",
    "loop": "LOOP",
    "真": "TRUE",
    "true": "TRUE",
    "假": "FALSE",
    "false": "FALSE",
    # 边沿 / 定时器
    "边沿": "EDGE",
    "edge": "EDGE",
    "每": "EVERY",
    "every": "EVERY",
    "定时": "TIMER",
    "timer": "TIMER",
}

# 双字符操作符
TWO_CHAR_OPS = {"==", "!=", ">=", "<=", "&&", "||"}

# 单字符操作符/分隔符
ONE_CHAR = set("!=><+-*/.(){}:,")

# 单位后缀（计时/数值）
UNITS = {
    "秒": 1.0, "s": 1.0,
    "毫秒": 0.001, "ms": 0.001,
    "分钟": 60.0, "min": 60.0,
    "小时": 3600.0, "h": 3600.0,
}


class LexError(Exception):
    def __init__(self, msg, line, col):
        super().__init__(f"[{line}:{col}] {msg}")
        self.line = line
        self.col = col


class Lexer:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.line = 1
        self.col = 1
        self.length = len(text)

    # ---- 基础 ----
    def _peek(self, offset: int = 0) -> str:
        i = self.pos + offset
        return self.text[i] if i < self.length else ""

    def _advance(self) -> str:
        ch = self.text[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _skip_ws_and_comments(self):
        while self.pos < self.length:
            ch = self._peek()
            if ch in " \t\r":
                self._advance()
            elif ch == "\n":
                self._advance()
            elif ch == "#" or (ch == "/" and self._peek(1) == "/"):
                # 注释到行尾
                while self.pos < self.length and self._peek() != "\n":
                    self._advance()
            else:
                break

    # ---- 主入口 ----
    def tokenize(self) -> List[Token]:
        tokens: List[Token] = []
        while True:
            self._skip_ws_and_comments()
            if self.pos >= self.length:
                tokens.append(Token("EOF", "", self.line, self.col))
                return tokens
            tokens.append(self._next_token())

    def _next_token(self) -> Token:
        line, col = self.line, self.col
        ch = self._peek()

        # 字符串
        if ch in "\"'":
            return self._read_string(line, col)

        # 数字（含小数）
        if ch.isdigit() or (ch == "." and self._peek(1).isdigit()):
            return self._read_number(line, col)

        # 标识符 / 关键字（中英文均可）
        if ch.isalpha() or ch == "_" or "\u4e00" <= ch <= "\u9fff":
            return self._read_ident(line, col)

        # 双字符操作符
        two = ch + self._peek(1)
        if two in TWO_CHAR_OPS:
            self._advance()
            self._advance()
            return Token("OP", two, line, col)

        # 单字符
        if ch in ONE_CHAR:
            self._advance()
            return Token("OP", ch, line, col)

        raise LexError(f"无法识别的字符: {ch!r}", line, col)

    # ---- 各类型读取 ----
    def _read_string(self, line, col) -> Token:
        quote = self._advance()
        buf = []
        while self.pos < self.length:
            ch = self._advance()
            if ch == quote:
                return Token("STRING", "".join(buf), line, col)
            if ch == "\\":
                nxt = self._advance()
                buf.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(nxt, nxt))
            else:
                buf.append(ch)
        raise LexError("字符串未闭合", line, col)

    def _read_number(self, line, col) -> Token:
        buf = []
        while self.pos < self.length:
            ch = self._peek()
            if ch.isdigit() or ch == ".":
                buf.append(self._advance())
            else:
                break
        return Token("NUMBER", "".join(buf), line, col)

    def _read_ident(self, line, col) -> Token:
        buf = []
        while self.pos < self.length:
            ch = self._peek()
            if ch.isalnum() or ch == "_" or "\u4e00" <= ch <= "\u9fff":
                buf.append(self._advance())
            else:
                break
        word = "".join(buf)
        ttype = KEYWORDS.get(word, "IDENT")
        return Token(ttype, word, line, col)
