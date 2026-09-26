"""Pattern parser: turns a pattern string into a small AST.

The parsing rules follow CPython's ``re._parser`` for the supported subset so
that the same patterns are accepted, rejected, or read as literals.

AST nodes are tuples:

* ``("char", c)``                      a literal character
* ``("any",)``                         ``.`` (anything but ``\\n``)
* ``("set", CharSet)``                 ``[...]`` or a class escape such as ``\\d``
* ``("bol",)`` / ``("eol",)``          ``^`` / ``$``
* ``("group", index | None, node)``    capturing (index >= 1) or non-capturing group
* ``("cat", [nodes])``                 concatenation
* ``("alt", [nodes])``                 alternation
* ``("rep", node, min, max, greedy)``  repetition; ``max`` is ``None`` for unbounded
"""

from __future__ import annotations

from ._charset import DIGIT, NOT_DIGIT, NOT_SPACE, NOT_WORD, SPACE, WORD, CharSet


class RegexError(Exception):
    """Raised for invalid or unsupported patterns."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None):
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)


MAXREPEAT = 4294967295

_DIGITS = frozenset("0123456789")
_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

_CLASS_ESCAPES = {
    "d": DIGIT,
    "D": NOT_DIGIT,
    "w": WORD,
    "W": NOT_WORD,
    "s": SPACE,
    "S": NOT_SPACE,
}

_CHAR_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "f": "\f",
    "v": "\v",
    "a": "\a",
}


class _Parser:
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.pos = 0
        self.ngroups = 0

    # -- helpers -----------------------------------------------------------

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

    def error(self, msg: str, pos: int | None = None) -> RegexError:
        return RegexError(msg, self.pattern, self.pos if pos is None else pos)

    # -- grammar -----------------------------------------------------------

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
                items.append(("set", self.parse_set(start)))
            elif ch == ".":
                items.append(("any",))
            elif ch == "^":
                items.append(("bol",))
            elif ch == "$":
                items.append(("eol",))
            elif ch == "\\":
                items.append(self.parse_escape(start))
            elif ch in "*+?{":
                self.parse_quantifier(ch, start, items)
            else:
                items.append(("char", ch))
        if len(items) == 1:
            return items[0]
        return ("cat", items)

    def parse_group(self, start: int):
        index = None
        if self.accept("?"):
            if not self.accept(":"):
                nxt = self.peek()
                if nxt is None:
                    raise self.error("unexpected end of pattern")
                raise self.error(f"unsupported group extension '(?{nxt}'", start)
        else:
            self.ngroups += 1
            index = self.ngroups
        body = self.parse_alt()
        if not self.accept(")"):
            raise self.error("missing ), unterminated subpattern", start)
        return ("group", index, body)

    def parse_quantifier(self, ch: str, start: int, items: list) -> None:
        if ch == "*":
            lo, hi = 0, None
        elif ch == "+":
            lo, hi = 1, None
        elif ch == "?":
            lo, hi = 0, 1
        else:
            # "{" is only a quantifier when it forms {n}, {n,}, {,m} or {n,m};
            # otherwise it is a literal character (like CPython).
            if self.peek() == "}":
                items.append(("char", "{"))
                return
            lo_s = self._digits()
            if self.accept(","):
                hi_s = self._digits()
            else:
                hi_s = lo_s
            if not self.accept("}"):
                self.pos = start + 1
                items.append(("char", "{"))
                return
            lo = int(lo_s) if lo_s else 0
            hi = int(hi_s) if hi_s else None
            if lo >= MAXREPEAT or (hi is not None and hi >= MAXREPEAT):
                raise self.error("the repetition number is too large", start)
            if hi is not None and hi < lo:
                raise self.error("min repeat greater than max repeat", start)
        if not items or items[-1][0] in ("bol", "eol"):
            raise self.error("nothing to repeat", start)
        if items[-1][0] == "rep":
            raise self.error("multiple repeat", start)
        greedy = True
        if self.accept("?"):
            greedy = False
        elif self.peek() == "+":
            raise self.error("possessive quantifiers are not supported")
        items[-1] = ("rep", items[-1], lo, hi, greedy)

    def _digits(self) -> str:
        begin = self.pos
        while self.peek() is not None and self.peek() in _DIGITS:
            self.pos += 1
        return self.pattern[begin : self.pos]

    def parse_escape(self, start: int):
        ch = self.get()
        if ch is None:
            raise self.error("bad escape (end of pattern)", start)
        if ch in _CLASS_ESCAPES:
            return ("set", _CLASS_ESCAPES[ch])
        if ch in _CHAR_ESCAPES:
            return ("char", _CHAR_ESCAPES[ch])
        if ch in _ASCII_LETTERS or ch in _DIGITS:
            raise self.error(f"bad or unsupported escape \\{ch}", start)
        return ("char", ch)

    def parse_class_escape(self, start: int):
        """Escape inside a set: returns a character or a CharSet."""
        ch = self.get()
        if ch is None:
            raise self.error("bad escape (end of pattern)", start)
        if ch in _CLASS_ESCAPES:
            return _CLASS_ESCAPES[ch]
        if ch in _CHAR_ESCAPES:
            return _CHAR_ESCAPES[ch]
        if ch == "b":
            return "\b"
        if ch in _ASCII_LETTERS or ch in _DIGITS:
            raise self.error(f"bad or unsupported escape \\{ch}", start)
        return ch

    def parse_set(self, start: int) -> CharSet:
        negate = self.accept("^")
        first = self.pos
        chars: set[str] = set()
        ranges: list[tuple[str, str]] = []
        classes: list[CharSet] = []

        def add(item) -> None:
            if isinstance(item, CharSet):
                classes.append(item)
            else:
                chars.add(item)

        while True:
            item_start = self.pos
            ch = self.get()
            if ch is None:
                raise self.error("unterminated character set", start)
            if ch == "]" and item_start != first:
                break
            if ch == "\\":
                code1 = self.parse_class_escape(item_start)
            else:
                code1 = ch
            if self.accept("-"):
                ch2_start = self.pos
                ch2 = self.get()
                if ch2 is None:
                    raise self.error("unterminated character set", start)
                if ch2 == "]":
                    add(code1)
                    chars.add("-")
                    break
                if ch2 == "\\":
                    code2 = self.parse_class_escape(ch2_start)
                else:
                    code2 = ch2
                if isinstance(code1, CharSet) or isinstance(code2, CharSet) or code2 < code1:
                    text = self.pattern[item_start : self.pos]
                    raise self.error(f"bad character range {text}", item_start)
                ranges.append((code1, code2))
            else:
                add(code1)
        return CharSet(chars, ranges, classes, negate)


def parse(pattern: str):
    """Parse ``pattern`` and return ``(ast, number_of_groups)``."""
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a str")
    p = _Parser(pattern)
    ast = p.parse()
    return ast, p.ngroups
