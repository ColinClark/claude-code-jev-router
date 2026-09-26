"""SQL tokenizer."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SQLError

KEYWORDS = frozenset(
    """
    ALL AND AS ASC BETWEEN BY CASE CREATE CROSS DELETE DESC DISTINCT DROP ELSE END EXISTS FROM
    GROUP HAVING IF IN INNER INSERT INTO IS JOIN LEFT LIKE LIMIT NOT NULL OFFSET ON OR ORDER
    OUTER SELECT SET TABLE THEN UPDATE VALUES WHEN WHERE
    """.split()
)

# Token kinds
IDENT = "IDENT"  # identifier (value is the name as written, unquoted)
KEYWORD = "KEYWORD"  # value is upper-case keyword
NUMBER = "NUMBER"  # value is int or float
STRING = "STRING"
OP = "OP"
EOF = "EOF"

_OPERATORS = (
    "||",
    "<=",
    ">=",
    "<>",
    "!=",
    "==",
    "=",
    "<",
    ">",
    "+",
    "-",
    "*",
    "/",
    "%",
    "(",
    ")",
    ",",
    ".",
    ";",
)


@dataclass
class Token:
    kind: str
    value: object
    pos: int


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(sql)
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
            buf = []
            i += 1
            while True:
                if i >= n:
                    raise SQLError("unterminated string literal")
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(sql[i])
                i += 1
            tokens.append(Token(STRING, "".join(buf), start))
            continue
        if c in '"`[':
            close = "]" if c == "[" else c
            buf = []
            i += 1
            while True:
                if i >= n:
                    raise SQLError("unterminated quoted identifier")
                if sql[i] == close:
                    if close != "]" and i + 1 < n and sql[i + 1] == close:
                        buf.append(close)
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(sql[i])
                i += 1
            tokens.append(Token(IDENT, "".join(buf), start))
            continue
        if c.isdigit() or (c == "." and i + 1 < n and sql[i + 1].isdigit()):
            j = i
            while j < n and sql[j].isdigit():
                j += 1
            is_real = False
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
                    is_real = True
                    j = k
                    while j < n and sql[j].isdigit():
                        j += 1
                else:
                    raise SQLError(f"malformed number near {sql[i:k]!r}")
            text = sql[i:j]
            if j < n and (sql[j].isalnum() or sql[j] == "_"):
                raise SQLError(f"unrecognized token: {sql[i : j + 1]!r}")
            if is_real:
                value: object = float(text)
            else:
                value = int(text)  # out-of-range values are handled by the parser
            tokens.append(Token(NUMBER, value, start))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] in "_$"):
                j += 1
            word = sql[i:j]
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token(KEYWORD, upper, start))
            else:
                tokens.append(Token(IDENT, word, start))
            i = j
            continue
        for op in _OPERATORS:
            if sql.startswith(op, i):
                tokens.append(Token(OP, op, start))
                i += len(op)
                break
        else:
            raise SQLError(f"unrecognized token: {c!r}")
    tokens.append(Token(EOF, None, n))
    return tokens
