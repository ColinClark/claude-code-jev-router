"""Tokenizer for minisql.

Produces a flat list of :class:`Token` objects ending with an ``EOF`` token.
Keywords are recognised case-insensitively and normalised to upper case;
unquoted identifiers keep their original spelling (identifier comparison is
case-insensitive and happens later).
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SQLError

# Token kinds
KEYWORD = "KEYWORD"
IDENT = "IDENT"
INTEGER = "INTEGER"
FLOAT = "FLOAT"
STRING = "STRING"
OP = "OP"
EOF = "EOF"

KEYWORDS = frozenset(
    {
        "SELECT", "FROM", "WHERE", "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC", "LIMIT",
        "OFFSET", "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE", "CREATE", "TABLE",
        "DROP", "IF", "EXISTS", "NOT", "NULL", "AND", "OR", "IN", "IS", "LIKE", "GLOB",
        "BETWEEN", "ESCAPE", "ISNULL", "NOTNULL", "JOIN", "INNER", "LEFT", "OUTER", "CROSS",
        "ON", "AS", "DISTINCT", "ALL", "CASE", "WHEN", "THEN", "ELSE", "END", "CAST",
    }
)

# Longest operators first so that greedy matching works.
OPERATORS = (
    "<>", "<=", ">=", "==", "!=", "||", "<<", ">>",
    "<", ">", "=", "+", "-", "*", "/", "%", "(", ")", ",", ".", ";", "&", "|", "~",
)

MAX_INT64 = 2**63 - 1


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: object
    pos: int
    text: str  # raw source text of the token (for error messages)


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
            continue
        # Comments
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        start = i
        # String literal
        if c == "'":
            i += 1
            buf = []
            while True:
                if i >= n:
                    raise SQLError("unrecognized token: unterminated string literal")
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(sql[i])
                i += 1
            tokens.append(Token(STRING, "".join(buf), start, sql[start:i]))
            continue
        # Quoted identifiers
        if c in "\"`[":
            close = {"\"": "\"", "`": "`", "[": "]"}[c]
            i += 1
            buf = []
            while True:
                if i >= n:
                    raise SQLError("unrecognized token: unterminated quoted identifier")
                if sql[i] == close:
                    if close != "]" and i + 1 < n and sql[i + 1] == close:
                        buf.append(close)
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(sql[i])
                i += 1
            tokens.append(Token(IDENT, "".join(buf), start, sql[start:i]))
            continue
        # Numbers
        if c.isdigit() or (c == "." and i + 1 < n and sql[i + 1].isdigit()):
            if c == "0" and i + 1 < n and sql[i + 1] in "xX":
                j = i + 2
                while j < n and sql[j] in "0123456789abcdefABCDEF":
                    j += 1
                if j == i + 2:
                    raise SQLError(f'unrecognized token: "{sql[i:j]}"')
                value = int(sql[i + 2 : j], 16)
                if value > 0xFFFFFFFFFFFFFFFF:
                    raise SQLError(f'hex literal too big: {sql[i:j]}')
                if value > MAX_INT64:
                    value -= 2**64
                tokens.append(Token(INTEGER, value, start, sql[i:j]))
                i = j
                continue
            j = i
            is_float = False
            while j < n and sql[j].isdigit():
                j += 1
            if j < n and sql[j] == ".":
                is_float = True
                j += 1
                while j < n and sql[j].isdigit():
                    j += 1
            if j < n and sql[j] in "eE":
                k = j + 1
                if k < n and sql[k] in "+-":
                    k += 1
                if k < n and sql[k].isdigit():
                    is_float = True
                    j = k
                    while j < n and sql[j].isdigit():
                        j += 1
                else:
                    raise SQLError(f'unrecognized token: "{sql[i:k]}"')
            if j < n and (sql[j].isalpha() or sql[j] == "_"):
                raise SQLError(f'unrecognized token: "{sql[i:j + 1]}"')
            text = sql[i:j]
            if is_float:
                tokens.append(Token(FLOAT, float(text), start, text))
            else:
                value = int(text)
                if value > MAX_INT64:
                    tokens.append(Token(FLOAT, float(text), start, text))
                else:
                    tokens.append(Token(INTEGER, value, start, text))
            i = j
            continue
        # Identifiers / keywords
        if c.isalpha() or c == "_":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] in "_$"):
                j += 1
            word = sql[i:j]
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token(KEYWORD, upper, start, word))
            else:
                tokens.append(Token(IDENT, word, start, word))
            i = j
            continue
        # Operators
        for op in OPERATORS:
            if sql.startswith(op, i):
                tokens.append(Token(OP, op, start, op))
                i += len(op)
                break
        else:
            raise SQLError(f'unrecognized token: "{c}"')
    tokens.append(Token(EOF, None, n, ""))
    return tokens
