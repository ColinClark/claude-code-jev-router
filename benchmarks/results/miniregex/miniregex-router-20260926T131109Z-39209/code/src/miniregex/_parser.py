"""Pattern parser: turns a pattern string into a small AST.

The grammar and error behaviour follow CPython's ``re._parser`` (sre_parse) for
the supported subset, so that patterns accepted or rejected by ``re`` are
accepted or rejected here as well.

AST nodes are tuples:

* ``(CHAR, ch)``                      a literal character
* ``(ANY,)``                          ``.`` (anything except ``\\n``)
* ``(SET, CharSet)``                  a character class
* ``(AT, kind)``                      a zero-width assertion
* ``(GROUP, index_or_None, node)``    capturing / non-capturing group
* ``(SEQ, [nodes])``                  concatenation
* ``(ALT, [nodes])``                  alternation (ordered)
* ``(REPEAT, lo, hi_or_None, greedy, node)``
"""

from __future__ import annotations

import sys
import unicodedata

CHAR = "char"
ANY = "any"
SET = "set"
AT = "at"
GROUP = "group"
SEQ = "seq"
ALT = "alt"
REPEAT = "repeat"

# Assertion kinds
AT_BEGINNING = "beginning"  # ^
AT_END = "end"  # $
AT_BEGINNING_STRING = "beginning_string"  # \A
AT_END_STRING = "end_string"  # \Z
AT_BOUNDARY = "boundary"  # \b
AT_NON_BOUNDARY = "non_boundary"  # \B

MAXREPEAT = 4294967295

DIGITS = frozenset("0123456789")
OCTDIGITS = frozenset("01234567")
HEXDIGITS = frozenset("0123456789abcdefABCDEF")
ASCIILETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

ESCAPES = {
    "\\a": "\a",
    "\\b": "\b",
    "\\f": "\f",
    "\\n": "\n",
    "\\r": "\r",
    "\\t": "\t",
    "\\v": "\v",
    "\\\\": "\\",
}

# Category escapes usable both inside and outside of sets.
CLASS_CATEGORIES = {"\\d", "\\D", "\\s", "\\S", "\\w", "\\W"}

AT_ESCAPES = {
    "\\A": AT_BEGINNING_STRING,
    "\\Z": AT_END_STRING,
    "\\b": AT_BOUNDARY,
    "\\B": AT_NON_BOUNDARY,
}
if sys.version_info >= (3, 14):
    AT_ESCAPES["\\z"] = AT_END_STRING


class RegexError(Exception):
    """Raised for invalid regular expressions."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None):
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pattern is not None and pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)


def is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _cat_test(cat: str):
    if cat == "d":
        return str.isdecimal, False
    if cat == "D":
        return str.isdecimal, True
    if cat == "s":
        return str.isspace, False
    if cat == "S":
        return str.isspace, True
    if cat == "w":
        return is_word, False
    if cat == "W":
        return is_word, True
    raise AssertionError(cat)


class CharSet:
    """A character class: literal chars, ranges and categories, maybe negated."""

    __slots__ = ("chars", "ranges", "categories", "negate")

    def __init__(self, negate: bool = False):
        self.chars: set[str] = set()
        self.ranges: list[tuple[int, int]] = []
        self.categories: list[str] = []
        self.negate = negate

    def make_test(self):
        chars = frozenset(self.chars)
        ranges = tuple(self.ranges)
        cats = tuple(_cat_test(c) for c in self.categories)
        negate = self.negate

        if not ranges and not cats:
            if negate:
                return lambda ch: ch not in chars
            return chars.__contains__

        def test(ch: str) -> bool:
            if ch in chars:
                return not negate
            o = ord(ch)
            for lo, hi in ranges:
                if lo <= o <= hi:
                    return not negate
            for fn, inverted in cats:
                if fn(ch) != inverted:
                    return not negate
            return negate

        return test


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
        """Return the next token (an escape counts as one token)."""
        p = self.pattern
        i = self.index
        if i >= len(p):
            return None
        ch = p[i]
        if ch == "\\":
            if i + 1 >= len(p):
                raise RegexError("bad escape (end of pattern)", p, i)
            self.index = i + 2
            return p[i : i + 2]
        self.index = i + 1
        return ch

    def match(self, ch: str) -> bool:
        if self.next == ch:
            self.index += 1
            return True
        return False

    def getwhile(self, n: int, charset) -> str:
        result = ""
        for _ in range(n):
            c = self.next
            if c is None or c not in charset:
                break
            result += c
            self.index += 1
        return result

    def getuntil(self, terminator: str, name: str) -> str:
        result = ""
        while True:
            c = self.next
            self.index += 1
            if c is None:
                if not result:
                    raise RegexError("missing " + name, self.pattern, self.index - 1)
                raise RegexError(
                    f"missing {terminator}, unterminated name", self.pattern, self.index - 1
                )
            if c == terminator:
                if not result:
                    raise RegexError("missing " + name, self.pattern, self.index - 1)
                break
            result += c
        return result

    def error(self, msg: str, offset: int = 0) -> RegexError:
        return RegexError(msg, self.pattern, self.index - offset)


def _unicode_escape(source: _Source, escape: str):
    """Handle \\x, \\u, \\U, \\N escapes. Returns a char or None if not applicable."""
    c = escape[1:2]
    if c == "x":
        escape += source.getwhile(2, HEXDIGITS)
        if len(escape) != 4:
            raise source.error(f"incomplete escape {escape}", len(escape))
        return chr(int(escape[2:], 16))
    if c == "u":
        escape += source.getwhile(4, HEXDIGITS)
        if len(escape) != 6:
            raise source.error(f"incomplete escape {escape}", len(escape))
        return chr(int(escape[2:], 16))
    if c == "U":
        escape += source.getwhile(8, HEXDIGITS)
        if len(escape) != 10:
            raise source.error(f"incomplete escape {escape}", len(escape))
        value = int(escape[2:], 16)
        if value > 0x10FFFF:
            raise source.error(f"bad escape {escape}", len(escape))
        return chr(value)
    if c == "N":
        if not source.match("{"):
            raise source.error("missing {")
        name = source.getuntil("}", "character name")
        try:
            return unicodedata.lookup(name)
        except KeyError:
            msg = f"undefined character name {name!r}"
            raise source.error(msg, len(name) + len(r"\N{}")) from None
    return None


def _class_escape(source: _Source, escape: str):
    """Escape inside a set. Returns ('lit', ch) or ('cat', letter)."""
    if escape in ESCAPES:
        return ("lit", ESCAPES[escape])
    if escape in CLASS_CATEGORIES:
        return ("cat", escape[1])
    ch = _unicode_escape(source, escape)
    if ch is not None:
        return ("lit", ch)
    c = escape[1:2]
    if c in OCTDIGITS:
        escape += source.getwhile(2, OCTDIGITS)
        value = int(escape[1:], 8)
        if value > 0o377:
            raise source.error(
                f"octal escape value {escape} outside of range 0-0o377", len(escape)
            )
        return ("lit", chr(value))
    if c in DIGITS or c in ASCIILETTERS:
        raise source.error(f"bad escape {escape}", len(escape))
    return ("lit", escape[1])


def _escape(source: _Source, escape: str):
    """Escape outside a set. Returns an AST node."""
    if escape in CLASS_CATEGORIES:
        cs = CharSet()
        cs.categories.append(escape[1])
        return (SET, cs)
    if escape in AT_ESCAPES:
        return (AT, AT_ESCAPES[escape])
    if escape in ESCAPES:
        return (CHAR, ESCAPES[escape])
    ch = _unicode_escape(source, escape)
    if ch is not None:
        return (CHAR, ch)
    c = escape[1:2]
    if c == "0":
        escape += source.getwhile(2, OCTDIGITS)
        return (CHAR, chr(int(escape[1:], 8)))
    if c in DIGITS:
        if source.next is not None and source.next in DIGITS:
            escape += source.get()
            if (
                escape[1] in OCTDIGITS
                and escape[2] in OCTDIGITS
                and source.next is not None
                and source.next in OCTDIGITS
            ):
                escape += source.get()
                value = int(escape[1:], 8)
                if value > 0o377:
                    raise source.error(
                        f"octal escape value {escape} outside of range 0-0o377", len(escape)
                    )
                return (CHAR, chr(value))
        raise source.error("backreferences are not supported", len(escape))
    if c in ASCIILETTERS:
        raise source.error(f"bad escape {escape}", len(escape))
    return (CHAR, escape[1])


class Parser:
    def __init__(self, pattern: str):
        self.source = _Source(pattern)
        self.groups = 0

    def parse(self):
        node = self._parse_alt(nested=0)
        if self.source.next is not None:
            # only an unmatched ")" can stop the top-level parse early
            raise RegexError("unbalanced parenthesis", self.source.pattern, self.source.index)
        return node

    def _parse_alt(self, nested: int):
        source = self.source
        items = [self._parse_seq(nested)]
        while source.match("|"):
            items.append(self._parse_seq(nested))
        if len(items) == 1:
            return items[0]
        return (ALT, items)

    def _parse_seq(self, nested: int):
        source = self.source
        seq: list = []
        while True:
            this = source.next
            if this is None or this in "|)":
                break
            start = source.index
            this = source.get()
            if this[0] == "\\":
                seq.append(_escape(source, this))
            elif this == "[":
                seq.append(self._parse_set(start))
            elif this == ".":
                seq.append((ANY,))
            elif this == "^":
                seq.append((AT, AT_BEGINNING))
            elif this == "$":
                seq.append((AT, AT_END))
            elif this == "(":
                seq.append(self._parse_group(start, nested))
            elif this in "*+?{":
                if not self._parse_repeat(this, start, seq):
                    seq.append((CHAR, "{"))
            else:
                seq.append((CHAR, this))
        if len(seq) == 1:
            return seq[0]
        return (SEQ, seq)

    def _parse_group(self, start: int, nested: int):
        source = self.source
        capture = True
        if source.match("?"):
            char = source.get()
            if char is None:
                raise source.error("unexpected end of pattern")
            if char == ":":
                capture = False
            else:
                raise RegexError(
                    f"unsupported group extension ?{char}", source.pattern, start + 1
                )
        index = None
        if capture:
            self.groups += 1
            index = self.groups
        body = self._parse_alt(nested + 1)
        if not source.match(")"):
            raise RegexError(
                "missing ), unterminated subpattern", source.pattern, start
            )
        return (GROUP, index, body)

    def _parse_repeat(self, this: str, here: int, seq: list) -> bool:
        """Parse a quantifier. Returns False if '{' turned out to be a literal."""
        source = self.source
        if this == "?":
            lo, hi = 0, 1
        elif this == "*":
            lo, hi = 0, None
        elif this == "+":
            lo, hi = 1, None
        else:  # "{"
            if source.next == "}":
                return False
            save = source.index
            lo_s = hi_s = ""
            while source.next is not None and source.next in DIGITS:
                lo_s += source.get()
            if source.match(","):
                while source.next is not None and source.next in DIGITS:
                    hi_s += source.get()
            else:
                hi_s = lo_s
            if not source.match("}"):
                source.index = save
                return False
            lo, hi = 0, None
            if lo_s:
                lo = int(lo_s)
                if lo >= MAXREPEAT:
                    raise RegexError("the repetition number is too large", source.pattern, here)
            if hi_s:
                hi = int(hi_s)
                if hi >= MAXREPEAT:
                    raise RegexError("the repetition number is too large", source.pattern, here)
                if hi < lo:
                    raise RegexError(
                        "min repeat greater than max repeat", source.pattern, here + 1
                    )
        if not seq or seq[-1][0] == AT:
            raise RegexError("nothing to repeat", source.pattern, here)
        item = seq[-1]
        if item[0] == REPEAT:
            raise RegexError("multiple repeat", source.pattern, here)
        if item[0] == GROUP and item[1] is None:
            item = item[2]
        greedy = True
        if source.match("?"):
            greedy = False
        elif source.next == "+":
            raise RegexError(
                "possessive quantifiers are not supported", source.pattern, source.index
            )
        seq[-1] = (REPEAT, lo, hi, greedy, item)
        return True

    def _parse_set(self, start: int):
        source = self.source
        negate = source.match("^")
        cs = CharSet(negate)
        items = 0
        while True:
            this = source.get()
            if this is None:
                raise RegexError("unterminated character set", source.pattern, start)
            if this == "]" and items:
                break
            if this[0] == "\\":
                code1 = _class_escape(source, this)
            else:
                code1 = ("lit", this)
            items += 1
            if source.match("-"):
                that = source.get()
                if that is None:
                    raise RegexError("unterminated character set", source.pattern, start)
                if that == "]":
                    _add(cs, code1)
                    cs.chars.add("-")
                    break
                if that[0] == "\\":
                    code2 = _class_escape(source, that)
                else:
                    code2 = ("lit", that)
                if code1[0] != "lit" or code2[0] != "lit":
                    raise source.error(
                        f"bad character range {this}-{that}", len(this) + 1 + len(that)
                    )
                lo, hi = ord(code1[1]), ord(code2[1])
                if hi < lo:
                    raise source.error(
                        f"bad character range {this}-{that}", len(this) + 1 + len(that)
                    )
                cs.ranges.append((lo, hi))
            else:
                _add(cs, code1)
        return (SET, cs)


def _add(cs: CharSet, code) -> None:
    if code[0] == "lit":
        cs.chars.add(code[1])
    else:
        cs.categories.append(code[1])


def parse(pattern: str):
    """Parse ``pattern``; returns ``(ast, number_of_groups)``."""
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a str")
    parser = Parser(pattern)
    ast = parser.parse()
    return ast, parser.groups
