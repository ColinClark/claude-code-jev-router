"""Pattern parser: turns a pattern string into a small syntax tree.

The accepted syntax and the error cases follow CPython's ``re._parser`` so that a
pattern is rejected here exactly when ``re`` rejects it (for the supported subset).

Tree nodes are tuples:

* ``("char", ch)``                 a literal character
* ``("set", matcher)``             a single-character test (``.``, classes, ``[...]``)
* ``("at", kind)``                 a zero-width anchor
* ``("group", index_or_None, node)``
* ``("cat", [nodes])``
* ``("alt", [nodes])``
* ``("repeat", node, min, max_or_None, greedy)``
"""

from __future__ import annotations

from collections.abc import Callable

MAXREPEAT = 4294967295
MAXCODE = 0x10FFFF

DIGITS = frozenset("0123456789")
OCTDIGITS = frozenset("01234567")
HEXDIGITS = frozenset("0123456789abcdefABCDEF")
ASCIILETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

SIMPLE_ESCAPES = {
    "a": "\a",
    "b": "\b",  # only inside sets; outside, \b is a word boundary
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
}

AT_BEGINNING = "beginning"
AT_END = "end"
AT_BEGINNING_STRING = "beginning_string"
AT_END_STRING = "end_string"
AT_BOUNDARY = "boundary"
AT_NON_BOUNDARY = "non_boundary"


class RegexError(ValueError):
    """Raised for invalid or unsupported patterns."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None):
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)


# --- character predicates (Unicode semantics, like ``re`` on str patterns) -----------


def is_digit(ch: str) -> bool:
    return ch.isdecimal()


def is_space(ch: str) -> bool:
    return ch.isspace()


def is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def not_digit(ch: str) -> bool:
    return not ch.isdecimal()


def not_space(ch: str) -> bool:
    return not ch.isspace()


def not_word(ch: str) -> bool:
    return not (ch.isalnum() or ch == "_")


def any_but_newline(ch: str) -> bool:
    return ch != "\n"


CATEGORIES: dict[str, Callable[[str], bool]] = {
    "d": is_digit,
    "D": not_digit,
    "s": is_space,
    "S": not_space,
    "w": is_word,
    "W": not_word,
}


def make_set(
    chars: set[str],
    ranges: list[tuple[int, int]],
    categories: list[Callable[[str], bool]],
    negate: bool,
) -> Callable[[str], bool]:
    """Build a predicate for a ``[...]`` set."""
    frozen = frozenset(chars)
    ranges = list(ranges)
    categories = list(categories)

    if not ranges and not categories:
        if negate:
            return lambda ch: ch not in frozen
        return frozen.__contains__

    def test(ch: str) -> bool:
        if ch in frozen:
            return not negate
        code = ord(ch)
        for lo, hi in ranges:
            if lo <= code <= hi:
                return not negate
        for cat in categories:
            if cat(ch):
                return not negate
        return negate

    return test


# --- parser ---------------------------------------------------------------------------


class _Parser:
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.pos = 0
        self.ngroups = 0

    # low-level helpers

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

    def match(self, ch: str) -> bool:
        if self.peek() == ch:
            self.pos += 1
            return True
        return False

    def getwhile(self, n: int, charset: frozenset[str]) -> str:
        out = ""
        while len(out) < n and self.peek() is not None and self.peek() in charset:
            out += self.get()  # type: ignore[operator]
        return out

    # grammar

    def parse(self):
        node = self.parse_alternation()
        if self.pos < len(self.pattern):
            # the only way to stop early at top level is an unmatched ')'
            raise self.error("unbalanced parenthesis")
        return node

    def parse_alternation(self):
        branches = [self.parse_sequence()]
        while self.match("|"):
            branches.append(self.parse_sequence())
        if len(branches) == 1:
            return branches[0]
        return ("alt", branches)

    def parse_sequence(self):
        items: list[tuple] = []
        while True:
            ch = self.peek()
            if ch is None or ch == "|" or ch == ")":
                break
            start = self.pos
            self.pos += 1

            if ch in "*+?{":
                quant = self.parse_quantifier(ch, start)
                if quant is None:
                    # a '{' that does not start a valid quantifier is a literal
                    items.append(("char", "{"))
                    continue
                lo, hi = quant
                if not items or items[-1][0] == "at":
                    raise self.error("nothing to repeat", start)
                if items[-1][0] == "repeat":
                    raise self.error("multiple repeat", start)
                greedy = True
                if self.match("?"):
                    greedy = False
                elif self.peek() == "+":
                    raise self.error("possessive quantifiers are not supported", self.pos)
                items[-1] = ("repeat", items[-1], lo, hi, greedy)
                continue

            if ch == ".":
                items.append(("set", any_but_newline))
            elif ch == "^":
                items.append(("at", AT_BEGINNING))
            elif ch == "$":
                items.append(("at", AT_END))
            elif ch == "[":
                items.append(self.parse_set(start))
            elif ch == "(":
                items.append(self.parse_group(start))
            elif ch == "\\":
                items.append(self.parse_escape(start))
            else:
                items.append(("char", ch))

        if len(items) == 1:
            return items[0]
        return ("cat", items)

    def parse_quantifier(self, ch: str, start: int):
        if ch == "*":
            return 0, None
        if ch == "+":
            return 1, None
        if ch == "?":
            return 0, 1
        # ch == "{"
        if self.peek() == "}":
            return None
        lo = self.getwhile(len(self.pattern), DIGITS)
        if self.match(","):
            hi = self.getwhile(len(self.pattern), DIGITS)
        else:
            hi = lo
        if not self.match("}"):
            self.pos = start + 1
            return None
        min_ = int(lo) if lo else 0
        max_ = int(hi) if hi else None
        if min_ >= MAXREPEAT or (max_ is not None and max_ >= MAXREPEAT):
            raise self.error("the repetition number is too large", start)
        if max_ is not None and max_ < min_:
            raise self.error("min repeat greater than max repeat", start)
        return min_, max_

    def parse_group(self, start: int):
        index: int | None
        if self.match("?"):
            ext = self.get()
            if ext is None:
                raise self.error("unexpected end of pattern")
            if ext != ":":
                raise self.error(f"group extension '(?{ext}' is not supported", start)
            index = None
        else:
            self.ngroups += 1
            index = self.ngroups
        body = self.parse_alternation()
        if not self.match(")"):
            raise self.error("missing ), unterminated subpattern", start)
        return ("group", index, body)

    def parse_escape(self, start: int):
        ch = self.get()
        if ch is None:
            raise self.error("bad escape (end of pattern)", start)
        if ch in CATEGORIES:
            return ("set", CATEGORIES[ch])
        if ch == "A":
            return ("at", AT_BEGINNING_STRING)
        if ch == "Z":
            return ("at", AT_END_STRING)
        if ch == "b":
            return ("at", AT_BOUNDARY)
        if ch == "B":
            return ("at", AT_NON_BOUNDARY)
        if ch == "0":
            digits = "0" + self.getwhile(2, OCTDIGITS)
            return ("char", chr(int(digits, 8)))
        if ch in DIGITS:
            # octal escape (three octal digits) or a group reference
            nxt = self.peek()
            if nxt is not None and nxt in DIGITS:
                self.pos += 1
                third = self.peek()
                if (
                    ch in OCTDIGITS
                    and nxt in OCTDIGITS
                    and third is not None
                    and (third in OCTDIGITS)
                ):
                    self.pos += 1
                    value = int(ch + nxt + third, 8)
                    if value > 0o377:
                        raise self.error("octal escape value outside of range 0-0o377", start)
                    return ("char", chr(value))
            raise self.error("backreferences are not supported", start)
        return ("char", self.common_escape(ch, start))

    def common_escape(self, ch: str, start: int) -> str:
        """Escapes shared by the pattern body and sets; returns the literal character."""
        if ch in SIMPLE_ESCAPES:
            return SIMPLE_ESCAPES[ch]
        if ch == "x":
            return self.hex_escape(2, start)
        if ch == "u":
            return self.hex_escape(4, start)
        if ch == "U":
            return self.hex_escape(8, start)
        if ch == "N":
            raise self.error("named unicode escapes are not supported", start)
        if ch in ASCIILETTERS or ch in DIGITS:
            raise self.error(f"bad escape \\{ch}", start)
        return ch

    def hex_escape(self, width: int, start: int) -> str:
        digits = self.getwhile(width, HEXDIGITS)
        if len(digits) != width:
            raise self.error(f"incomplete escape \\{self.pattern[start + 1]}{digits}", start)
        value = int(digits, 16)
        if value > MAXCODE:
            raise self.error("bad escape", start)
        return chr(value)

    def parse_set_item(self, this: str, start: int):
        """Return ("lit", ch) or ("cat", predicate) for one set member."""
        if this != "\\":
            return ("lit", this)
        ch = self.get()
        if ch is None:
            raise self.error("bad escape (end of pattern)", start)
        if ch in CATEGORIES:
            return ("cat", CATEGORIES[ch])
        if ch in OCTDIGITS:
            digits = ch + self.getwhile(2, OCTDIGITS)
            value = int(digits, 8)
            if value > 0o377:
                raise self.error("octal escape value outside of range 0-0o377", start)
            return ("lit", chr(value))
        return ("lit", self.common_escape(ch, start))

    def parse_set(self, set_start: int):
        negate = self.match("^")
        chars: set[str] = set()
        ranges: list[tuple[int, int]] = []
        categories: list[Callable[[str], bool]] = []
        first = True
        while True:
            item_start = self.pos
            this = self.get()
            if this is None:
                raise self.error("unterminated character set", set_start)
            if this == "]" and not first:
                break
            first = False
            code1 = self.parse_set_item(this, item_start)
            if self.match("-"):
                that_start = self.pos
                that = self.get()
                if that is None:
                    raise self.error("unterminated character set", set_start)
                if that == "]":
                    self._add_set_item(code1, chars, categories)
                    chars.add("-")
                    break
                code2 = self.parse_set_item(that, that_start)
                if code1[0] != "lit" or code2[0] != "lit":
                    raise self.error("bad character range", item_start)
                lo, hi = ord(code1[1]), ord(code2[1])
                if hi < lo:
                    raise self.error("bad character range", item_start)
                ranges.append((lo, hi))
            else:
                self._add_set_item(code1, chars, categories)
        return ("set", make_set(chars, ranges, categories, negate))

    @staticmethod
    def _add_set_item(item, chars, categories) -> None:
        if item[0] == "lit":
            chars.add(item[1])
        else:
            categories.append(item[1])


def parse(pattern: str):
    """Parse ``pattern``; return ``(tree, number_of_groups)``."""
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a str")
    parser = _Parser(pattern)
    tree = parser.parse()
    return tree, parser.ngroups
