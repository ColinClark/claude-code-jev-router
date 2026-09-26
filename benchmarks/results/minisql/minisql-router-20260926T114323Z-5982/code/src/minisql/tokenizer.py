"""SQL tokenizer."""

from __future__ import annotations

from dataclasses import dataclass

from minisql.errors import SQLError
from minisql.values import sqlite_atof

KEYWORDS = frozenset(
    """
    ALL AND AS ASC BETWEEN BY CASE CAST COLLATE CREATE CROSS DELETE DESC DISTINCT DROP ELSE
    END ESCAPE EXCEPT EXISTS FROM FULL GLOB GROUP HAVING IF IN INNER INSERT INTERSECT INTO IS
    ISNULL JOIN LEFT LIKE LIMIT NATURAL NOT NOTNULL NULL OFFSET ON OR ORDER OUTER RIGHT SELECT
    SET TABLE THEN UNION UPDATE USING VALUES WHEN WHERE
    """.split()
)

# Kinds: INT, FLOAT, STR, ID, QID (quoted identifier), KW, OP, EOF
_TWO_CHAR_OPS = ("||", "<=", ">=", "<>", "!=", "==", "<<", ">>")
_ONE_CHAR_OPS = "=<>+-*/%(),.;&|~"
_WS = " \t\n\f\r\v"


@dataclass(slots=True)
class Token:
    kind: str
    value: object
    pos: int
    text: str = ""


def _is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_ident_start(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ch == "_" or ord(ch) >= 0x80


def _is_ident_char(ch: str) -> bool:
    return _is_ident_start(ch) or _is_digit(ch) or ch == "$"


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch in _WS:
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
        if _is_digit(ch) or (ch == "." and i + 1 < n and _is_digit(sql[i + 1])):
            tokens.append(_number(sql, i))
            i = tokens[-1].pos + len(tokens[-1].text)
            if i < n and _is_ident_char(sql[i]):
                raise SQLError(f'unrecognized token: "{sql[start : i + 1]}"')
            continue
        if ch == "'":
            buf = []
            i += 1
            while True:
                if i >= n:
                    raise SQLError(f'unrecognized token: "{sql[start:]}"')
                c = sql[i]
                if c == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(c)
                i += 1
            tokens.append(Token("STR", "".join(buf), start))
            continue
        if ch in "\"`[":
            close = "]" if ch == "[" else ch
            buf = []
            i += 1
            while True:
                if i >= n:
                    raise SQLError(f'unrecognized token: "{sql[start:]}"')
                c = sql[i]
                if c == close:
                    if close != "]" and i + 1 < n and sql[i + 1] == close:
                        buf.append(close)
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(c)
                i += 1
            # Only "..." falls back to a string literal when unresolvable.
            tokens.append(Token("QID", "".join(buf), start, text=ch))
            continue
        if _is_ident_start(ch):
            j = i + 1
            while j < n and _is_ident_char(sql[j]):
                j += 1
            word = sql[i:j]
            up = word.upper()
            if up in KEYWORDS:
                tokens.append(Token("KW", up, start, word))
            else:
                tokens.append(Token("ID", word, start, word))
            i = j
            continue
        two = sql[i : i + 2]
        if two in _TWO_CHAR_OPS:
            tokens.append(Token("OP", two, start))
            i += 2
            continue
        if ch in _ONE_CHAR_OPS:
            tokens.append(Token("OP", ch, start))
            i += 1
            continue
        raise SQLError(f'unrecognized token: "{ch}"')
    tokens.append(Token("EOF", None, n))
    return tokens


def _number(sql: str, i: int) -> Token:
    n = len(sql)
    start = i
    if sql.startswith(("0x", "0X"), i) and i + 2 < n and _is_hex(sql[i + 2]):
        j = i + 2
        while j < n and _is_hex(sql[j]):
            j += 1
        text = sql[start:j]
        value = int(text[2:], 16)
        if value >= 1 << 64:
            raise SQLError(f'hex literal too big: "{text}"')
        if value >= 1 << 63:
            value -= 1 << 64
        return Token("INT", value, start, text)
    is_float = False
    while i < n and _is_digit(sql[i]):
        i += 1
    if i < n and sql[i] == ".":
        is_float = True
        i += 1
        while i < n and _is_digit(sql[i]):
            i += 1
    if i < n and sql[i] in "eE":
        j = i + 1
        if j < n and sql[j] in "+-":
            j += 1
        if j < n and _is_digit(sql[j]):
            is_float = True
            while j < n and _is_digit(sql[j]):
                j += 1
            i = j
        else:
            raise SQLError(f'unrecognized token: "{sql[start : j + 1]}"')
    text = sql[start:i]
    if is_float:
        return Token("FLOAT", sqlite_atof(text)[0], start, text)
    value = int(text)
    if value > (1 << 63) - 1:
        # Too large for a 64-bit integer: SQLite treats it as a real.
        return Token("FLOAT", sqlite_atof(text)[0], start, text)
    return Token("INT", value, start, text)


def _is_hex(ch: str) -> bool:
    return ch in "0123456789abcdefABCDEF"
