"""SQL tokenizer."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SQLError
from .values import INT_MAX


@dataclass(slots=True)
class Token:
    kind: str  # NAME, QNAME, NUM, STR, OP, EOF
    value: object
    pos: int
    text: str = ""

    @property
    def upper(self) -> str | None:
        if self.kind == "NAME":
            return str(self.value).upper()
        return None


_OPS2 = ("||", "<=", ">=", "<>", "!=", "==", "<<", ">>")
_OPS1 = "+-*/%<>=(),.;&|~"


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(sql)
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
        if c.isdigit() or (c == "." and i + 1 < n and sql[i + 1].isdigit()):
            if c == "0" and i + 1 < n and sql[i + 1] in "xX":
                j = i + 2
                while j < n and sql[j] in "0123456789abcdefABCDEF":
                    j += 1
                if j == i + 2:
                    raise SQLError(f'unrecognized token: "{sql[i:j]}"')
                val = int(sql[i + 2 : j], 16)
                if val > 0xFFFFFFFFFFFFFFFF:
                    raise SQLError(f'hex literal too big: "{sql[i:j]}"')
                if val > INT_MAX:
                    val -= 2**64
                tokens.append(Token("NUM", val, start))
                i = j
            else:
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
                        is_real = True
                        j = k
                        while j < n and sql[j].isdigit():
                            j += 1
                    else:
                        raise SQLError(f'unrecognized token: "{sql[i:k]}"')
                text = sql[i:j]
                if j < n and (sql[j].isalnum() or sql[j] == "_"):
                    raise SQLError(f'unrecognized token: "{text}{sql[j]}"')
                if is_real:
                    value: int | float = float(text)
                else:
                    value = int(text)
                    if value > INT_MAX:
                        value = float(text)
                tokens.append(Token("NUM", value, start, text))
                i = j
            continue
        if c.isalpha() or c == "_":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] in "_$"):
                j += 1
            tokens.append(Token("NAME", sql[i:j], start))
            i = j
            continue
        if c == "'":
            j = i + 1
            parts = []
            while True:
                k = sql.find("'", j)
                if k < 0:
                    raise SQLError("unrecognized token: unterminated string literal")
                parts.append(sql[j:k])
                if k + 1 < n and sql[k + 1] == "'":
                    parts.append("'")
                    j = k + 2
                    continue
                i = k + 1
                break
            tokens.append(Token("STR", "".join(parts), start))
            continue
        if c in "\"`[":
            close = {"\"": "\"", "`": "`", "[": "]"}[c]
            j = i + 1
            parts = []
            while True:
                k = sql.find(close, j)
                if k < 0:
                    raise SQLError("unrecognized token: unterminated identifier")
                parts.append(sql[j:k])
                if close != "]" and k + 1 < n and sql[k + 1] == close:
                    parts.append(close)
                    j = k + 2
                    continue
                i = k + 1
                break
            tokens.append(Token("QNAME", "".join(parts), start))
            continue
        two = sql[i : i + 2]
        if two in _OPS2:
            tokens.append(Token("OP", two, start))
            i += 2
            continue
        if c in _OPS1:
            tokens.append(Token("OP", c, start))
            i += 1
            continue
        raise SQLError(f'unrecognized token: "{c}"')
    tokens.append(Token("EOF", None, n))
    return tokens
