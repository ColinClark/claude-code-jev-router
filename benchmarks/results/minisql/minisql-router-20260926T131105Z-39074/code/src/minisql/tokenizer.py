"""Lexical analysis: turn SQL text into a list of tokens."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .errors import SQLError


class TokenKind(Enum):
    KEYWORD = auto()
    IDENT = auto()
    INTEGER = auto()
    REAL = auto()
    STRING = auto()
    OP = auto()
    EOF = auto()


KEYWORDS = frozenset(
    [
        "ALL",
        "AND",
        "AS",
        "ASC",
        "BETWEEN",
        "BY",
        "CREATE",
        "CROSS",
        "DELETE",
        "DESC",
        "DISTINCT",
        "DROP",
        "EXISTS",
        "FROM",
        "GROUP",
        "HAVING",
        "IF",
        "IN",
        "INNER",
        "INSERT",
        "INTO",
        "IS",
        "ISNULL",
        "JOIN",
        "LEFT",
        "LIKE",
        "LIMIT",
        "NOT",
        "NOTNULL",
        "NULL",
        "OFFSET",
        "ON",
        "OR",
        "ORDER",
        "OUTER",
        "SELECT",
        "SET",
        "TABLE",
        "UPDATE",
        "VALUES",
        "WHERE",
    ]
)

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


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    value: str | int | float
    pos: int

    def is_keyword(self, *words: str) -> bool:
        return self.kind is TokenKind.KEYWORD and self.value in words

    def is_op(self, *ops: str) -> bool:
        return self.kind is TokenKind.OP and self.value in ops


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_" or ord(ch) > 127


def _is_ident_char(ch: str) -> bool:
    return ch.isalnum() or ch in "_$" or ord(ch) > 127


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end + 1
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif ch.isdigit() or (ch == "." and i + 1 < n and sql[i + 1].isdigit()):
            i = _read_number(sql, i, tokens)
        elif ch == "'":
            i = _read_quoted(sql, i, "'", TokenKind.STRING, tokens)
        elif ch == '"':
            i = _read_quoted(sql, i, '"', TokenKind.IDENT, tokens)
        elif ch == "`":
            i = _read_quoted(sql, i, "`", TokenKind.IDENT, tokens)
        elif ch == "[":
            end = sql.find("]", i + 1)
            if end < 0:
                raise SQLError(f"unterminated identifier at position {i}")
            tokens.append(Token(TokenKind.IDENT, sql[i + 1 : end], i))
            i = end + 1
        elif _is_ident_start(ch):
            start = i
            while i < n and _is_ident_char(sql[i]):
                i += 1
            word = sql[start:i]
            if word.upper() in KEYWORDS:
                tokens.append(Token(TokenKind.KEYWORD, word.upper(), start))
            else:
                tokens.append(Token(TokenKind.IDENT, word, start))
        else:
            for op in OPERATORS:
                if sql.startswith(op, i):
                    tokens.append(Token(TokenKind.OP, op, i))
                    i += len(op)
                    break
            else:
                raise SQLError(f"unrecognized token: {ch!r}")
    tokens.append(Token(TokenKind.EOF, "", n))
    return tokens


def _read_number(sql: str, i: int, tokens: list[Token]) -> int:
    start = i
    n = len(sql)
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
    if i < n and _is_ident_char(sql[i]):
        raise SQLError(f"unrecognized token: {sql[start : i + 1]!r}")
    text = sql[start:i]
    if is_real:
        tokens.append(Token(TokenKind.REAL, float(text), start))
    else:
        value = int(text)
        if value > 2**63 - 1:
            tokens.append(Token(TokenKind.REAL, float(value), start))
        else:
            tokens.append(Token(TokenKind.INTEGER, value, start))
    return i


def _read_quoted(sql: str, i: int, quote: str, kind: TokenKind, tokens: list[Token]) -> int:
    start = i
    i += 1
    parts: list[str] = []
    n = len(sql)
    while True:
        end = sql.find(quote, i)
        if end < 0:
            raise SQLError(f"unterminated quoted text at position {start}")
        parts.append(sql[i:end])
        if end + 1 < n and sql[end + 1] == quote:
            parts.append(quote)
            i = end + 2
        else:
            tokens.append(Token(kind, "".join(parts), start))
            return end + 1
