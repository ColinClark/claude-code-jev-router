"""Tokenizer for the supported SQL dialect."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SQLError
from .values import INT64_MAX

KEYWORDS = frozenset(
    """
    ALL AND AS ASC BETWEEN BY CASE CAST CREATE CROSS DELETE DESC DISTINCT DROP ELSE END ESCAPE
    EXCEPT EXISTS FROM FULL GROUP HAVING IF IN INNER INSERT INTERSECT INTO IS ISNULL JOIN LEFT
    LIKE LIMIT NATURAL NOT NOTNULL NULL OFFSET ON OR ORDER OUTER RIGHT SELECT SET TABLE THEN
    UNION UPDATE USING VALUES WHEN WHERE
    """.split()
)

# Longest operators first so that e.g. "<=" wins over "<".
_OPERATORS = ("||", "<=", ">=", "<>", "!=", "==", "(", ")", ",", ".", ";", "*", "+", "-",
              "/", "%", "=", "<", ">")


_DIGITS = frozenset("0123456789")


@dataclass(slots=True)
class Token:
    kind: str  # "kw", "ident", "int", "float", "str", "op", "eof"
    value: object
    pos: int

    def __repr__(self) -> str:
        return f"Token({self.kind}, {self.value!r})"


def _is_ident_start(c: str) -> bool:
    return c.isalpha() or c == "_" or ord(c) > 127


def _is_ident_char(c: str) -> bool:
    return c.isalnum() or c in "_$" or ord(c) > 127


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
        start = i
        if c == "'":
            parts = []
            i += 1
            while True:
                j = sql.find("'", i)
                if j < 0:
                    raise SQLError(f"unrecognized token: {sql[start:]!r}")
                parts.append(sql[i:j])
                if j + 1 < n and sql[j + 1] == "'":
                    parts.append("'")
                    i = j + 2
                    continue
                i = j + 1
                break
            tokens.append(Token("str", "".join(parts), start))
            continue
        if c in "\"`[":
            close = {'"': '"', "`": "`", "[": "]"}[c]
            parts = []
            i += 1
            while True:
                j = sql.find(close, i)
                if j < 0:
                    raise SQLError(f"unrecognized token: {sql[start:]!r}")
                parts.append(sql[i:j])
                if close != "]" and j + 1 < n and sql[j + 1] == close:
                    parts.append(close)
                    i = j + 2
                    continue
                i = j + 1
                break
            tokens.append(Token("ident", "".join(parts), start))
            continue
        if c in _DIGITS or (c == "." and i + 1 < n and sql[i + 1] in _DIGITS):
            i = _lex_number(sql, i, tokens)
            continue
        if _is_ident_start(c):
            while i < n and _is_ident_char(sql[i]):
                i += 1
            word = sql[start:i]
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token("kw", upper, start))
            else:
                tokens.append(Token("ident", word, start))
            continue
        for op in _OPERATORS:
            if sql.startswith(op, i):
                tokens.append(Token("op", op, start))
                i += len(op)
                break
        else:
            raise SQLError(f"unrecognized token: {c!r}")
    tokens.append(Token("eof", None, n))
    return tokens


def _lex_number(sql: str, i: int, tokens: list[Token]) -> int:
    n = len(sql)
    start = i
    if sql.startswith(("0x", "0X"), i) and i + 2 < n and sql[i + 2] in "0123456789abcdefABCDEF":
        i += 2
        while i < n and sql[i] in "0123456789abcdefABCDEF":
            i += 1
        if i < n and _is_ident_char(sql[i]):
            raise SQLError(f"unrecognized token: {sql[start:i + 1]!r}")
        value = int(sql[start + 2 : i], 16)
        if value > 0xFFFFFFFFFFFFFFFF:
            raise SQLError(f"hex literal too big: {sql[start:i]}")
        if value > INT64_MAX:
            value -= 1 << 64
        tokens.append(Token("int", value, start))
        return i
    is_float = False
    while i < n and sql[i] in _DIGITS:
        i += 1
    if i < n and sql[i] == ".":
        is_float = True
        i += 1
        while i < n and sql[i] in _DIGITS:
            i += 1
    if i < n and sql[i] in "eE":
        j = i + 1
        if j < n and sql[j] in "+-":
            j += 1
        if j < n and sql[j] in _DIGITS:
            is_float = True
            i = j
            while i < n and sql[i] in _DIGITS:
                i += 1
        else:
            raise SQLError(f"unrecognized token: {sql[start:j]!r}")
    if i < n and _is_ident_char(sql[i]):
        raise SQLError(f"unrecognized token: {sql[start:i + 1]!r}")
    text = sql[start:i]
    if is_float:
        tokens.append(Token("float", float(text), start))
    else:
        value = int(text)
        if value > INT64_MAX + 1:
            tokens.append(Token("float", float(value), start))
        else:
            tokens.append(Token("int", value, start))
    return i
