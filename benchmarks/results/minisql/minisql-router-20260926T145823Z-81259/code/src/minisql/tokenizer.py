"""Lexical analysis: turns SQL text into a list of tokens."""

from dataclasses import dataclass

from .errors import SQLError

INT64_MAX = 2**63 - 1

# Longest operators first so that e.g. "<=" wins over "<".
OPERATORS = (
    "||",
    "<=",
    ">=",
    "<>",
    "!=",
    "==",
    "<",
    ">",
    "=",
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


@dataclass(frozen=True)
class Token:
    kind: str  # "num", "str", "id", "qid" (quoted identifier), "op", "eof"
    value: object
    pos: int


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end + 1
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end < 0:
                raise SQLError("unterminated comment")
            i = end + 2
        elif c == "'":
            i, text = _read_quoted(sql, i, "'")
            tokens.append(Token("str", text, i))
        elif c in '"`':
            start = i
            i, text = _read_quoted(sql, i, c)
            tokens.append(Token("qid", text, start))
        elif c == "[":
            end = sql.find("]", i)
            if end < 0:
                raise SQLError("unterminated identifier")
            tokens.append(Token("qid", sql[i + 1 : end], i))
            i = end + 1
        elif c.isdigit() or (c == "." and i + 1 < n and sql[i + 1].isdigit()):
            start = i
            i, value = _read_number(sql, i)
            tokens.append(Token("num", value, start))
        elif c.isalpha() or c == "_":
            start = i
            while i < n and (sql[i].isalnum() or sql[i] in "_$"):
                i += 1
            tokens.append(Token("id", sql[start:i], start))
        else:
            for op in OPERATORS:
                if sql.startswith(op, i):
                    tokens.append(Token("op", op, i))
                    i += len(op)
                    break
            else:
                raise SQLError(f'unrecognized token: "{c}"')
    tokens.append(Token("eof", None, n))
    return tokens


def _read_quoted(sql: str, i: int, quote: str) -> tuple[int, str]:
    parts = []
    i += 1
    while True:
        end = sql.find(quote, i)
        if end < 0:
            raise SQLError("unrecognized token: unterminated quoted string")
        parts.append(sql[i:end])
        if sql.startswith(quote * 2, end):
            parts.append(quote)
            i = end + 2
        else:
            return end + 1, "".join(parts)


def _read_number(sql: str, i: int) -> tuple[int, int | float]:
    n = len(sql)
    start = i
    is_real = False
    while i < n and sql[i].isdigit():
        i += 1
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
            raise SQLError(f'unrecognized token: "{sql[start:j]}"')
    if i < n and (sql[i].isalpha() or sql[i] == "_"):
        raise SQLError(f'unrecognized token: "{sql[start : i + 1]}"')
    text = sql[start:i]
    if is_real:
        return i, float(text)
    value = int(text)
    # Integer literals too large for a 64-bit integer become reals, as in SQLite.
    return i, value if value <= INT64_MAX else float(text)
