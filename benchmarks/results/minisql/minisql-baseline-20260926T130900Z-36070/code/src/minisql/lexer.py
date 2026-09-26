from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import SQLError

KEYWORDS = {
    "select", "from", "where", "insert", "into", "values", "update", "set",
    "delete", "create", "table", "join", "inner", "left", "outer", "on",
    "as", "and", "or", "not", "null", "is", "in", "between", "like",
    "distinct", "group", "by", "having", "order", "asc", "desc", "limit",
    "offset", "integer", "real", "text", "count", "sum", "avg", "min", "max",
    "true", "false",
}

# Multi-character operators must be listed before their single-char prefixes.
_OPERATORS = [
    "==", "!=", "<>", "<=", ">=", "||",
    "=", "<", ">", "+", "-", "*", "/", "%", "(", ")", ",", ".",
]

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
    |(?P<real>\d+\.\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)
    |(?P<integer>\d+)
    |(?P<string>'(?:[^']|'')*')
    |(?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    |(?P<op>==|!=|<>|<=|>=|\|\||[=<>+\-*/%(),.;])
    """,
    re.VERBOSE,
)


@dataclass
class Token:
    kind: str  # 'keyword', 'ident', 'integer', 'real', 'string', 'op', 'eof'
    value: str
    pos: int


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    n = len(sql)
    while pos < n:
        m = _TOKEN_RE.match(sql, pos)
        if not m:
            raise SQLError(f"Unexpected character {sql[pos]!r} at position {pos}")
        pos = m.end()
        if m.lastgroup == "ws":
            continue
        kind = m.lastgroup
        text = m.group()
        if kind == "ident":
            low = text.lower()
            if low in KEYWORDS:
                tokens.append(Token("keyword", low, m.start()))
            else:
                tokens.append(Token("ident", text, m.start()))
        elif kind == "string":
            value = text[1:-1].replace("''", "'")
            tokens.append(Token("string", value, m.start()))
        elif kind == "op":
            tokens.append(Token("op", text, m.start()))
        elif kind == "integer":
            tokens.append(Token("integer", text, m.start()))
        elif kind == "real":
            tokens.append(Token("real", text, m.start()))
    tokens.append(Token("eof", "", n))
    return tokens
