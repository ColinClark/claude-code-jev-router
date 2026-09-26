"""Recursive-descent parser: pattern string -> AST (see :mod:`miniregex.nodes`).

The grammar and its error behaviour follow CPython's ``re`` parser (``sre_parse``)
for the supported subset of syntax.
"""

from __future__ import annotations

from .errors import RegexError
from .nodes import (
    CATEGORIES,
    Alt,
    Any,
    Bol,
    Char,
    CharSet,
    Eol,
    Group,
    Node,
    Repeat,
    Seq,
)

# Same limit as CPython's MAXREPEAT; counts must be strictly below it.
MAXREPEAT = 4294967295

_DIGITS = "0123456789"

# Letter escapes that denote a single literal character.
_CHAR_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v", "a": "\a"}


class Parser:
    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self.pos = 0
        self.ngroups = 0

    # -- helpers -----------------------------------------------------------

    def error(self, msg: str, pos: int | None = None) -> RegexError:
        return RegexError(msg, self.pattern, self.pos if pos is None else pos)

    def peek(self) -> str | None:
        if self.pos < len(self.pattern):
            return self.pattern[self.pos]
        return None

    def get(self) -> str | None:
        if self.pos < len(self.pattern):
            ch = self.pattern[self.pos]
            self.pos += 1
            return ch
        return None

    # -- grammar -----------------------------------------------------------

    def parse(self) -> Node:
        node = self.parse_alt()
        if self.pos < len(self.pattern):
            # Only an unmatched ')' can stop the top-level alternation early.
            raise self.error("unbalanced parenthesis")
        return node

    def parse_alt(self) -> Node:
        branches = [self.parse_seq()]
        while self.peek() == "|":
            self.pos += 1
            branches.append(self.parse_seq())
        if len(branches) == 1:
            return branches[0]
        return Alt(tuple(branches))

    def parse_seq(self) -> Node:
        items: list[Node] = []
        pattern = self.pattern
        while self.pos < len(pattern):
            start = self.pos
            ch = pattern[self.pos]
            if ch in "|)":
                break
            self.pos += 1
            if ch == "(":
                items.append(self.parse_group(start))
            elif ch == "[":
                items.append(self.parse_set(start))
            elif ch == ".":
                items.append(Any())
            elif ch == "^":
                items.append(Bol())
            elif ch == "$":
                items.append(Eol())
            elif ch == "\\":
                items.append(self.parse_escape(start))
            elif ch in "*+?{":
                bounds = self.parse_quantifier(ch, start)
                if bounds is None:
                    # '{' that does not form a valid quantifier is a literal.
                    items.append(Char(ch))
                    continue
                lo, hi = bounds
                if not items or isinstance(items[-1], (Bol, Eol)):
                    raise self.error("nothing to repeat", start)
                if isinstance(items[-1], Repeat):
                    raise self.error("multiple repeat", start)
                greedy = True
                if self.peek() == "?":
                    self.pos += 1
                    greedy = False
                items[-1] = Repeat(items[-1], lo, hi, greedy)
            else:
                items.append(Char(ch))
        if len(items) == 1:
            return items[0]
        return Seq(tuple(items))

    def parse_quantifier(self, ch: str, start: int) -> tuple[int, int | None] | None:
        if ch == "*":
            return 0, None
        if ch == "+":
            return 1, None
        if ch == "?":
            return 0, 1
        # ch == "{": mirror sre_parse, falling back to a literal '{'.
        pattern = self.pattern
        if self.peek() == "}":
            return None
        lo = hi = ""
        while self.peek() is not None and self.peek() in _DIGITS:
            lo += pattern[self.pos]
            self.pos += 1
        if self.peek() == ",":
            self.pos += 1
            while self.peek() is not None and self.peek() in _DIGITS:
                hi += pattern[self.pos]
                self.pos += 1
        else:
            hi = lo
        if self.peek() != "}":
            self.pos = start + 1
            return None
        self.pos += 1
        mn = 0
        mx: int | None = None
        if lo:
            mn = int(lo)
            if mn >= MAXREPEAT:
                raise self.error("the repetition number is too large", start)
        if hi:
            mx = int(hi)
            if mx >= MAXREPEAT:
                raise self.error("the repetition number is too large", start)
            if mx < mn:
                raise self.error("min repeat greater than max repeat", start)
        return mn, mx

    def parse_group(self, start: int) -> Node:
        capture = True
        if self.peek() == "?":
            self.pos += 1
            nxt = self.get()
            if nxt != ":":
                if nxt is None:
                    raise self.error("unexpected end of pattern", self.pos)
                raise self.error(f"unknown or unsupported extension ?{nxt}", start + 1)
            capture = False
        index = 0
        if capture:
            self.ngroups += 1
            index = self.ngroups
        body = self.parse_alt()
        if self.peek() != ")":
            raise self.error("missing ), unterminated subpattern", start)
        self.pos += 1
        if capture:
            return Group(index, body)
        # Keep the group boundary visible so that e.g. ``(?:a*)*`` is not
        # mistaken for a "multiple repeat" and ``(?:^)*`` is allowed, as in re.
        return Seq((body,))

    def parse_escape(self, start: int) -> Node:
        ch = self.get()
        if ch is None:
            raise self.error("bad escape (end of pattern)", start)
        if ch in CATEGORIES:
            return CharSet(frozenset(), (), (ch,), False)
        if ch in _CHAR_ESCAPES:
            return Char(_CHAR_ESCAPES[ch])
        if ch.isascii() and ch.isalnum():
            raise self.error(f"bad escape \\{ch}", start)
        return Char(ch)

    def parse_set_escape(self, start: int) -> tuple[str, str]:
        """Parse an escape inside ``[...]``. Returns ("lit", ch) or ("cat", letter)."""
        ch = self.get()
        if ch is None:
            raise self.error("bad escape (end of pattern)", start)
        if ch in CATEGORIES:
            return "cat", ch
        if ch in _CHAR_ESCAPES:
            return "lit", _CHAR_ESCAPES[ch]
        if ch == "b":
            return "lit", "\b"
        if ch.isascii() and ch.isalnum():
            raise self.error(f"bad escape \\{ch}", start)
        return "lit", ch

    def parse_set(self, start: int) -> Node:
        negated = False
        if self.peek() == "^":
            self.pos += 1
            negated = True
        chars: set[str] = set()
        ranges: list[tuple[str, str]] = []
        categories: list[str] = []
        first = True

        def add(item: tuple[str, str]) -> None:
            if item[0] == "cat":
                categories.append(item[1])
            else:
                chars.add(item[1])

        while True:
            item_start = self.pos
            this = self.get()
            if this is None:
                raise self.error("unterminated character set", start)
            if this == "]" and not first:
                break
            first = False
            if this == "\\":
                code1 = self.parse_set_escape(item_start)
            else:
                code1 = ("lit", this)
            if self.peek() == "-":
                self.pos += 1
                that_start = self.pos
                that = self.get()
                if that is None:
                    raise self.error("unterminated character set", start)
                if that == "]":
                    add(code1)
                    chars.add("-")
                    break
                if that == "\\":
                    code2 = self.parse_set_escape(that_start)
                else:
                    code2 = ("lit", that)
                if code1[0] != "lit" or code2[0] != "lit":
                    text = self.pattern[item_start : self.pos]
                    raise self.error(f"bad character range {text}", item_start)
                lo, hi = code1[1], code2[1]
                if hi < lo:
                    text = self.pattern[item_start : self.pos]
                    raise self.error(f"bad character range {text}", item_start)
                ranges.append((lo, hi))
            else:
                add(code1)
        return CharSet(frozenset(chars), tuple(ranges), tuple(categories), negated)


def parse(pattern: str) -> tuple[Node, int]:
    """Parse ``pattern`` and return ``(ast, number_of_capturing_groups)``."""
    if not isinstance(pattern, str):
        raise TypeError(f"pattern must be a str, not {type(pattern).__name__}")
    parser = Parser(pattern)
    node = parser.parse()
    return node, parser.ngroups
