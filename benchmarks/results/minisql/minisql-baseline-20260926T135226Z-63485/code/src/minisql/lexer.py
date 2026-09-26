"""Tokenizer for the minisql SQL dialect."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SQLError

KEYWORDS = frozenset(
    """
    ALL AND AS ASC BETWEEN BY CASE CAST CREATE CROSS DELETE DESC DISTINCT DROP ELSE END ESCAPE
    EXISTS FROM GROUP HAVING IF IN INNER INSERT INTO IS ISNULL JOIN LEFT LIKE LIMIT NOT NOTNULL
    NULL OFFSET ON OR ORDER OUTER SELECT SET TABLE THEN UPDATE VALUES WHEN WHERE
    """.split()
)

# Longest operators first so that e.g. "<=" wins over "<".
OPERATORS = (
    "||", "<=", ">=", "<>", "!=", "==",
    "=", "<", ">", "+", "-", "*", "/", "%", "(", ")", ",", ".", ";",
)

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


@dataclass(frozen=True, slots=True)
class Token:
    kind: str  # "NUM", "STR", "ID", "KW", "OP", "EOF"
    value: object
    pos: int


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
            i = n if end < 0 else end + 2
            continue
        if ch == "'":
            j = i + 1
            parts = []
            while True:
                k = sql.find("'", j)
                if k < 0:
                    raise SQLError(f"unrecognized token: {sql[i:]!r}")
                parts.append(sql[j:k])
                if k + 1 < n and sql[k + 1] == "'":
                    parts.append("'")
                    j = k + 2
                    continue
                j = k + 1
                break
            tokens.append(Token("STR", "".join(parts), i))
            i = j
            continue
        if ch in "\"`[":
            close = {"\"": "\"", "`": "`", "[": "]"}[ch]
            j = i + 1
            parts = []
            while True:
                k = sql.find(close, j)
                if k < 0:
                    raise SQLError(f"unrecognized token: {sql[i:]!r}")
                parts.append(sql[j:k])
                if close != "]" and k + 1 < n and sql[k + 1] == close:
                    parts.append(close)
                    j = k + 2
                    continue
                j = k + 1
                break
            tokens.append(Token("ID", "".join(parts), i))
            i = j
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and sql[i + 1].isdigit()):
            i = _number(sql, i, tokens)
            continue
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] in "_$"):
                j += 1
            word = sql[i:j]
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token("KW", upper, i))
            else:
                tokens.append(Token("ID", word, i))
            i = j
            continue
        for op in OPERATORS:
            if sql.startswith(op, i):
                tokens.append(Token("OP", op, i))
                i += len(op)
                break
        else:
            raise SQLError(f"unrecognized token: {ch!r}")
    tokens.append(Token("EOF", None, n))
    return tokens


def _number(sql: str, i: int, tokens: list[Token]) -> int:
    n = len(sql)
    start = i
    if sql.startswith(("0x", "0X"), i):
        j = i + 2
        while j < n and sql[j] in "0123456789abcdefABCDEF":
            j += 1
        if j == i + 2 or (j < n and (sql[j].isalnum() or sql[j] == "_")):
            raise SQLError(f"unrecognized token: {sql[start:j + 1]!r}")
        value = int(sql[i + 2:j], 16)
        if value > 0xFFFFFFFFFFFFFFFF:
            raise SQLError(f"hex literal too big: {sql[start:j]}")
        if value > INT64_MAX:
            value -= 2**64
        tokens.append(Token("NUM", value, start))
        return j
    j = i
    is_real = False
    while j < n and sql[j].isdigit():
        j += 1
    if j < n and sql[j] == ".":
        is_real = True
        j += 1
        while j < n and sql[j].isdigit():
            j += 1
    if j < n and sql[j] in "eE":
        k = j + 1
        if k < n and sql[k] in "+-":
            k += 1
        if k < n and sql[k].isdigit():
            while k < n and sql[k].isdigit():
                k += 1
            is_real = True
            j = k
        else:
            raise SQLError(f"unrecognized token: {sql[start:k]!r}")
    if j < n and (sql[j].isalpha() or sql[j] == "_"):
        raise SQLError(f"unrecognized token: {sql[start:j + 1]!r}")
    text = sql[start:j]
    if is_real:
        value: int | float = float(text)
    else:
        value = int(text)
        # 2**63 is kept as an int so the parser can fold "-9223372036854775808".
        if value > INT64_MAX + 1:
            value = float(text)
    tokens.append(Token("NUM", value, start))
    return j
