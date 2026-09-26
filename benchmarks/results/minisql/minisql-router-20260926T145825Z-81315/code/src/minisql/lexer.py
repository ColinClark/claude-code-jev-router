"""Tokenizer for the minisql SQL dialect."""

from dataclasses import dataclass

from minisql.errors import SQLError

KEYWORDS = frozenset(
    """
    ALL AND AS ASC BETWEEN BY CASE CREATE CROSS DELETE DESC DISTINCT DROP ELSE END ESCAPE
    EXISTS FROM FULL GROUP HAVING IF IN INNER INSERT INTO IS ISNULL JOIN LEFT LIKE LIMIT
    NATURAL NOT NOTNULL NULL OFFSET ON OR ORDER OUTER RIGHT SELECT SET TABLE THEN UNION
    UPDATE USING VALUES WHEN WHERE
    """.split()
)

# Longest operators first so that e.g. "<=" wins over "<".
OPERATORS = ("||", "==", "!=", "<>", "<=", ">=", "<", ">", "=", "+", "-", "*", "/", "%",
             "(", ")", ",", ".", ";")


@dataclass(frozen=True)
class Token:
    kind: str  # "kw", "id", "num", "str", "op", "eof"
    value: str
    pos: int


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_"


def _is_ident_char(ch: str) -> bool:
    return ch.isalnum() or ch in "_$"


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
        start = i
        if ch.isdigit() or (ch == "." and i + 1 < n and sql[i + 1].isdigit()):
            while i < n and sql[i].isdigit():
                i += 1
            if i < n and sql[i] == ".":
                i += 1
                while i < n and sql[i].isdigit():
                    i += 1
            if i < n and sql[i] in "eE":
                j = i + 1
                if j < n and sql[j] in "+-":
                    j += 1
                if j < n and sql[j].isdigit():
                    i = j
                    while i < n and sql[i].isdigit():
                        i += 1
                else:
                    raise SQLError(f'unrecognized token: "{sql[start:j]}"')
            if i < n and _is_ident_char(sql[i]):
                raise SQLError(f'unrecognized token: "{sql[start:i + 1]}"')
            tokens.append(Token("num", sql[start:i], start))
            continue
        if ch == "'":
            i += 1
            parts = []
            while True:
                if i >= n:
                    raise SQLError("unterminated string literal")
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        parts.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                parts.append(sql[i])
                i += 1
            tokens.append(Token("str", "".join(parts), start))
            continue
        if ch in '"`[':
            close = {"\"": '"', "`": "`", "[": "]"}[ch]
            i += 1
            parts = []
            while True:
                if i >= n:
                    raise SQLError("unterminated quoted identifier")
                if sql[i] == close:
                    if close != "]" and i + 1 < n and sql[i + 1] == close:
                        parts.append(close)
                        i += 2
                        continue
                    i += 1
                    break
                parts.append(sql[i])
                i += 1
            tokens.append(Token("id", "".join(parts), start))
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
            raise SQLError(f'unrecognized token: "{ch}"')
    tokens.append(Token("eof", "", n))
    return tokens
