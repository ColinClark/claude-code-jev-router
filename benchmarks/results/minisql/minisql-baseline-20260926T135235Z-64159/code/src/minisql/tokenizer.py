"""SQL tokenizer."""

from __future__ import annotations

import re
from dataclasses import dataclass

from minisql.errors import SQLError

# Token kinds
NUM = "NUM"  # numeric literal (value is the source text)
STR = "STR"  # string literal (value is the unescaped string)
ID = "ID"  # bare identifier or keyword
QID = "QID"  # quoted identifier ("x", `x` or [x])
OP = "OP"  # operator or punctuation
EOF = "EOF"

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+|--[^\n]*|/\*.*?(?:\*/|\Z))
    |(?P<num>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)
    |(?P<str>'(?:[^']|'')*')
    |(?P<qid>"(?:[^"]|"")*"|`(?:[^`]|``)*`|\[[^\]]*\])
    |(?P<id>[^\W\d][\w$]*)
    |(?P<op>\|\||==|!=|<>|<=|>=|[<>=+\-*/%(),.;])
    """,
    re.VERBOSE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: str
    pos: int
    upper: str = ""  # upper-cased value for bare identifiers (keyword matching)

    def is_kw(self, *words: str) -> bool:
        return self.kind == ID and self.upper in words


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    n = len(sql)
    match = _TOKEN_RE.match
    while pos < n:
        m = match(sql, pos)
        if m is None:
            ch = sql[pos]
            if ch == "'":
                raise SQLError("unterminated string literal")
            if ch in '"`[':
                raise SQLError("unterminated quoted identifier")
            raise SQLError(f"unrecognized token: {ch!r}")
        kind = m.lastgroup
        text = m.group()
        end = m.end()
        if kind == "num":
            if end < n and (sql[end].isalnum() or sql[end] == "_"):
                raise SQLError(f"unrecognized token: {sql[pos : end + 1]!r}")
            tokens.append(Token(NUM, text, pos))
        elif kind == "str":
            tokens.append(Token(STR, text[1:-1].replace("''", "'"), pos))
        elif kind == "qid":
            q = text[0]
            body = text[1:-1]
            if q != "[":
                body = body.replace(q + q, q)
            tokens.append(Token(QID, body, pos))
        elif kind == "id":
            tokens.append(Token(ID, text, pos, text.upper()))
        elif kind == "op":
            tokens.append(Token(OP, text, pos))
        pos = end
    tokens.append(Token(EOF, "", n))
    return tokens
