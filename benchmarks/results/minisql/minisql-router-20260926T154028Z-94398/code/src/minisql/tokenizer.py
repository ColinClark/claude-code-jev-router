"""SQL tokenizer."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import SQLError

KEYWORDS = {
    "SELECT", "DISTINCT", "ALL", "FROM", "WHERE", "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC",
    "LIMIT", "OFFSET", "AS", "JOIN", "INNER", "LEFT", "OUTER", "CROSS", "ON", "AND", "OR", "NOT",
    "IS", "NULL", "IN", "BETWEEN", "LIKE", "CREATE", "TABLE", "INSERT", "INTO", "VALUES", "UPDATE",
    "SET", "DELETE", "CASE", "WHEN", "THEN", "ELSE", "END", "IF", "EXISTS", "DROP", "ISNULL",
    "NOTNULL",
}


@dataclass(slots=True)
class Token:
    kind: str  # KW, ID, INT, REAL, STR, OP, EOF
    value: object
    pos: int


_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+|--[^\n]*|/\*.*?\*/)
  | (?P<real>(\d+\.\d*|\.\d+)([eE][+-]?\d+)?|\d+[eE][+-]?\d+)
  | (?P<int>\d+)
  | (?P<str>'(?:[^']|'')*')
  | (?P<qid>"(?:[^"]|"")*"|`(?:[^`]|``)*`|\[[^\]]*\])
  | (?P<id>[A-Za-z_\x80-\U0010ffff][A-Za-z0-9_$\x80-\U0010ffff]*)
  | (?P<op>\|\||==|!=|<>|<=|>=|[-+*/%<>=(),.;])
    """,
    re.VERBOSE | re.DOTALL,
)


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    n = len(sql)
    while pos < n:
        m = _TOKEN_RE.match(sql, pos)
        if not m:
            raise SQLError(f"unrecognized token near {sql[pos:pos + 10]!r}")
        kind = m.lastgroup
        text = m.group(kind)
        if kind == "ws":
            pass
        elif kind == "real":
            tokens.append(Token("REAL", float(text), pos))
        elif kind == "int":
            tokens.append(Token("INT", int(text), pos))
        elif kind == "str":
            tokens.append(Token("STR", text[1:-1].replace("''", "'"), pos))
        elif kind == "qid":
            if text[0] == "[":
                name = text[1:-1]
            else:
                q = text[0]
                name = text[1:-1].replace(q + q, q)
            tokens.append(Token("ID", name, pos))
        elif kind == "id":
            upper = text.upper()
            if upper in KEYWORDS:
                tokens.append(Token("KW", upper, pos))
            else:
                tokens.append(Token("ID", text, pos))
        else:
            tokens.append(Token("OP", text, pos))
        pos = m.end()
    tokens.append(Token("EOF", None, n))
    return tokens
