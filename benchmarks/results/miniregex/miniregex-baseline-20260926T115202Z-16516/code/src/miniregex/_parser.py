"""Pattern parser.

Produces a small syntax tree. The tree shape deliberately mirrors CPython's
``re._parser`` (including its alternation optimisations) because the shape
decides which matching strategy the compiler picks, and those strategies
differ in how capture groups are saved and restored on backtracking.

Nodes are tuples:

* ``("lit", ch)``
* ``("any",)``                      -- ``.``
* ``("in", CharSet)``
* ``("at", "beg" | "end")``
* ``("group", index | None, seq)``  -- index is 1-based; None = non-capturing
* ``("branch", [seq, ...])``
* ``("repeat", min, max, greedy, seq)``

A ``seq`` is a list of nodes. ``max`` is ``MAXREPEAT`` for "unbounded".
"""

from __future__ import annotations

from dataclasses import dataclass

MAXREPEAT = 2**32 - 1


class RegexError(ValueError):
    """Raised for invalid or unsupported patterns."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None):
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)


_DIGITS = frozenset("0123456789")
_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_WORD = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_SPACE = frozenset(" \t\n\r\f\v")

# Category name -> (member set, negated)
_CATEGORIES = {
    "d": (_DIGITS, False),
    "D": (_DIGITS, True),
    "w": (_WORD, False),
    "W": (_WORD, True),
    "s": (_SPACE, False),
    "S": (_SPACE, True),
}

_LITERAL_ESCAPES = {"a": "\a", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}

_UNSUPPORTED_ESCAPES = frozenset("AbBZxuUNgk")


@dataclass(frozen=True)
class CharSet:
    """A set of characters: literal ranges plus categories, optionally negated."""

    ranges: tuple[tuple[int, int], ...]
    categories: tuple[str, ...]
    negate: bool = False

    def __contains__(self, ch: str) -> bool:
        code = ord(ch)
        found = False
        for lo, hi in self.ranges:
            if lo <= code <= hi:
                found = True
                break
        else:
            for name in self.categories:
                members, negated = _CATEGORIES[name]
                if (ch in members) != negated:
                    found = True
                    break
        return found != self.negate


def _category_set(name: str) -> CharSet:
    return CharSet((), (name,))


class _Parser:
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.pos = 0
        self.ngroups = 0

    # -- helpers ---------------------------------------------------------

    def error(self, msg: str, pos: int | None = None) -> RegexError:
        return RegexError(msg, self.pattern, self.pos if pos is None else pos)

    def peek(self) -> str | None:
        if self.pos < len(self.pattern):
            return self.pattern[self.pos]
        return None

    def accept(self, ch: str) -> bool:
        if self.peek() == ch:
            self.pos += 1
            return True
        return False

    def next_token(self) -> str | None:
        """Return the next token: one character, or a backslash plus one character."""
        if self.pos >= len(self.pattern):
            return None
        ch = self.pattern[self.pos]
        if ch == "\\":
            if self.pos + 1 >= len(self.pattern):
                raise self.error("bad escape (end of pattern)")
            self.pos += 2
            return self.pattern[self.pos - 2 : self.pos]
        self.pos += 1
        return ch

    # -- grammar ---------------------------------------------------------

    def parse(self) -> list:
        seq = self.parse_alternation()
        if self.pos < len(self.pattern):
            # Only an unmatched ")" can stop the top-level alternation early.
            raise self.error("unbalanced parenthesis")
        return seq

    def parse_alternation(self) -> list:
        items = [self.parse_sequence()]
        while self.accept("|"):
            items.append(self.parse_sequence())
        if len(items) == 1:
            return items[0]

        result: list = []
        # Move a common leading node out of the branch (as re._parser does).
        while all(items) and all(_same_node(item[0], items[0][0]) for item in items[1:]):
            prefix = items[0][0]
            for item in items:
                del item[0]
            result.append(prefix)

        # A branch of single characters/sets becomes a single character set.
        ranges: list[tuple[int, int]] = []
        categories: list[str] = []
        for item in items:
            if len(item) != 1:
                break
            node = item[0]
            if node[0] == "lit":
                ranges.append((ord(node[1]), ord(node[1])))
            elif node[0] == "in" and not node[1].negate:
                ranges.extend(node[1].ranges)
                categories.extend(node[1].categories)
            else:
                break
        else:
            result.append(("in", CharSet(tuple(ranges), tuple(categories))))
            return result

        result.append(("branch", items))
        return result

    def parse_sequence(self) -> list:
        seq: list = []
        while True:
            ch = self.peek()
            if ch is None or ch in "|)":
                return seq
            start = self.pos
            token = self.next_token()
            assert token is not None
            if token == "(":
                seq.append(self.parse_group(start))
            elif token == "[":
                seq.append(self.parse_set(start))
            elif token == ".":
                seq.append(("any",))
            elif token == "^":
                seq.append(("at", "beg"))
            elif token == "$":
                seq.append(("at", "end"))
            elif token in ("*", "+", "?", "{"):
                self.parse_quantifier(token, seq, start)
            elif token[0] == "\\":
                seq.append(self.parse_escape(token, start))
            else:
                seq.append(("lit", token))

    def parse_group(self, start: int) -> tuple:
        if self.accept("?"):
            if not self.accept(":"):
                raise self.error("unsupported group extension", start)
            index = None
        else:
            self.ngroups += 1
            index = self.ngroups
        body = self.parse_alternation()
        if not self.accept(")"):
            raise self.error("missing ), unterminated subpattern", start)
        return ("group", index, body)

    def parse_quantifier(self, token: str, seq: list, start: int) -> None:
        if token == "?":
            lo, hi = 0, 1
        elif token == "*":
            lo, hi = 0, MAXREPEAT
        elif token == "+":
            lo, hi = 1, MAXREPEAT
        else:
            # "{" is only a quantifier when it forms {n}, {n,}, {,m} or {n,m};
            # otherwise it is a literal brace.
            if self.peek() == "}":
                seq.append(("lit", "{"))
                return
            lo_digits = self.take_digits()
            if self.accept(","):
                hi_digits = self.take_digits()
            else:
                hi_digits = lo_digits
            if not self.accept("}"):
                self.pos = start + 1
                seq.append(("lit", "{"))
                return
            lo, hi = 0, MAXREPEAT
            if lo_digits:
                lo = int(lo_digits)
                if lo >= MAXREPEAT:
                    raise self.error("the repetition number is too large", start)
            if hi_digits:
                hi = int(hi_digits)
                if hi >= MAXREPEAT:
                    raise self.error("the repetition number is too large", start)
                if hi < lo:
                    raise self.error("min repeat greater than max repeat", start)

        if not seq or seq[-1][0] == "at":
            raise self.error("nothing to repeat", start)
        if seq[-1][0] == "repeat":
            raise self.error("multiple repeat", start)
        last = seq[-1]
        if last[0] == "group" and last[1] is None:
            item = last[2]
        else:
            item = [last]
        greedy = True
        if self.accept("?"):
            greedy = False
        elif self.peek() == "+":
            raise self.error("possessive quantifiers are not supported")
        seq[-1] = ("repeat", lo, hi, greedy, item)

    def take_digits(self) -> str:
        begin = self.pos
        while self.peek() is not None and self.peek() in _DIGITS:
            self.pos += 1
        return self.pattern[begin : self.pos]

    def parse_escape(self, token: str, start: int) -> tuple:
        c = token[1]
        if c in _CATEGORIES:
            return ("in", _category_set(c))
        return ("lit", self.escape_literal(c, start))

    def escape_literal(self, c: str, start: int) -> str:
        if c in _LITERAL_ESCAPES:
            return _LITERAL_ESCAPES[c]
        if c in _DIGITS:
            raise self.error("backreferences and octal escapes are not supported", start)
        if c in _UNSUPPORTED_ESCAPES:
            raise self.error(f"unsupported escape \\{c}", start)
        if c in _ASCII_LETTERS:
            raise self.error(f"bad escape \\{c}", start)
        return c

    def parse_set(self, start: int) -> tuple:
        negate = self.accept("^")
        items: list[tuple] = []  # ("range", lo, hi) or ("cat", name)
        while True:
            token = self.next_token()
            if token is None:
                raise self.error("unterminated character set", start)
            if token == "]" and items:
                break
            first = self.set_item(token)
            if self.accept("-"):
                token2 = self.next_token()
                if token2 is None:
                    raise self.error("unterminated character set", start)
                if token2 == "]":
                    items.append(first)
                    items.append(("range", ord("-"), ord("-")))
                    break
                second = self.set_item(token2)
                if first[0] != "range" or second[0] != "range" or second[1] < first[1]:
                    raise self.error(f"bad character range {token}-{token2}")
                items.append(("range", first[1], second[1]))
            else:
                items.append(first)

        if len(items) == 1 and items[0][0] == "range" and items[0][1] == items[0][2]:
            ch = chr(items[0][1])
            if not negate:
                return ("lit", ch)
        ranges = tuple((it[1], it[2]) for it in items if it[0] == "range")
        categories = tuple(it[1] for it in items if it[0] == "cat")
        return ("in", CharSet(ranges, categories, negate))

    def set_item(self, token: str) -> tuple:
        if token[0] != "\\":
            return ("range", ord(token), ord(token))
        c = token[1]
        if c in _CATEGORIES:
            return ("cat", c)
        ch = self.escape_literal(c, self.pos - 2)
        return ("range", ord(ch), ord(ch))


def _same_node(a: tuple, b: tuple) -> bool:
    """Structural equality as re._parser sees it: groups, repeats and branches never compare
    equal (they hold distinct sub-pattern objects)."""
    return a[0] in ("lit", "any", "at", "in") and a == b


def parse(pattern: str) -> tuple[list, int]:
    """Parse ``pattern`` and return ``(tree, number_of_groups)``."""
    parser = _Parser(pattern)
    tree = parser.parse()
    return tree, parser.ngroups
