"""Recursive-descent parser: pattern string -> matcher node tree."""

from __future__ import annotations

from .errors import RegexError
from .nodes import Alt as AltNode
from .nodes import (
    AnyChar,
    CharPredicate,
    Concat,
    Empty,
    EndAnchor,
    Group,
    Literal,
    NonCapturingGroup,
    Repeat,
    StartAnchor,
)

_DIGIT = frozenset("0123456789")
_WORD = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
)
_SPACE = frozenset(" \t\n\r\f\v")

_CLASS_PREDICATES = {
    "d": lambda c: c in _DIGIT,
    "D": lambda c: c not in _DIGIT,
    "w": lambda c: c in _WORD,
    "W": lambda c: c not in _WORD,
    "s": lambda c: c in _SPACE,
    "S": lambda c: c not in _SPACE,
}

_SIMPLE_ESCAPES = set(".\\*+?()[]{}|^$-")


class Parser:
    def __init__(self, pattern):
        self.pattern = pattern
        self.pos = 0
        self.n = len(pattern)
        self.group_count = 0

    def error(self, msg):
        raise RegexError(f"{msg} at position {self.pos}")

    def peek(self):
        if self.pos < self.n:
            return self.pattern[self.pos]
        return None

    def advance(self):
        ch = self.pattern[self.pos]
        self.pos += 1
        return ch

    def parse(self):
        node = self.parse_alt()
        if self.pos != self.n:
            self.error(f"unexpected {self.pattern[self.pos]!r}")
        return node, self.group_count

    # alternation: concat ('|' concat)*
    def parse_alt(self):
        branches = [self.parse_concat()]
        while self.peek() == "|":
            self.advance()
            branches.append(self.parse_concat())
        if len(branches) == 1:
            return branches[0]
        return AltNode(branches)

    def parse_concat(self):
        nodes = []
        while self.pos < self.n and self.peek() not in ("|", ")"):
            nodes.append(self.parse_repeat())
        if not nodes:
            return Empty()
        if len(nodes) == 1:
            return nodes[0]
        return Concat(nodes)

    def parse_repeat(self):
        start_pos = self.pos
        atom = self.parse_atom()
        quant = self.try_parse_quantifier()
        if quant is None:
            return atom
        min_count, max_count = quant
        lazy = False
        if self.peek() == "?":
            self.advance()
            lazy = True
        if isinstance(atom, Repeat):
            self.pos = start_pos
            self.error("multiple repeat")
        return Repeat(atom, min_count, max_count, lazy)

    def try_parse_quantifier(self):
        ch = self.peek()
        if ch == "*":
            self.advance()
            return (0, None)
        if ch == "+":
            self.advance()
            return (1, None)
        if ch == "?":
            self.advance()
            return (0, 1)
        if ch == "{":
            return self.try_parse_brace_quantifier()
        return None

    def try_parse_brace_quantifier(self):
        save = self.pos
        self.advance()  # consume '{'
        digits1 = self._read_digits()
        has_comma = False
        digits2 = ""
        if self.peek() == ",":
            has_comma = True
            self.advance()
            digits2 = self._read_digits()
        if self.peek() != "}":
            self.pos = save
            return None
        if not digits1 and not has_comma:
            self.pos = save
            return None
        self.advance()  # consume '}'

        min_count = int(digits1) if digits1 else 0
        if has_comma:
            max_count = int(digits2) if digits2 else None
        else:
            max_count = min_count
        if max_count is not None and min_count > max_count:
            self.error("min repeat greater than max repeat")
        return (min_count, max_count)

    def _read_digits(self):
        start = self.pos
        while self.pos < self.n and self.pattern[self.pos] in _DIGIT:
            self.pos += 1
        return self.pattern[start:self.pos]

    def parse_atom(self):
        ch = self.peek()
        if ch is None:
            self.error("unexpected end of pattern")
        if ch == "(":
            return self.parse_group()
        if ch in ("*", "+", "?"):
            self.error("nothing to repeat")
        if ch == "{":
            quant_save = self.pos
            quant = self.try_parse_brace_quantifier()
            self.pos = quant_save
            if quant is not None:
                self.error("nothing to repeat")
        if ch == ")":
            self.error("unbalanced parenthesis")
        if ch == "]":
            self.advance()
            return Literal("]")
        if ch == ".":
            self.advance()
            return AnyChar()
        if ch == "^":
            self.advance()
            return StartAnchor()
        if ch == "$":
            self.advance()
            return EndAnchor()
        if ch == "[":
            return self.parse_class()
        if ch == "\\":
            return self.parse_escape()
        self.advance()
        return Literal(ch)

    def parse_group(self):
        self.advance()  # consume '('
        capturing = True
        if self.peek() == "?":
            self.advance()
            if self.peek() == ":":
                self.advance()
                capturing = False
            else:
                self.error("unsupported group syntax")
        index = None
        if capturing:
            self.group_count += 1
            index = self.group_count
        inner = self.parse_alt()
        if self.peek() != ")":
            self.error("missing closing parenthesis")
        self.advance()
        if capturing:
            return Group(index, inner)
        return NonCapturingGroup(inner)

    def parse_escape(self):
        self.advance()  # consume backslash
        ch = self.peek()
        if ch is None:
            self.error("bad escape at end of pattern")
        if ch in _CLASS_PREDICATES:
            self.advance()
            return CharPredicate(_CLASS_PREDICATES[ch])
        if ch in _SIMPLE_ESCAPES:
            self.advance()
            return Literal(ch)
        self.error(f"bad escape \\{ch}")

    def parse_class(self):
        self.advance()  # consume '['
        negate = False
        if self.peek() == "^":
            negate = True
            self.advance()

        chars = set()
        ranges = []
        predicates = []

        first = True
        while True:
            ch = self.peek()
            if ch is None:
                self.error("unterminated character set")
            if ch == "]" and not first:
                break
            first = False

            if ch == "]":
                # first char literal ']'
                self.advance()
                chars.add("]")
                continue

            lo, lo_is_literal = self._read_class_item(chars, predicates)
            if lo is None:
                continue
            # Check for range
            if (
                lo_is_literal
                and self.peek() == "-"
                and self.pos + 1 < self.n
                and self.pattern[self.pos + 1] != "]"
            ):
                self.advance()  # consume '-'
                hi, hi_is_literal = self._read_class_item(chars, predicates, consume_only=True)
                if not hi_is_literal:
                    self.error("bad character range")
                if lo > hi:
                    self.error("bad character range")
                ranges.append((lo, hi))
            else:
                chars.add(lo)

        if self.peek() != "]":
            self.error("unterminated character set")
        self.advance()  # consume ']'

        def predicate(c, chars=chars, ranges=ranges, predicates=predicates):
            if c in chars:
                return True
            for lo, hi in ranges:
                if lo <= c <= hi:
                    return True
            for p in predicates:
                if p(c):
                    return True
            return False

        if negate:
            base = predicate
            return CharPredicate(lambda c, base=base: not base(c))
        return CharPredicate(predicate)

    def _read_class_item(self, chars, predicates, consume_only=False):
        """Reads a single item inside a char set: a literal char, an escaped
        char, or a class shorthand. Returns (value, is_literal). If the item
        is a class shorthand it is added to ``predicates`` and (None, False)
        is returned (unless ``consume_only``, used for range endpoints, in
        which case it's an error at the call site since None is returned).
        """
        ch = self.advance()
        if ch != "\\":
            return ch, True
        esc = self.peek()
        if esc is None:
            self.error("bad escape at end of pattern")
        if esc in _CLASS_PREDICATES:
            self.advance()
            predicates.append(_CLASS_PREDICATES[esc])
            return None, False
        if esc in _SIMPLE_ESCAPES:
            self.advance()
            return esc, True
        self.error(f"bad escape \\{esc}")
        return None, False
