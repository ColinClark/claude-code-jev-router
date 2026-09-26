"""Pattern parser.

Produces a small syntax tree that mirrors the one built by CPython's
``re._parser`` (including its branch-to-set and common-prefix rewrites), so
that the compiled program backtracks in exactly the same order as ``re``.

Tree items are tuples:

* ``(LITERAL, ch)``, ``(ANY,)``, ``(IN, negate, members)`` -- single characters.
  ``members`` is a tuple of ``(LITERAL, ch)``, ``(RANGE, lo, hi)`` or
  ``(CATEGORY, letter)``.
* ``(AT, BEGINNING | END)``
* ``(SUBPATTERN, group_or_None, items)``
* ``(BRANCH, [items, ...])``
* ``(REPEAT, min, max_or_None, lazy, items)``
"""

from __future__ import annotations

LITERAL = "LITERAL"
ANY = "ANY"
IN = "IN"
RANGE = "RANGE"
CATEGORY = "CATEGORY"
AT = "AT"
BEGINNING = "BEGINNING"
END = "END"
SUBPATTERN = "SUBPATTERN"
BRANCH = "BRANCH"
REPEAT = "REPEAT"

UNIT_OPS = frozenset({LITERAL, ANY, IN})
MAXREPEAT = 4294967295
DIGITS = frozenset("0123456789")
ASCII_ALNUM = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
CATEGORY_LETTERS = frozenset("dDwWsS")
CONTROL_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v", "a": "\a"}


class RegexError(ValueError):
    """Raised for invalid (or unsupported) patterns."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None):
        if pattern is not None and pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)
        self.msg = msg
        self.pattern = pattern
        self.pos = pos


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


class _State:
    def __init__(self):
        self.groups = 1  # group 0 is the whole match
        self.open: list[int] = []

    def opengroup(self) -> int:
        gid = self.groups
        self.groups += 1
        self.open.append(gid)
        return gid

    def closegroup(self, gid: int) -> None:
        self.open.remove(gid)


def parse(pattern: str) -> tuple[list, int]:
    """Parse ``pattern``; return ``(items, number_of_capturing_groups)``."""
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a str")
    source = _Source(pattern)
    state = _State()
    items = _parse_sub(source, state, 0)
    if source.next is not None:
        raise source.error("unbalanced parenthesis")
    return items, state.groups - 1


def _parse_sub(source: _Source, state: _State, nested: int) -> list:
    alternatives = []
    while True:
        alternatives.append(_parse(source, state, nested + 1))
        if not source.match("|"):
            break
    if len(alternatives) == 1:
        return alternatives[0]

    result: list = []
    # Move a prefix shared by every alternative out of the branch.  Only
    # single-character and anchor items can compare equal (as in re).
    while True:
        prefix = None
        for alt in alternatives:
            if not alt or alt[0][0] not in (LITERAL, ANY, IN, AT):
                break
            if prefix is None:
                prefix = alt[0]
            elif alt[0] != prefix:
                break
        else:
            for alt in alternatives:
                del alt[0]
            result.append(prefix)
            continue
        break

    # A branch of single characters becomes a character set.
    members: list = []
    for alt in alternatives:
        if len(alt) != 1:
            break
        item = alt[0]
        if item[0] == LITERAL:
            members.append(item)
        elif item[0] == IN and not item[1]:
            members.extend(item[2])
        else:
            break
    else:
        unique = tuple(dict.fromkeys(members))
        result.append((IN, False, unique))
        return result

    result.append((BRANCH, alternatives))
    return result


def _parse(source: _Source, state: _State, nested: int) -> list:
    items: list = []
    while True:
        this = source.next
        if this is None or this in "|)":
            break
        source.get()

        if this == "\\":
            items.append(_escape(source, in_class=False))
        elif this == "[":
            items.append(_parse_set(source))
        elif this == ".":
            items.append((ANY,))
        elif this in "*+?{":
            here = source.index
            if this == "?":
                lo, hi = 0, 1
            elif this == "*":
                lo, hi = 0, None
            elif this == "+":
                lo, hi = 1, None
            else:
                if source.next == "}":
                    items.append((LITERAL, this))
                    continue
                lo, hi = 0, None
                lo_s = hi_s = ""
                while source.next in DIGITS:
                    lo_s += source.get()
                if source.match(","):
                    while source.next in DIGITS:
                        hi_s += source.get()
                else:
                    hi_s = lo_s
                if not source.match("}"):
                    items.append((LITERAL, this))
                    source.index = here
                    continue
                if lo_s:
                    lo = int(lo_s)
                    if lo >= MAXREPEAT:
                        raise source.error("the repetition number is too large")
                if hi_s:
                    hi = int(hi_s)
                    if hi >= MAXREPEAT:
                        raise source.error("the repetition number is too large")
                    if hi < lo:
                        raise source.error("min repeat greater than max repeat")

            if not items or items[-1][0] == AT:
                raise source.error("nothing to repeat", source.index - here + 1)
            item = items[-1]
            if item[0] == REPEAT:
                raise source.error("multiple repeat", source.index - here + 1)
            if item[0] == SUBPATTERN and item[1] is None:
                body = item[2]
            else:
                body = [item]
            lazy = source.match("?")
            if source.next == "+":
                raise source.error("possessive quantifiers are not supported")
            items[-1] = (REPEAT, lo, hi, lazy, body)
        elif this == "(":
            start = source.index - 1
            group = None
            if source.match("?"):
                if not source.match(":"):
                    raise source.error("unsupported group extension", 1)
            else:
                group = state.opengroup()
            body = _parse_sub(source, state, nested + 1)
            if not source.match(")"):
                raise RegexError("missing ), unterminated subpattern", source.pattern, start)
            if group is not None:
                state.closegroup(group)
            items.append((SUBPATTERN, group, body))
        elif this == "^":
            items.append((AT, BEGINNING))
        elif this == "$":
            items.append((AT, END))
        else:
            items.append((LITERAL, this))
    return items


def _escape(source: _Source, in_class: bool) -> tuple:
    """Parse the character after a backslash."""
    ch = source.get()
    if ch is None:
        raise source.error("bad escape (end of pattern)", 1)
    if ch in CATEGORY_LETTERS:
        return (IN, False, ((CATEGORY, ch),))
    if ch in CONTROL_ESCAPES:
        return (LITERAL, CONTROL_ESCAPES[ch])
    if in_class and ch == "b":
        return (LITERAL, "\b")
    if ch in ASCII_ALNUM:
        raise source.error(f"bad or unsupported escape \\{ch}", 2)
    return (LITERAL, ch)


def _parse_set(source: _Source) -> tuple:
    start = source.index - 1
    members: list = []
    negate = source.match("^")
    while True:
        this = source.get()
        if this is None:
            raise RegexError("unterminated character set", source.pattern, start)
        # ``]`` directly after ``[`` or ``[^`` is a literal.
        if this == "]" and members:
            break
        code1 = _escape(source, in_class=True) if this == "\\" else (LITERAL, this)
        if source.match("-"):
            that = source.get()
            if that is None:
                raise RegexError("unterminated character set", source.pattern, start)
            if that == "]":
                members.append(code1[2][0] if code1[0] == IN else code1)
                members.append((LITERAL, "-"))
                break
            code2 = _escape(source, in_class=True) if that == "\\" else (LITERAL, that)
            if code1[0] != LITERAL or code2[0] != LITERAL:
                raise source.error("bad character range")
            if ord(code2[1]) < ord(code1[1]):
                raise source.error("bad character range")
            members.append((RANGE, code1[1], code2[1]))
        else:
            members.append(code1[2][0] if code1[0] == IN else code1)
    return (IN, negate, tuple(members))
