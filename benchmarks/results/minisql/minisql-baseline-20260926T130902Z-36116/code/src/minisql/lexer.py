from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import SQLError


@dataclass
class Token:
    kind: str  # 'IDENT', 'NUMBER', 'STRING', 'OP', 'EOF'
    value: object
    pos: int


_KEYWORDS = {
    "select", "distinct", "from", "as", "where", "group", "by", "having",
    "order", "asc", "desc", "limit", "offset", "join", "inner", "left",
    "outer", "on", "and", "or", "not", "is", "null", "in", "between",
    "like", "insert", "into", "values", "update", "set", "delete",
    "create", "table", "integer", "real", "text", "true", "false",
}

_TOKEN_RE = re.compile(
    r"""
    (?P<WS>\s+)
  | (?P<COMMENT>--[^\n]*)
  | (?P<NUMBER>\d+\.\d+(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)
  | (?P<STRING>'(?:[^']|'')*')
  | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<OP><=|>=|<>|!=|==|\|\||[(),.*+\-/%=<>])
    """,
    re.VERBOSE,
)


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    length = len(sql)
    while pos < length:
        m = _TOKEN_RE.match(sql, pos)
        if not m:
            raise SQLError(f"Unexpected character at position {pos}: {sql[pos]!r}")
        kind = m.lastgroup
        text = m.group()
        pos = m.end()
        if kind in ("WS", "COMMENT"):
            continue
        if kind == "NUMBER":
            if any(c in text for c in ".eE"):
                tokens.append(Token("NUMBER", float(text), m.start()))
            else:
                tokens.append(Token("NUMBER", int(text), m.start()))
        elif kind == "STRING":
            inner = text[1:-1].replace("''", "'")
            tokens.append(Token("STRING", inner, m.start()))
        elif kind == "IDENT":
            lower = text.lower()
            if lower in _KEYWORDS:
                tokens.append(Token("KEYWORD", lower, m.start()))
            else:
                tokens.append(Token("IDENT", text, m.start()))
        elif kind == "OP":
            tokens.append(Token("OP", text, m.start()))
        else:
            raise SQLError(f"Unexpected token at position {pos}")
    tokens.append(Token("EOF", None, length))
    return tokens
