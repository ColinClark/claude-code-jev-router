"""Recursive-descent parser: pattern string -> AST (see ``nodes``)."""

from __future__ import annotations

from .errors import RegexError
from .nodes import (
    Alternation,
    Anchor,
    AnyChar,
    CharClass,
    Group,
    Literal,
    Node,
    Repeat,
    Sequence,
)

_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_DIGITS = frozenset("0123456789")
_OCTDIGITS = frozenset("01234567")
_HEXDIGITS = frozenset("0123456789abcdefABCDEF")
_CLASS_LETTERS = frozenset("dDwWsS")
_REPEAT_CHARS = frozenset("*+?{")
_SIMPLE_ESCAPES = {
    "a": "\a",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}
_ANCHOR_ESCAPES = {"A": "A", "Z": "Z", "b": "b", "B": "B"}
MAXREPEAT = 4294967295


class Parser:
    def __init__(self, pattern: str) -> None:
        if not isinstance(pattern, str):
            raise TypeError("pattern must be a str")
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

    def next(self) -> str | None:
        ch = self.peek()
        if ch is not None:
            self.pos += 1
        return ch

    # -- grammar -----------------------------------------------------------
    def parse(self) -> Node:
        node = self.parse_alternation()
        if self.pos < len(self.pattern):
            # Only an unmatched ')' can stop the top-level parse early.
            raise self.error("unbalanced parenthesis")
        return node

    def parse_alternation(self) -> Node:
        start = self.pos
        branches = [self.parse_sequence()]
        while self.peek() == "|":
            self.pos += 1
            branches.append(self.parse_sequence())
        if len(branches) == 1:
            return branches[0]
        for b in branches:
            if isinstance(b, Sequence) and not b.items:
                raise self.error("dangling '|' (empty alternative)", start)
        return Alternation(tuple(branches))

    def parse_sequence(self) -> Node:
        items: list[Node] = []
        while True:
            ch = self.peek()
            if ch is None or ch in "|)":
                break
            atom_start = self.pos
            atom = self.parse_atom()
            items.append(self.parse_quantifiers(atom, atom_start))
        if len(items) == 1:
            return items[0]
        return Sequence(tuple(items))

    def parse_quantifiers(self, atom: Node, atom_start: int) -> Node:
        ch = self.peek()
        if ch is None or ch not in _REPEAT_CHARS:
            return atom
        qpos = self.pos
        lo, hi = self.parse_quantifier()
        if isinstance(atom, Anchor):
            raise self.error("nothing to repeat", qpos)
        greedy = True
        if self.peek() == "?":
            self.pos += 1
            greedy = False
        nxt = self.peek()
        if nxt is not None and nxt in _REPEAT_CHARS:
            if nxt == "+":
                raise self.error("multiple repeat (possessive quantifiers are not supported)")
            raise self.error("multiple repeat")
        return Repeat(atom, lo, hi, greedy)

    def parse_quantifier(self) -> tuple[int, int | None]:
        ch = self.next()
        if ch == "*":
            return 0, None
        if ch == "+":
            return 1, None
        if ch == "?":
            return 0, 1
        # ch == "{"
        start = self.pos - 1
        lo_s = self._read_digits()
        hi_s: str | None
        if self.peek() == ",":
            self.pos += 1
            hi_s = self._read_digits()
        else:
            hi_s = lo_s
            if not lo_s:
                raise self.error("invalid repetition: expected digits in '{...}'", start)
        if self.peek() != "}":
            raise self.error("invalid repetition: expected '}'", start)
        self.pos += 1
        lo = int(lo_s) if lo_s else 0
        hi = int(hi_s) if hi_s else None
        if lo > MAXREPEAT or (hi is not None and hi > MAXREPEAT):
            raise self.error("the repetition number is too large", start)
        if hi is not None and hi < lo:
            raise self.error("min repeat greater than max repeat", start)
        return lo, hi

    def _read_digits(self) -> str:
        start = self.pos
        while (c := self.peek()) is not None and c in _DIGITS:
            self.pos += 1
        return self.pattern[start : self.pos]

    def parse_atom(self) -> Node:
        start = self.pos
        ch = self.next()
        assert ch is not None
        if ch == "(":
            return self.parse_group(start)
        if ch == "[":
            return self.parse_class(start)
        if ch == ".":
            return AnyChar()
        if ch == "^":
            return Anchor("bol")
        if ch == "$":
            return Anchor("eol")
        if ch == "\\":
            return self.parse_escape(start)
        if ch in _REPEAT_CHARS:
            raise self.error("nothing to repeat", start)
        return Literal(ch)

    def parse_group(self, start: int) -> Node:
        index: int | None
        if self.peek() == "?":
            if self.pattern.startswith("?:", self.pos):
                self.pos += 2
                index = None
            else:
                raise self.error("unsupported group extension '(?'", start)
        else:
            self.ngroups += 1
            index = self.ngroups
        body = self.parse_alternation()
        if self.peek() != ")":
            raise self.error("missing ), unterminated subpattern", start)
        self.pos += 1
        return Group(index, body)

    # -- escapes -----------------------------------------------------------
    def _hex_escape(self, ndigits: int, start: int) -> str:
        digits = self.pattern[self.pos : self.pos + ndigits]
        if len(digits) != ndigits or any(d not in _HEXDIGITS for d in digits):
            raise self.error("incomplete hex escape", start)
        self.pos += ndigits
        code = int(digits, 16)
        if code > 0x10FFFF:
            raise self.error("bad escape (code point out of range)", start)
        return chr(code)

    def _octal_tail(self, first: str, start: int) -> str:
        digits = first
        while len(digits) < 3 and (c := self.peek()) is not None and c in _OCTDIGITS:
            digits += c
            self.pos += 1
        code = int(digits, 8)
        if code > 0o377:
            raise self.error("octal escape value outside of range 0-0o377", start)
        return chr(code)

    def _common_escape(self, c: str, start: int) -> str | None:
        """Escapes shared by both contexts. Returns the literal char or None."""
        if c in _SIMPLE_ESCAPES:
            return _SIMPLE_ESCAPES[c]
        if c == "x":
            return self._hex_escape(2, start)
        if c == "u":
            return self._hex_escape(4, start)
        if c == "U":
            return self._hex_escape(8, start)
        return None

    def parse_escape(self, start: int) -> Node:
        c = self.next()
        if c is None:
            raise self.error("bad escape (end of pattern)", start)
        if c in _CLASS_LETTERS:
            return CharClass(classes=(c,))
        if c in _ANCHOR_ESCAPES:
            return Anchor(_ANCHOR_ESCAPES[c])
        lit = self._common_escape(c, start)
        if lit is not None:
            return Literal(lit)
        if c == "0":
            return Literal(self._octal_tail(c, start))
        if c in _DIGITS:
            # Three octal digits form an octal escape; otherwise a backreference.
            nxt = self.pattern[self.pos : self.pos + 2]
            if c in _OCTDIGITS and len(nxt) == 2 and all(d in _OCTDIGITS for d in nxt):
                self.pos += 2
                code = int(c + nxt, 8)
                if code > 0o377:
                    raise self.error("octal escape value outside of range 0-0o377", start)
                return Literal(chr(code))
            raise self.error("backreferences are not supported", start)
        if c in _ASCII_LETTERS:
            raise self.error(f"bad escape \\{c}", start)
        return Literal(c)

    def parse_class_escape(self, start: int) -> str | CharClass:
        c = self.next()
        if c is None:
            raise self.error("bad escape (end of pattern)", start)
        if c in _CLASS_LETTERS:
            return CharClass(classes=(c,))
        if c == "b":
            return "\b"
        lit = self._common_escape(c, start)
        if lit is not None:
            return lit
        if c in _OCTDIGITS:
            return self._octal_tail(c, start)
        if c in _DIGITS or c in _ASCII_LETTERS:
            raise self.error(f"bad escape \\{c}", start)
        return c

    # -- character sets ----------------------------------------------------
    def parse_class(self, start: int) -> Node:
        negated = False
        if self.peek() == "^":
            self.pos += 1
            negated = True
        chars: set[str] = set()
        ranges: list[tuple[int, int]] = []
        classes: list[str] = []
        first_pos = self.pos

        def add(item: str | CharClass) -> None:
            if isinstance(item, CharClass):
                classes.extend(item.classes)
            else:
                chars.add(item)

        while True:
            item_pos = self.pos
            ch = self.next()
            if ch is None:
                raise self.error("unterminated character set", start)
            if ch == "]" and item_pos != first_pos:
                break
            code1: str | CharClass = self.parse_class_escape(item_pos) if ch == "\\" else ch
            if self.peek() == "-":
                self.pos += 1
                that_pos = self.pos
                that = self.next()
                if that is None:
                    raise self.error("unterminated character set", start)
                if that == "]":
                    add(code1)
                    chars.add("-")
                    break
                code2 = self.parse_class_escape(that_pos) if that == "\\" else that
                if isinstance(code1, CharClass) or isinstance(code2, CharClass):
                    raise self.error("bad character range", item_pos)
                lo, hi = ord(code1), ord(code2)
                if hi < lo:
                    raise self.error("bad character range", item_pos)
                ranges.append((lo, hi))
            else:
                add(code1)
        return CharClass(frozenset(chars), tuple(ranges), tuple(classes), negated)


def parse(pattern: str) -> tuple[Node, int]:
    """Parse ``pattern`` and return ``(ast, number_of_capturing_groups)``."""
    p = Parser(pattern)
    node = p.parse()
    return node, p.ngroups
