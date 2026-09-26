"""Pattern parser.

Turns a pattern string into a small syntax tree. The grammar and the error cases follow
CPython's ``re._parser`` for the supported subset, so that the same patterns are accepted
and the tree has the same shape (which matters for matching semantics).

Tree nodes are ``(op, argument)`` tuples:

- ``(LITERAL, ch)``
- ``(ANY, None)``                       ``.``
- ``(IN, CharSet)``                     ``[...]`` and ``\\d``-style classes
- ``(AT, AT_BEGINNING | AT_END)``       ``^`` and ``$``
- ``(BRANCH, [seq, seq, ...])``         alternation
- ``(SUBPATTERN, (group | None, seq))`` ``( )`` and ``(?: )``
- ``(REPEAT, (min, max, greedy, seq))`` quantifiers; ``max`` is ``MAXREPEAT`` if unbounded

A ``seq`` is a list of nodes.
"""

from __future__ import annotations

from dataclasses import dataclass

LITERAL = "literal"
ANY = "any"
IN = "in"
AT = "at"
BRANCH = "branch"
SUBPATTERN = "subpattern"
REPEAT = "repeat"

AT_BEGINNING = "beginning"
AT_END = "end"

# Same limit as CPython's _sre.MAXREPEAT; also used as the "unbounded" marker.
MAXREPEAT = 2**32 - 1

DIGITS = frozenset("0123456789")
WORD = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
WHITESPACE = frozenset(" \t\n\r\f\v")

# class escape letter -> (characters, negated)
CATEGORIES = {
    "d": (DIGITS, False),
    "D": (DIGITS, True),
    "w": (WORD, False),
    "W": (WORD, True),
    "s": (WHITESPACE, False),
    "S": (WHITESPACE, True),
}

# Simple character escapes accepted in and outside of sets.
CHAR_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v", "a": "\a"}

SPECIAL_CHARS = frozenset(".\\[{()*+?^$|")
REPEAT_CHARS = frozenset("*+?{")


class RegexError(ValueError):
    """Raised for invalid or unsupported patterns."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None) -> None:
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)


@dataclass(frozen=True)
class CharSet:
    """A set of characters: literal characters, inclusive ranges and categories."""

    negate: bool
    chars: frozenset[str]
    ranges: tuple[tuple[str, str], ...]
    categories: tuple[tuple[frozenset[str], bool], ...]

    def __contains__(self, ch: str) -> bool:
        found = ch in self.chars
        if not found:
            for lo, hi in self.ranges:
                if lo <= ch <= hi:
                    found = True
                    break
        if not found:
            for members, negated in self.categories:
                if (ch in members) != negated:
                    found = True
                    break
        return found != self.negate


def _category_set(letter: str) -> CharSet:
    return CharSet(False, frozenset(), (), (CATEGORIES[letter],))


class _Source:
    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self.index = 0
        self.next: str | None = None
        self._advance()

    def _advance(self) -> None:
        index = self.index
        if index >= len(self.pattern):
            self.next = None
            return
        char = self.pattern[index]
        if char == "\\":
            if index + 1 >= len(self.pattern):
                raise RegexError("bad escape (end of pattern)", self.pattern, index)
            char += self.pattern[index + 1]
        self.index = index + len(char)
        self.next = char

    def match(self, char: str) -> bool:
        if char == self.next:
            self._advance()
            return True
        return False

    def get(self) -> str | None:
        this = self.next
        self._advance()
        return this

    def tell(self) -> int:
        return self.index - len(self.next or "")

    def seek(self, index: int) -> None:
        self.index = index
        self._advance()

    def error(self, msg: str, offset: int = 0) -> RegexError:
        return RegexError(msg, self.pattern, self.tell() - offset)


def parse(pattern: str) -> tuple[list, int]:
    """Parse ``pattern``; return ``(tree, number_of_groups)``."""
    if not isinstance(pattern, str):
        raise TypeError(f"pattern must be a str, not {type(pattern).__name__}")
    source = _Source(pattern)
    state = _ParseState()
    tree = _parse_sub(source, state, nested=0)
    if source.next is not None:
        assert source.next == ")"
        raise source.error("unbalanced parenthesis")
    return tree, state.groups


class _ParseState:
    def __init__(self) -> None:
        self.groups = 0

    def open_group(self) -> int:
        self.groups += 1
        return self.groups


def _parse_sub(source: _Source, state: _ParseState, nested: int) -> list:
    """Parse alternatives separated by ``|``."""
    items = []
    while True:
        items.append(_parse(source, state, nested + 1))
        if not source.match("|"):
            break
    if len(items) == 1:
        return items[0]
    return [(BRANCH, items)]


def _parse(source: _Source, state: _ParseState, nested: int) -> list:
    """Parse one alternative: a sequence of (possibly quantified) items."""
    seq: list = []
    while True:
        this = source.next
        if this is None or this in "|)":
            break
        source.get()

        if this[0] == "\\":
            seq.append(_escape(source, this))

        elif this not in SPECIAL_CHARS:
            seq.append((LITERAL, this))

        elif this == "[":
            seq.append(_parse_set(source))

        elif this in REPEAT_CHARS:
            here = source.tell()
            if this == "?":
                lo, hi = 0, 1
            elif this == "*":
                lo, hi = 0, MAXREPEAT
            elif this == "+":
                lo, hi = 1, MAXREPEAT
            else:  # "{"
                if source.next == "}":
                    seq.append((LITERAL, this))
                    continue
                lo, hi = 0, MAXREPEAT
                low = high = ""
                while source.next is not None and source.next in DIGITS:
                    low += source.get()
                if source.match(","):
                    while source.next is not None and source.next in DIGITS:
                        high += source.get()
                else:
                    high = low
                if not source.match("}"):
                    # Not a valid quantifier: the brace is an ordinary character.
                    seq.append((LITERAL, this))
                    source.seek(here)
                    continue
                if low:
                    lo = int(low)
                    if lo >= MAXREPEAT:
                        raise source.error("the repetition number is too large")
                if high:
                    hi = int(high)
                    if hi >= MAXREPEAT:
                        raise source.error("the repetition number is too large")
                    if hi < lo:
                        raise RegexError("min repeat greater than max repeat", source.pattern, here)

            if not seq or seq[-1][0] is AT:
                raise RegexError("nothing to repeat", source.pattern, here - len(this))
            if seq[-1][0] is REPEAT:
                raise RegexError("multiple repeat", source.pattern, here - len(this))
            item = seq[-1]
            body = [item]
            if item[0] is SUBPATTERN and item[1][0] is None:
                body = item[1][1]
            if source.match("?"):
                greedy = False
            elif source.next == "+":
                raise source.error("possessive quantifiers are not supported")
            else:
                greedy = True
            seq[-1] = (REPEAT, (lo, hi, greedy, body))

        elif this == ".":
            seq.append((ANY, None))

        elif this == "(":
            start = source.tell() - 1
            group: int | None
            if source.match("?"):
                if source.next is None:
                    raise source.error("unexpected end of pattern")
                if not source.match(":"):
                    raise source.error(f"unsupported group extension ?{source.next}")
                group = None
            else:
                group = state.open_group()
            body = _parse_sub(source, state, nested + 1)
            if not source.match(")"):
                raise RegexError("missing ), unterminated subpattern", source.pattern, start)
            seq.append((SUBPATTERN, (group, body)))

        elif this == "^":
            seq.append((AT, AT_BEGINNING))

        elif this == "$":
            seq.append((AT, AT_END))

        else:  # pragma: no cover - every special character is handled above
            raise AssertionError(f"unhandled special character {this!r}")

    return seq


def _escape(source: _Source, escape: str) -> tuple:
    """Parse an escape outside of a character set."""
    char = escape[1]
    if char in CATEGORIES:
        return (IN, _category_set(char))
    if char in CHAR_ESCAPES:
        return (LITERAL, CHAR_ESCAPES[char])
    if char.isascii() and char.isalnum():
        raise source.error(f"bad or unsupported escape {escape}", len(escape))
    return (LITERAL, char)


def _class_escape(source: _Source, escape: str) -> tuple:
    """Parse an escape inside a character set: ``("lit", ch)`` or ``("cat", letter)``."""
    char = escape[1]
    if char in CATEGORIES:
        return ("cat", char)
    if char in CHAR_ESCAPES:
        return ("lit", CHAR_ESCAPES[char])
    if char == "b":
        return ("lit", "\b")
    if char.isascii() and char.isalnum():
        raise source.error(f"bad or unsupported escape {escape}", len(escape))
    return ("lit", char)


def _parse_set(source: _Source) -> tuple:
    start = source.tell() - 1
    negate = source.match("^")
    chars: set[str] = set()
    ranges: list[tuple[str, str]] = []
    categories: list[tuple[frozenset[str], bool]] = []
    empty = True

    def add(code: tuple) -> None:
        if code[0] == "lit":
            chars.add(code[1])
        else:
            categories.append(CATEGORIES[code[1]])

    while True:
        this = source.get()
        if this is None:
            raise RegexError("unterminated character set", source.pattern, start)
        if this == "]" and not empty:
            break
        empty = False
        if this[0] == "\\":
            code1 = _class_escape(source, this)
        else:
            code1 = ("lit", this)
        if source.match("-"):
            that = source.get()
            if that is None:
                raise RegexError("unterminated character set", source.pattern, start)
            if that == "]":
                add(code1)
                chars.add("-")
                break
            if that[0] == "\\":
                code2 = _class_escape(source, that)
            else:
                code2 = ("lit", that)
            if code1[0] != "lit" or code2[0] != "lit":
                raise source.error(f"bad character range {this}-{that}", len(this) + 1 + len(that))
            lo, hi = code1[1], code2[1]
            if hi < lo:
                raise source.error(f"bad character range {this}-{that}", len(this) + 1 + len(that))
            ranges.append((lo, hi))
        else:
            add(code1)

    return (IN, CharSet(negate, frozenset(chars), tuple(ranges), tuple(categories)))
