"""Pattern parser: turns a pattern string into a small AST.

The grammar and error cases follow CPython's ``re._parser`` for the supported
subset of the syntax.

AST nodes are tuples:

* ``("lit", str)``                      -- one or more literal characters
* ``("set", CharSet)``                  -- a single character from a set
* ``("seq", [node, ...])``
* ``("alt", [node, ...])``
* ``("group", index_or_None, node)``    -- capturing when index is an int
* ``("rep", min, max_or_None, lazy, node)``
* ``("at", kind)``                      -- "bol", "eol", "bos", "eos"
"""

from __future__ import annotations

from dataclasses import dataclass


class RegexError(ValueError):
    """Raised for invalid or unsupported patterns."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None):
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)


MAXREPEAT = 4294967295

DIGITS = frozenset("0123456789")
OCTDIGITS = frozenset("01234567")
HEXDIGITS = frozenset("0123456789abcdefABCDEF")
ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

DIGIT_CHARS = frozenset("0123456789")
WORD_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
SPACE_CHARS = frozenset(" \t\n\r\f\v")

# class escape -> (character set, negated)
CATEGORIES = {
    "d": (DIGIT_CHARS, False),
    "D": (DIGIT_CHARS, True),
    "w": (WORD_CHARS, False),
    "W": (WORD_CHARS, True),
    "s": (SPACE_CHARS, False),
    "S": (SPACE_CHARS, True),
}

SIMPLE_ESCAPES = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
}


@dataclass(frozen=True)
class CharSet:
    """A set of characters: literal chars, ranges and (possibly negated) categories."""

    chars: frozenset[str]
    ranges: tuple[tuple[int, int], ...]
    categories: tuple[tuple[frozenset[str], bool], ...]
    negated: bool

    def __contains__(self, ch: str) -> bool:
        hit = ch in self.chars
        if not hit:
            code = ord(ch)
            for lo, hi in self.ranges:
                if lo <= code <= hi:
                    hit = True
                    break
        if not hit:
            for members, neg in self.categories:
                if (ch in members) != neg:
                    hit = True
                    break
        return hit != self.negated


ANY_BUT_NEWLINE = CharSet(frozenset("\n"), (), (), True)


def category_set(letter: str) -> CharSet:
    members, neg = CATEGORIES[letter]
    return CharSet(members, (), (), neg)


class _Source:
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.index = 0

    @property
    def next(self) -> str | None:
        if self.index < len(self.pattern):
            return self.pattern[self.index]
        return None

    def get(self) -> str | None:
        ch = self.next
        if ch is not None:
            self.index += 1
        return ch

    def match(self, ch: str) -> bool:
        if self.next == ch:
            self.index += 1
            return True
        return False

    def error(self, msg: str, offset: int = 0) -> RegexError:
        return RegexError(msg, self.pattern, self.index - offset)


class Parser:
    def __init__(self, pattern: str):
        if not isinstance(pattern, str):
            raise TypeError("pattern must be a str")
        self.src = _Source(pattern)
        self.groups = 0

    def parse(self):
        node = self._alternation(nested=False)
        if self.src.next is not None:
            raise self.src.error("unbalanced parenthesis")
        return node

    # alternation := sequence ('|' sequence)*
    def _alternation(self, nested: bool):
        branches = [self._sequence()]
        while self.src.match("|"):
            branches.append(self._sequence())
        if nested and self.src.next != ")":
            raise self.src.error("missing ), unterminated subpattern")
        if len(branches) == 1:
            return branches[0]
        return ("alt", branches)

    def _sequence(self):
        src = self.src
        items: list = []
        while True:
            ch = src.next
            if ch is None or ch in "|)":
                break
            start = src.index
            src.get()
            if ch == "\\":
                items.append(self._escape())
            elif ch == "[":
                items.append(("set", self._charset(start)))
            elif ch == ".":
                items.append(("set", ANY_BUT_NEWLINE))
            elif ch == "^":
                items.append(("at", "bol"))
            elif ch == "$":
                items.append(("at", "eol"))
            elif ch == "(":
                items.append(self._group(start))
            elif ch in "*+?{":
                rep = self._repeat_bounds(ch)
                if rep is None:  # '{' that does not start a valid repeat
                    items.append(("lit", "{"))
                    continue
                lo, hi = rep
                if not items or items[-1][0] == "at":
                    raise RegexError("nothing to repeat", src.pattern, start)
                if items[-1][0] == "rep":
                    raise RegexError("multiple repeat", src.pattern, start)
                lazy = src.match("?")
                if src.next == "+":
                    raise src.error("possessive quantifiers are not supported")
                item = items.pop()
                if item[0] == "group" and item[1] is None:
                    item = item[2]
                items.append(("rep", lo, hi, lazy, item))
            else:
                items.append(("lit", ch))
        return _make_seq(items)

    def _repeat_bounds(self, ch: str):
        src = self.src
        if ch == "*":
            return 0, None
        if ch == "+":
            return 1, None
        if ch == "?":
            return 0, 1
        # '{'
        here = src.index
        if src.next == "}":
            return None
        lo = hi = ""
        while src.next is not None and src.next in DIGITS:
            lo += src.get()
        if src.match(","):
            while src.next is not None and src.next in DIGITS:
                hi += src.get()
        else:
            hi = lo
        if not src.match("}"):
            src.index = here
            return None
        low = 0
        high = None
        if lo:
            low = int(lo)
            if low >= MAXREPEAT:
                raise RegexError("the repetition number is too large", src.pattern, here)
        if hi:
            high = int(hi)
            if high >= MAXREPEAT:
                raise RegexError("the repetition number is too large", src.pattern, here)
            if high < low:
                raise RegexError("min repeat greater than max repeat", src.pattern, here)
        return low, high

    def _group(self, start: int):
        src = self.src
        index = None
        if src.match("?"):
            if not src.match(":"):
                raise RegexError("unsupported group extension", src.pattern, start)
        else:
            self.groups += 1
            index = self.groups
        body = self._alternation(nested=True)
        if not src.match(")"):
            raise RegexError("missing ), unterminated subpattern", src.pattern, start)
        return ("group", index, body)

    def _escape(self):
        src = self.src
        start = src.index - 1
        ch = src.get()
        if ch is None:
            raise src.error("bad escape (end of pattern)", 1)
        if ch in CATEGORIES:
            return ("set", category_set(ch))
        if ch == "A":
            return ("at", "bos")
        if ch == "Z":
            return ("at", "eos")
        if ch == "b":
            raise RegexError("\\b is not supported", src.pattern, start)
        if ch == "0":
            digits = ""
            while len(digits) < 2 and src.next is not None and src.next in OCTDIGITS:
                digits += src.get()
            return ("lit", chr(int(digits or "0", 8)))
        if ch in DIGITS:
            raise RegexError("backreferences are not supported", src.pattern, start)
        return ("lit", self._common_escape(ch, start))

    def _common_escape(self, ch: str, start: int) -> str:
        """Escapes that mean a single literal character, inside or outside sets."""
        src = self.src
        if ch in SIMPLE_ESCAPES:
            return SIMPLE_ESCAPES[ch]
        if ch in "xuU":
            width = {"x": 2, "u": 4, "U": 8}[ch]
            digits = ""
            while len(digits) < width and src.next is not None and src.next in HEXDIGITS:
                digits += src.get()
            if len(digits) != width:
                raise RegexError(f"incomplete escape \\{ch}{digits}", src.pattern, start)
            code = int(digits, 16)
            if code > 0x10FFFF:
                raise RegexError(f"bad escape \\{ch}{digits}", src.pattern, start)
            return chr(code)
        if ch in ASCII_LETTERS:
            raise RegexError(f"bad escape \\{ch}", src.pattern, start)
        return ch

    def _class_escape(self, start: int):
        """Parse an escape inside a set. Returns a literal char or a CharSet."""
        src = self.src
        ch = src.get()
        if ch is None:
            raise src.error("bad escape (end of pattern)", 1)
        if ch in CATEGORIES:
            return category_set(ch)
        if ch in OCTDIGITS:
            digits = ch
            while len(digits) < 3 and src.next is not None and src.next in OCTDIGITS:
                digits += src.get()
            code = int(digits, 8)
            if code > 0o377:
                raise RegexError(f"octal escape value \\{digits} outside of range 0-0o377", src.pattern, start)
            return chr(code)
        if ch in DIGITS:
            raise RegexError(f"bad escape \\{ch}", src.pattern, start)
        return self._common_escape(ch, start)

    def _charset(self, start: int) -> CharSet:
        src = self.src
        negated = src.match("^")
        chars: set[str] = set()
        ranges: list[tuple[int, int]] = []
        categories: list[tuple[frozenset[str], bool]] = []
        empty = True

        def add(item) -> None:
            if isinstance(item, CharSet):
                categories.append(item.categories[0] if item.categories else (item.chars, item.negated))
            else:
                chars.add(item)

        while True:
            here = src.index
            ch = src.get()
            if ch is None:
                raise RegexError("unterminated character set", src.pattern, start)
            if ch == "]" and not empty:
                break
            empty = False
            item = self._class_escape(here) if ch == "\\" else ch
            if src.match("-"):
                that_pos = src.index
                that = src.get()
                if that is None:
                    raise RegexError("unterminated character set", src.pattern, start)
                if that == "]":
                    add(item)
                    chars.add("-")
                    break
                other = self._class_escape(that_pos) if that == "\\" else that
                if isinstance(item, CharSet) or isinstance(other, CharSet):
                    raise RegexError("bad character range", src.pattern, here)
                if ord(other) < ord(item):
                    raise RegexError("bad character range", src.pattern, here)
                ranges.append((ord(item), ord(other)))
            else:
                add(item)
        return CharSet(frozenset(chars), tuple(ranges), tuple(categories), negated)


def _make_seq(items: list):
    merged: list = []
    for item in items:
        if item[0] == "lit" and merged and merged[-1][0] == "lit":
            merged[-1] = ("lit", merged[-1][1] + item[1])
        else:
            merged.append(item)
    if len(merged) == 1:
        return merged[0]
    return ("seq", merged)


def parse(pattern: str):
    """Parse ``pattern`` and return ``(ast, number_of_groups)``."""
    parser = Parser(pattern)
    ast = parser.parse()
    return ast, parser.groups
