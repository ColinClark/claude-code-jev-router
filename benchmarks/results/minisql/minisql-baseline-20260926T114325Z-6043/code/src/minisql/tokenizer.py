"""SQL tokenizer."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SQLError

KEYWORDS = frozenset(
    """
    ALL AND AS ASC BETWEEN BY CREATE CROSS DELETE DESC DISTINCT ESCAPE FROM GROUP HAVING IN
    INNER INSERT INTO IS ISNULL JOIN LEFT LIKE LIMIT NOT NOTNULL NULL OFFSET ON OR ORDER OUTER
    SELECT SET TABLE UPDATE VALUES WHERE
    """.split()
)

# Longest operators first so that e.g. "<=" wins over "<".
OPERATORS = (
    "||", "<=", ">=", "<>", "!=", "==",
    "<", ">", "=", "+", "-", "*", "/", "%", "(", ")", ",", ".", ";",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class Token:
    kind: str  # "num", "str", "id", "kw", "op", "eof"
    value: object
    pos: int
    double_quoted: bool = False  # "name" may fall back to a string literal


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_" or ord(ch) > 127


def _is_ident_char(ch: str) -> bool:
    return ch.isalnum() or ch in "_$" or ord(ch) > 127


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(sql)
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
        start = i
        if ch == "'":
            parts = []
            i += 1
            while True:
                end = sql.find("'", i)
                if end < 0:
                    raise SQLError("unterminated string literal")
                parts.append(sql[i:end])
                if end + 1 < n and sql[end + 1] == "'":
                    parts.append("'")
                    i = end + 2
                else:
                    i = end + 1
                    break
            tokens.append(Token("str", "".join(parts), start))
            continue
        if ch in '"`[':
            close = {'"': '"', "`": "`", "[": "]"}[ch]
            parts = []
            i += 1
            while True:
                end = sql.find(close, i)
                if end < 0:
                    raise SQLError("unterminated quoted identifier")
                parts.append(sql[i:end])
                if close != "]" and end + 1 < n and sql[end + 1] == close:
                    parts.append(close)
                    i = end + 2
                else:
                    i = end + 1
                    break
            tokens.append(Token("id", "".join(parts), start, double_quoted=ch == '"'))
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and sql[i + 1].isdigit()):
            while i < n and sql[i].isdigit():
                i += 1
            is_real = False
            if i < n and sql[i] == ".":
                is_real = True
                i += 1
                while i < n and sql[i].isdigit():
                    i += 1
            if i < n and sql[i] in "eE":
                j = i + 1
                if j < n and sql[j] in "+-":
                    j += 1
                if j < n and sql[j].isdigit():
                    is_real = True
                    i = j
                    while i < n and sql[i].isdigit():
                        i += 1
                else:
                    raise SQLError(f"malformed number near {sql[start:j]!r}")
            if i < n and _is_ident_char(sql[i]):
                raise SQLError(f"unrecognized token: {sql[start : i + 1]!r}")
            text = sql[start:i]
            value: int | float
            if is_real:
                value = float(text)
            else:
                value = int(text)
                if value > 2**63 - 1:
                    value = float(value)
            tokens.append(Token("num", value, start))
            continue
        if _is_ident_start(ch):
            while i < n and _is_ident_char(sql[i]):
                i += 1
            word = sql[start:i]
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token("kw", upper, start))
            else:
                tokens.append(Token("id", word, start))
            continue
        for op in OPERATORS:
            if sql.startswith(op, i):
                tokens.append(Token("op", op, start))
                i += len(op)
                break
        else:
            raise SQLError(f"unrecognized token: {ch!r}")
    tokens.append(Token("eof", None, n))
    return tokens
