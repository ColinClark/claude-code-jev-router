"""SQL tokenizer."""

from __future__ import annotations

import re
from dataclasses import dataclass

from minisql.errors import SQLError

# Token kinds
IDENT = "ident"  # bare identifier or keyword (case-insensitive)
QIDENT = "qident"  # "quoted identifier" (never a keyword)
INT = "int"
REAL = "real"
STRING = "string"
OP = "op"
EOF = "eof"


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    pos: int

    def is_kw(self, *words: str) -> bool:
        return self.kind == IDENT and str(self.value).upper() in words

    def is_op(self, *ops: str) -> bool:
        return self.kind == OP and self.value in ops


_OPERATORS = ("||", "<=", ">=", "<>", "!=", "==", "=", "<", ">", "+", "-", "*", "/", "%",
              "(", ")", ",", ".", ";")

_NUMBER_RE = re.compile(r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
            continue
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end + 1
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end < 0:
                raise SQLError("unterminated block comment")
            i = end + 2
            continue
        if ch == "'":
            j = i + 1
            parts: list[str] = []
            while True:
                k = sql.find("'", j)
                if k < 0:
                    raise SQLError("unterminated string literal")
                parts.append(sql[j:k])
                if k + 1 < n and sql[k + 1] == "'":
                    parts.append("'")
                    j = k + 2
                    continue
                j = k + 1
                break
            tokens.append(Token(STRING, "".join(parts), i))
            i = j
            continue
        if ch == '"':
            j = i + 1
            parts = []
            while True:
                k = sql.find('"', j)
                if k < 0:
                    raise SQLError("unterminated quoted identifier")
                parts.append(sql[j:k])
                if k + 1 < n and sql[k + 1] == '"':
                    parts.append('"')
                    j = k + 2
                    continue
                j = k + 1
                break
            tokens.append(Token(QIDENT, "".join(parts), i))
            i = j
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and sql[i + 1].isdigit()):
            m = _NUMBER_RE.match(sql, i)
            assert m is not None
            text = m.group(0)
            if "." in text or "e" in text or "E" in text:
                tokens.append(Token(REAL, float(text), i))
            else:
                tokens.append(Token(INT, int(text), i))
            i = m.end()
            if i < n and (sql[i].isalnum() or sql[i] == "_"):
                raise SQLError(f"unrecognized token near {sql[i - len(text):i + 1]!r}")
            continue
        m = _IDENT_RE.match(sql, i)
        if m:
            tokens.append(Token(IDENT, m.group(0), i))
            i = m.end()
            continue
        for op in _OPERATORS:
            if sql.startswith(op, i):
                tokens.append(Token(OP, op, i))
                i += len(op)
                break
        else:
            raise SQLError(f"unrecognized token {ch!r} at position {i}")
    tokens.append(Token(EOF, None, n))
    return tokens
