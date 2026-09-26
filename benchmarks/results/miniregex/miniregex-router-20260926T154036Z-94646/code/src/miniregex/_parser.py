"""Pattern parser: turns a pattern string into a small AST.

The grammar and its error cases follow CPython's ``re._parser`` for the supported
subset, so patterns that ``re`` rejects are rejected here too.

AST nodes are tuples:

    ("char", pred)               one character satisfying ``pred(ch)``
    ("lit", c)                   one literal character ``c``
    ("bol",) / ("eol",)          ``^`` / ``$``
    ("seq", [nodes])
    ("alt", [nodes])
    ("group", index_or_None, node)
    ("rep", node, min, max_or_None, lazy)
"""

from __future__ import annotations

from collections.abc import Callable


class RegexError(ValueError):
    """Raised for an invalid (or unsupported) pattern."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None):
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)


MAXREPEAT = 2**32 - 1  # matches re's limit so overflowing counts are rejected alike

_DIGITS = "0123456789"
_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_CONTROL_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v", "a": "\a"}


def _is_digit(ch: str) -> bool:
    return ch.isdecimal()


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _is_space(ch: str) -> bool:
    return ch.isspace()


# Class escapes; semantics equal re's default (Unicode) str behaviour, which
# coincides with the ASCII definitions for ASCII text.
_CLASS_ESCAPES: dict[str, tuple[Callable[[str], bool], bool]] = {
    "d": (_is_digit, False),
    "D": (_is_digit, True),
    "w": (_is_word, False),
    "W": (_is_word, True),
    "s": (_is_space, False),
    "S": (_is_space, True),
}


def _class_pred(name: str) -> Callable[[str], bool]:
    fn, negated = _CLASS_ESCAPES[name]
    if negated:
        return lambda ch: not fn(ch)
    return fn


def any_char(ch: str) -> bool:
    return ch != "\n"


class _Parser:
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.pos = 0
        self.ngroups = 0

    # -- helpers -------------------------------------------------------------

    def error(self, msg: str, pos: int | None = None) -> RegexError:
        return RegexError(msg, self.pattern, self.pos if pos is None else pos)

    def peek(self) -> str | None:
        if self.pos < len(self.pattern):
            return self.pattern[self.pos]
        return None

    def get(self) -> str | None:
        ch = self.peek()
        if ch is not None:
            self.pos += 1
        return ch

    def accept(self, ch: str) -> bool:
        if self.peek() == ch:
            self.pos += 1
            return True
        return False

    # -- grammar -------------------------------------------------------------

    def parse(self):
        node = self.parse_alt()
        if self.pos < len(self.pattern):
            # Only an unmatched ")" can stop parse_alt early at top level.
            raise self.error("unbalanced parenthesis")
        return node

    def parse_alt(self):
        branches = [self.parse_seq()]
        while self.accept("|"):
            branches.append(self.parse_seq())
        if len(branches) == 1:
            return branches[0]
        return ("alt", branches)

    def parse_seq(self):
        items: list = []
        while True:
            ch = self.peek()
            if ch is None or ch in "|)":
                break
            start = self.pos
            self.pos += 1
            if ch == "(":
                items.append(self.parse_group(start))
            elif ch == "[":
                items.append(self.parse_set(start))
            elif ch == ".":
                items.append(("char", any_char))
            elif ch == "^":
                items.append(("bol",))
            elif ch == "$":
                items.append(("eol",))
            elif ch == "\\":
                items.append(self.parse_escape(start))
            elif ch in "*+?":
                self.apply_repeat(items, start, *{"*": (0, None), "+": (1, None), "?": (0, 1)}[ch])
            elif ch == "{":
                bounds = self.parse_braces(start)
                if bounds is None:
                    items.append(("lit", "{"))
                else:
                    self.apply_repeat(items, start, *bounds)
            else:
                items.append(("lit", ch))
        if len(items) == 1:
            return items[0]
        return ("seq", items)

    def parse_braces(self, start: int):
        """Parse ``{n}``, ``{n,}``, ``{,m}``, ``{n,m}`` after the ``{``.

        Returns ``(min, max)`` or ``None`` (leaving the position just after ``{``)
        when the text is not a valid quantifier, in which case ``{`` is a literal.
        """
        here = self.pos
        if self.peek() == "}":
            return None
        lo = hi = ""
        while (c := self.peek()) is not None and c in _DIGITS:
            lo += c
            self.pos += 1
        if self.accept(","):
            while (c := self.peek()) is not None and c in _DIGITS:
                hi += c
                self.pos += 1
        else:
            hi = lo
        if not self.accept("}"):
            self.pos = here
            return None
        mn = int(lo) if lo else 0
        mx = int(hi) if hi else None
        if mn >= MAXREPEAT or (mx is not None and mx >= MAXREPEAT):
            raise self.error("the repetition number is too large", start)
        if mx is not None and mx < mn:
            raise self.error("min repeat greater than max repeat", start + 1)
        return mn, mx

    def apply_repeat(self, items: list, start: int, mn: int, mx: int | None) -> None:
        if not items or items[-1][0] in ("bol", "eol"):
            raise self.error("nothing to repeat", start)
        if items[-1][0] == "rep":
            raise self.error("multiple repeat", start)
        lazy = self.accept("?")
        if self.peek() == "+" and not lazy:
            raise self.error("possessive quantifiers are not supported")
        items[-1] = ("rep", items[-1], mn, mx, lazy)

    def parse_group(self, start: int):
        index = None
        if self.accept("?"):
            if not self.accept(":"):
                raise self.error("unsupported group extension", start + 1)
        else:
            self.ngroups += 1
            index = self.ngroups
        node = self.parse_alt()
        if not self.accept(")"):
            raise self.error("missing ), unterminated subpattern", start)
        return ("group", index, node)

    def parse_escape(self, start: int):
        ch = self.get()
        if ch is None:
            raise self.error("bad escape (end of pattern)", start)
        if ch in _CLASS_ESCAPES:
            return ("char", _class_pred(ch))
        if ch in _CONTROL_ESCAPES:
            return ("lit", _CONTROL_ESCAPES[ch])
        if ch in _ASCII_LETTERS or ch in _DIGITS:
            raise self.error(f"bad or unsupported escape \\{ch}", start)
        return ("lit", ch)

    def parse_set_escape(self, start: int):
        """Escape inside ``[...]``: returns ("lit", c) or ("char", pred)."""
        ch = self.get()
        if ch is None:
            raise self.error("unterminated character set", start)
        if ch in _CLASS_ESCAPES:
            return ("char", _class_pred(ch))
        if ch in _CONTROL_ESCAPES:
            return ("lit", _CONTROL_ESCAPES[ch])
        if ch == "b":
            return ("lit", "\b")
        if ch in _ASCII_LETTERS or ch in _DIGITS:
            raise self.error(f"bad or unsupported escape \\{ch}", self.pos - 2)
        return ("lit", ch)

    def parse_set(self, start: int):
        negated = self.accept("^")
        first = self.pos
        chars: set[str] = set()
        ranges: list[tuple[str, str]] = []
        preds: list[Callable[[str], bool]] = []

        def add(item) -> None:
            if item[0] == "lit":
                chars.add(item[1])
            else:
                preds.append(item[1])

        while True:
            item_start = self.pos
            ch = self.get()
            if ch is None:
                raise self.error("unterminated character set", start)
            if ch == "]" and item_start != first:
                break
            item1 = self.parse_set_escape(start) if ch == "\\" else ("lit", ch)
            if self.accept("-"):
                ch2 = self.get()
                if ch2 is None:
                    raise self.error("unterminated character set", start)
                if ch2 == "]":
                    add(item1)
                    chars.add("-")
                    break
                item2 = self.parse_set_escape(start) if ch2 == "\\" else ("lit", ch2)
                if item1[0] != "lit" or item2[0] != "lit":
                    raise self.error("bad character range", item_start)
                lo, hi = item1[1], item2[1]
                if hi < lo:
                    raise self.error("bad character range", item_start)
                ranges.append((lo, hi))
            else:
                add(item1)

        frozen = frozenset(chars)
        range_list = tuple(ranges)
        pred_list = tuple(preds)

        def member(c: str) -> bool:
            if c in frozen:
                return True
            for lo, hi in range_list:
                if lo <= c <= hi:
                    return True
            for p in pred_list:
                if p(c):
                    return True
            return False

        if negated:
            return ("char", lambda c: not member(c))
        return ("char", member)


def parse(pattern: str):
    """Parse ``pattern``; returns ``(ast, number_of_groups)``."""
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a str")
    parser = _Parser(pattern)
    ast = parser.parse()
    return ast, parser.ngroups
