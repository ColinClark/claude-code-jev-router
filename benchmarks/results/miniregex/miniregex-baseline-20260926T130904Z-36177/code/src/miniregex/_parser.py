"""Recursive-descent parser producing matcher nodes from `_nodes.py`."""

from __future__ import annotations

from ._errors import RegexError
from ._nodes import (
    Alt,
    AnchorEnd,
    AnchorStart,
    AnyChar,
    CharSet,
    Concat,
    Empty,
    Group,
    Literal,
    Repeat,
)


def _is_digit(c):
    return "0" <= c <= "9"


def _is_word(c):
    return c == "_" or "a" <= c <= "z" or "A" <= c <= "Z" or "0" <= c <= "9"


def _is_space(c):
    return c in " \t\n\r\f\v"


CLASS_PREDICATES = {
    "d": _is_digit,
    "D": lambda c: not _is_digit(c),
    "w": _is_word,
    "W": lambda c: not _is_word(c),
    "s": _is_space,
    "S": lambda c: not _is_space(c),
}

LITERAL_ESCAPES = set(".\\*+?()[]{}|^$-")


class Parser:
    def __init__(self, pattern):
        self.p = pattern
        self.i = 0
        self.n = len(pattern)
        self.group_count = 0

    def peek(self):
        return self.p[self.i] if self.i < self.n else None

    def advance(self):
        ch = self.p[self.i]
        self.i += 1
        return ch

    def eof(self):
        return self.i >= self.n

    def parse(self):
        node = self.parse_alt()
        if not self.eof():
            raise RegexError(f"Unexpected character {self.p[self.i]!r} at position {self.i}")
        return node, self.group_count

    def parse_alt(self):
        branches = [self.parse_concat()]
        while not self.eof() and self.peek() == "|":
            self.advance()
            branches.append(self.parse_concat())
        if len(branches) == 1:
            return branches[0]
        return Alt(branches)

    def parse_concat(self):
        items = []
        while not self.eof() and self.peek() not in ("|", ")"):
            items.append(self.parse_repeat())
        if not items:
            return Empty()
        if len(items) == 1:
            return items[0]
        return Concat(items)

    def parse_repeat(self):
        atom = self.parse_atom()
        while not self.eof():
            c = self.peek()
            if c == "*":
                self.advance()
                mn, mx = 0, None
            elif c == "+":
                self.advance()
                mn, mx = 1, None
            elif c == "?":
                self.advance()
                mn, mx = 0, 1
            elif c == "{":
                res = self._try_parse_braces()
                if res is None:
                    break
                mn, mx = res
            else:
                break
            if isinstance(atom, Repeat):
                raise RegexError("multiple repeat")
            lazy = False
            if not self.eof() and self.peek() == "?":
                self.advance()
                lazy = True
            atom = Repeat(atom, mn, mx, lazy)
        return atom

    def _try_parse_braces(self):
        start = self.i
        j = self.i + 1

        def read_digits(j):
            s = j
            while j < self.n and self.p[j].isdigit():
                j += 1
            return self.p[s:j], j

        n1, j = read_digits(j)
        if j < self.n and self.p[j] == ",":
            j += 1
            n2, j = read_digits(j)
            if j < self.n and self.p[j] == "}":
                mn = int(n1) if n1 else 0
                mx = int(n2) if n2 else None
                if mx is not None and mx < mn:
                    raise RegexError("min repeat greater than max repeat")
                self.i = j + 1
                return (mn, mx)
            self.i = start
            return None
        else:
            if n1 and j < self.n and self.p[j] == "}":
                mn = int(n1)
                self.i = j + 1
                return (mn, mn)
            self.i = start
            return None

    def parse_atom(self):
        c = self.peek()
        if c is None:
            raise RegexError("Unexpected end of pattern")
        if c == "(":
            return self.parse_group()
        if c == "[":
            return self.parse_class()
        if c == ".":
            self.advance()
            return AnyChar()
        if c == "^":
            self.advance()
            return AnchorStart()
        if c == "$":
            self.advance()
            return AnchorEnd()
        if c == "\\":
            return self.parse_escape()
        if c == ")":
            raise RegexError("Unbalanced parenthesis")
        if c in "*+?":
            raise RegexError(f"Nothing to repeat: {c!r}")
        self.advance()
        return Literal(c)

    def parse_escape(self):
        self.advance()
        if self.eof():
            raise RegexError("Trailing backslash")
        c = self.advance()
        if c in CLASS_PREDICATES:
            return CharSet([("pred", CLASS_PREDICATES[c])], negate=False)
        if c in LITERAL_ESCAPES:
            return Literal(c)
        raise RegexError(f"Unsupported escape sequence \\{c}")

    def parse_group(self):
        self.advance()  # consume '('
        capturing = True
        index = None
        if not self.eof() and self.peek() == "?":
            if self.i + 1 < self.n and self.p[self.i + 1] == ":":
                self.advance()
                self.advance()
                capturing = False
            else:
                raise RegexError("Unsupported group syntax")
        if capturing:
            self.group_count += 1
            index = self.group_count
        body = self.parse_alt()
        if self.eof() or self.peek() != ")":
            raise RegexError("Missing closing parenthesis")
        self.advance()
        return Group(index, body)

    def _read_set_char(self):
        c = self.advance()
        if c == "\\":
            if self.eof():
                raise RegexError("Trailing backslash in character set")
            e = self.advance()
            if e in CLASS_PREDICATES:
                return ("pred", CLASS_PREDICATES[e])
            if e in LITERAL_ESCAPES:
                return ("lit", e)
            raise RegexError(f"Unsupported escape sequence \\{e} in character set")
        return ("lit", c)

    def parse_class(self):
        self.advance()  # consume '['
        negate = False
        if not self.eof() and self.peek() == "^":
            negate = True
            self.advance()
        items = []
        first = True
        while True:
            if self.eof():
                raise RegexError("Unterminated character set")
            c = self.peek()
            if c == "]" and not first:
                self.advance()
                break
            first = False
            kind, value = self._read_set_char()
            if kind == "pred":
                items.append(("pred", value))
                continue
            lo = value
            if (
                not self.eof()
                and self.peek() == "-"
                and self.i + 1 < self.n
                and self.p[self.i + 1] != "]"
            ):
                self.advance()  # consume '-'
                hi_kind, hi_value = self._read_set_char()
                if hi_kind == "pred":
                    raise RegexError("Bad character range")
                hi = hi_value
                if ord(lo) > ord(hi):
                    raise RegexError(f"Bad character range {lo}-{hi}")
                items.append(("range", lo, hi))
            else:
                items.append(("range", lo, lo))
        return CharSet(items, negate)


def parse(pattern):
    parser = Parser(pattern)
    return parser.parse()
