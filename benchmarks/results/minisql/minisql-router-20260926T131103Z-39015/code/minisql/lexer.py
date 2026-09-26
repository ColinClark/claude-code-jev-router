"""Tokenizer for the minisql SQL dialect."""

from __future__ import annotations

from dataclasses import dataclass

from minisql.errors import SQLError

# Token kinds
IDENT = "IDENT"  # bare or quoted identifier (keywords are bare IDENTs)
STRING = "STRING"
NUMBER = "NUMBER"
OP = "OP"
EOF = "EOF"

_TWO_CHAR_OPS = {"||", "<=", ">=", "<>", "!=", "==", "<<", ">>"}
_ONE_CHAR_OPS = set("+-*/%(),.;=<>&|~")


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: object
    pos: int
    quoted: bool = False

    @property
    def upper(self) -> str:
        """Uppercase text of a bare identifier (used for keyword matching)."""
        if self.kind == IDENT and not self.quoted:
            return str(self.value).upper()
        return ""


def _parse_number(text: str) -> int | float:
    if text.lower().startswith("0x"):
        value = int(text, 16)
        if value >= 2**63:
            value -= 2**64
        return value
    if any(c in text for c in ".eE"):
        return float(text)
    return int(text)


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
            continue
        if c == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        start = i
        if c == "'":
            i += 1
            parts: list[str] = []
            while True:
                if i >= n:
                    raise SQLError("unrecognized token: unterminated string literal")
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        parts.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                parts.append(sql[i])
                i += 1
            tokens.append(Token(STRING, "".join(parts), start))
            continue
        if c in "\"`[":
            close = {"\"": "\"", "`": "`", "[": "]"}[c]
            i += 1
            parts = []
            while True:
                if i >= n:
                    raise SQLError("unrecognized token: unterminated identifier")
                if sql[i] == close:
                    if close != "]" and i + 1 < n and sql[i + 1] == close:
                        parts.append(close)
                        i += 2
                        continue
                    i += 1
                    break
                parts.append(sql[i])
                i += 1
            tokens.append(Token(IDENT, "".join(parts), start, quoted=True))
            continue
        if c.isdigit() or (c == "." and i + 1 < n and sql[i + 1].isdigit()):
            if c == "0" and i + 1 < n and sql[i + 1] in "xX":
                j = i + 2
                while j < n and sql[j] in "0123456789abcdefABCDEF":
                    j += 1
                if j == i + 2:
                    raise SQLError(f"unrecognized token: {sql[i:j]!r}")
                i = j
            else:
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
                        while j < n and sql[j].isdigit():
                            j += 1
                        i = j
                    else:
                        raise SQLError(f"unrecognized token: {sql[start:j]!r}")
            if i < n and (sql[i].isalpha() or sql[i] == "_"):
                raise SQLError(f"unrecognized token: {sql[start:i + 1]!r}")
            tokens.append(Token(NUMBER, _parse_number(sql[start:i]), start))
            continue
        if c.isalpha() or c == "_":
            while i < n and (sql[i].isalnum() or sql[i] in "_$"):
                i += 1
            tokens.append(Token(IDENT, sql[start:i], start))
            continue
        two = sql[i : i + 2]
        if two in _TWO_CHAR_OPS:
            tokens.append(Token(OP, two, start))
            i += 2
            continue
        if c in _ONE_CHAR_OPS:
            tokens.append(Token(OP, c, start))
            i += 1
            continue
        raise SQLError(f"unrecognized token: {c!r}")
    tokens.append(Token(EOF, None, n))
    return tokens
