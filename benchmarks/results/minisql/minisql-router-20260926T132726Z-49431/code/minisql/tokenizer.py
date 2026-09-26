"""SQL tokenizer."""

from __future__ import annotations

import re
from dataclasses import dataclass

from minisql.errors import SQLError
from minisql.values import INT_MAX

# Token kinds
NUM = "NUM"
STR = "STR"
ID = "ID"  # bare identifier or keyword
QID = "QID"  # quoted identifier (never a keyword)
OP = "OP"
EOF = "EOF"


@dataclass(slots=True)
class Token:
    kind: str
    value: object
    pos: int

    @property
    def upper(self) -> str:
        return self.value.upper() if self.kind == ID else ""


_NUMBER = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_IDENT = re.compile(r"[A-Za-z_\u0080-\U0010ffff][A-Za-z0-9_$\u0080-\U0010ffff]*")
_OPS2 = ("<>", "<=", ">=", "==", "!=", "||", "<<", ">>")
_OPS1 = "+-*/%=<>(),.;&|~"


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
            continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c.isdigit() or (c == "." and i + 1 < n and sql[i + 1].isdigit()):
            m = _NUMBER.match(sql, i)
            assert m is not None
            text = m.group(0)
            end = m.end()
            if end < n and (sql[end].isalnum() or sql[end] == "_"):
                raise SQLError(f'unrecognized token: "{sql[i:end + 1]}"')
            if "." in text or "e" in text or "E" in text:
                value: object = float(text)
            else:
                iv = int(text)
                value = float(text) if iv > INT_MAX else iv
            tokens.append(Token(NUM, value, i))
            i = end
            continue
        if c == "'":
            j = i + 1
            parts = []
            while True:
                k = sql.find("'", j)
                if k < 0:
                    raise SQLError(f"unrecognized token: \"{sql[i:]}\"")
                parts.append(sql[j:k])
                if k + 1 < n and sql[k + 1] == "'":
                    parts.append("'")
                    j = k + 2
                    continue
                i = k + 1
                break
            tokens.append(Token(STR, "".join(parts), i))
            continue
        if c in "\"`":
            j = i + 1
            parts = []
            while True:
                k = sql.find(c, j)
                if k < 0:
                    raise SQLError(f"unrecognized token: \"{sql[i:]}\"")
                parts.append(sql[j:k])
                if k + 1 < n and sql[k + 1] == c:
                    parts.append(c)
                    j = k + 2
                    continue
                start = i
                i = k + 1
                break
            tokens.append(Token(QID, "".join(parts), start))
            continue
        if c == "[":
            k = sql.find("]", i + 1)
            if k < 0:
                raise SQLError(f"unrecognized token: \"{sql[i:]}\"")
            tokens.append(Token(QID, sql[i + 1 : k], i))
            i = k + 1
            continue
        m = _IDENT.match(sql, i)
        if m:
            tokens.append(Token(ID, m.group(0), i))
            i = m.end()
            continue
        two = sql[i : i + 2]
        if two in _OPS2:
            tokens.append(Token(OP, two, i))
            i += 2
            continue
        if c in _OPS1:
            tokens.append(Token(OP, c, i))
            i += 1
            continue
        raise SQLError(f'unrecognized token: "{c}"')
    tokens.append(Token(EOF, None, n))
    return tokens
