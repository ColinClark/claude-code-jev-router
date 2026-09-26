"""Pattern parser.

The grammar and its edge cases mirror CPython's ``re._parser`` (no flags) so
that exactly the same patterns are accepted and they mean the same thing.

Parse tree nodes are tuples:

* ``("lit", ch)``                       one literal character
* ``("notlit", ch)``                    any character except ``ch``
* ``("any",)``                          ``.``
* ``("in", negate, items)``             character set; items are
  ``("lit", ch)``, ``("range", lo, hi)`` (code points) or ``("cat", name)``
* ``("at", kind)``                      zero-width assertion
* ``("group", gid_or_None, seq)``       (non-)capturing group
* ``("branch", [seq, ...])``            alternation
* ``("repeat", min, max_or_None, greedy, seq)``
* ``("groupref", gid)``                 backreference

A ``seq`` is a list of nodes.
"""

from __future__ import annotations

import sys
import unicodedata

from ._errors import RegexError

SPECIAL_CHARS = frozenset(".\\[{()*+?^$|")
REPEAT_CHARS = frozenset("*+?{")
DIGITS = frozenset("0123456789")
OCTDIGITS = frozenset("01234567")
HEXDIGITS = frozenset("0123456789abcdefABCDEF")
ASCIILETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

# Mirrors sre MAXREPEAT: larger repeat counts are rejected.
MAXREPEAT = 4294967295

ESCAPES = {
    r"\a": ("lit", "\a"),
    r"\b": ("lit", "\b"),
    r"\f": ("lit", "\f"),
    r"\n": ("lit", "\n"),
    r"\r": ("lit", "\r"),
    r"\t": ("lit", "\t"),
    r"\v": ("lit", "\v"),
    "\\\\": ("lit", "\\"),
}

CATEGORIES = {
    r"\A": ("at", "begin_string"),
    r"\Z": ("at", "end_string"),
    r"\b": ("at", "boundary"),
    r"\B": ("at", "nonboundary"),
    r"\d": ("in", False, (("cat", "digit"),)),
    r"\D": ("in", False, (("cat", "notdigit"),)),
    r"\s": ("in", False, (("cat", "space"),)),
    r"\S": ("in", False, (("cat", "notspace"),)),
    r"\w": ("in", False, (("cat", "word"),)),
    r"\W": ("in", False, (("cat", "notword"),)),
}
if sys.version_info >= (3, 14):
    # Python 3.14 added \z as an alias of \Z.
    CATEGORIES[r"\z"] = ("at", "end_string")


class _Source:
    """Tokenizer: yields single characters, or two-character escapes."""

    def __init__(self, string: str) -> None:
        self.string = string
        self.index = 0
        self.next: str | None = None
        self._advance()

    def _advance(self) -> None:
        index = self.index
        try:
            char = self.string[index]
        except IndexError:
            self.next = None
            return
        if char == "\\":
            index += 1
            try:
                char += self.string[index]
            except IndexError:
                raise self.error("bad escape (end of pattern)") from None
        self.index = index + 1
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

    def getwhile(self, n: int, charset: frozenset[str]) -> str:
        result = ""
        for _ in range(n):
            c = self.next
            if c not in charset:
                break
            result += c
            self._advance()
        return result

    def getuntil(self, terminator: str, name: str) -> str:
        result = ""
        while True:
            c = self.next
            self._advance()
            if c is None:
                if not result:
                    raise self.error("missing " + name)
                raise self.error(f"missing {terminator}, unterminated name")
            if c == terminator:
                if not result:
                    raise self.error("missing " + name)
                break
            result += c
        return result

    def tell(self) -> int:
        return self.index - len(self.next or "")

    def seek(self, index: int) -> None:
        self.index = index
        self._advance()

    def error(self, msg: str) -> RegexError:
        return RegexError(msg, self.string, self.tell())


class _State:
    def __init__(self) -> None:
        self.ngroups = 0
        self.closed: set[int] = set()

    def opengroup(self) -> int:
        self.ngroups += 1
        return self.ngroups

    def closegroup(self, gid: int) -> None:
        self.closed.add(gid)


def _named_char(source: _Source) -> int:
    if not source.match("{"):
        raise source.error("missing {")
    charname = source.getuntil("}", "character name")
    try:
        return ord(unicodedata.lookup(charname))
    except (KeyError, TypeError):
        raise source.error(f"undefined character name {charname!r}") from None


def _class_escape(source: _Source, escape: str) -> tuple:
    code = ESCAPES.get(escape)
    if code:
        return code
    code = CATEGORIES.get(escape)
    if code and code[0] == "in":
        return code
    c = escape[1:2]
    if c == "x":
        escape += source.getwhile(2, HEXDIGITS)
        if len(escape) != 4:
            raise source.error(f"incomplete escape {escape}")
        return ("lit", chr(int(escape[2:], 16)))
    if c == "u":
        escape += source.getwhile(4, HEXDIGITS)
        if len(escape) != 6:
            raise source.error(f"incomplete escape {escape}")
        return ("lit", chr(int(escape[2:], 16)))
    if c == "U":
        escape += source.getwhile(8, HEXDIGITS)
        if len(escape) != 10:
            raise source.error(f"incomplete escape {escape}")
        value = int(escape[2:], 16)
        if value > 0x10FFFF:
            raise source.error(f"bad escape {escape}")
        return ("lit", chr(value))
    if c == "N":
        return ("lit", chr(_named_char(source)))
    if c in OCTDIGITS:
        escape += source.getwhile(2, OCTDIGITS)
        value = int(escape[1:], 8)
        if value > 0o377:
            raise source.error(f"octal escape value {escape} outside of range 0-0o377")
        return ("lit", chr(value))
    if c in DIGITS:
        raise source.error(f"bad escape {escape}")
    if len(escape) == 2:
        if c in ASCIILETTERS:
            raise source.error(f"bad escape {escape}")
        return ("lit", escape[1])
    raise source.error(f"bad escape {escape}")


def _escape(source: _Source, escape: str, state: _State) -> tuple:
    code = CATEGORIES.get(escape)
    if code:
        return code
    code = ESCAPES.get(escape)
    if code:
        return code
    c = escape[1:2]
    if c == "x":
        escape += source.getwhile(2, HEXDIGITS)
        if len(escape) != 4:
            raise source.error(f"incomplete escape {escape}")
        return ("lit", chr(int(escape[2:], 16)))
    if c == "u":
        escape += source.getwhile(4, HEXDIGITS)
        if len(escape) != 6:
            raise source.error(f"incomplete escape {escape}")
        return ("lit", chr(int(escape[2:], 16)))
    if c == "U":
        escape += source.getwhile(8, HEXDIGITS)
        if len(escape) != 10:
            raise source.error(f"incomplete escape {escape}")
        value = int(escape[2:], 16)
        if value > 0x10FFFF:
            raise source.error(f"bad escape {escape}")
        return ("lit", chr(value))
    if c == "N":
        return ("lit", chr(_named_char(source)))
    if c == "0":
        escape += source.getwhile(2, OCTDIGITS)
        return ("lit", chr(int(escape[1:], 8)))
    if c in DIGITS:
        # octal escape *or* decimal group reference
        if source.next in DIGITS:
            escape += source.get()  # type: ignore[operator]
            if escape[1] in OCTDIGITS and escape[2] in OCTDIGITS and source.next in OCTDIGITS:
                escape += source.get()  # type: ignore[operator]
                value = int(escape[1:], 8)
                if value > 0o377:
                    raise source.error(f"octal escape value {escape} outside of range 0-0o377")
                return ("lit", chr(value))
        group = int(escape[1:])
        if group <= state.ngroups:
            if group not in state.closed:
                raise source.error("cannot refer to an open group")
            return ("groupref", group)
        raise source.error(f"invalid group reference {group}")
    if len(escape) == 2:
        if c in ASCIILETTERS:
            raise source.error(f"bad escape {escape}")
        return ("lit", escape[1])
    raise source.error(f"bad escape {escape}")


def _parse_sub(source: _Source, state: _State, nested: int) -> list:
    items = []
    while True:
        items.append(_parse(source, state, nested + 1))
        if not source.match("|"):
            break
    if len(items) == 1:
        return items[0]
    return [("branch", items)]


def _parse_set(source: _Source) -> tuple:
    items: list = []
    negate = source.match("^")
    while True:
        this = source.get()
        if this is None:
            raise source.error("unterminated character set")
        if this == "]" and items:
            break
        if this[0] == "\\":
            code1 = _class_escape(source, this)
        else:
            code1 = ("lit", this)
        if source.match("-"):
            that = source.get()
            if that is None:
                raise source.error("unterminated character set")
            if that == "]":
                items.append(code1 if code1[0] == "lit" else code1[2][0])
                items.append(("lit", "-"))
                break
            if that[0] == "\\":
                code2 = _class_escape(source, that)
            else:
                code2 = ("lit", that)
            if code1[0] != "lit" or code2[0] != "lit":
                raise source.error(f"bad character range {this}-{that}")
            lo = ord(code1[1])
            hi = ord(code2[1])
            if hi < lo:
                raise source.error(f"bad character range {this}-{that}")
            items.append(("range", lo, hi))
        else:
            items.append(code1 if code1[0] == "lit" else code1[2][0])
    if len(items) == 1 and items[0][0] == "lit":
        if negate:
            return ("notlit", items[0][1])
        return items[0]
    return ("in", negate, tuple(items))


def _parse_brace(source: _Source) -> tuple[int, int | None] | None:
    """Parse ``{m,n}`` after the ``{``; return None if it is a literal brace."""
    here = source.tell()
    if source.next == "}":
        return None
    lo = hi = ""
    while source.next in DIGITS:
        lo += source.get()  # type: ignore[operator]
    if source.match(","):
        while source.next in DIGITS:
            hi += source.get()  # type: ignore[operator]
    else:
        hi = lo
    if not source.match("}"):
        source.seek(here)
        return None
    mn = 0
    mx: int | None = None
    if lo:
        mn = int(lo)
        if mn >= MAXREPEAT:
            raise source.error("the repetition number is too large")
    if hi:
        mx = int(hi)
        if mx >= MAXREPEAT:
            raise source.error("the repetition number is too large")
        if mx < mn:
            raise source.error("min repeat greater than max repeat")
    return mn, mx


def _parse(source: _Source, state: _State, nested: int) -> list:
    seq: list = []
    while True:
        this = source.next
        if this is None:
            break
        if this in ("|", ")"):
            break
        source.get()
        if this[0] == "\\":
            seq.append(_escape(source, this, state))
        elif this not in SPECIAL_CHARS:
            seq.append(("lit", this))
        elif this == "[":
            seq.append(_parse_set(source))
        elif this in REPEAT_CHARS:
            mn: int
            mx: int | None
            if this == "?":
                mn, mx = 0, 1
            elif this == "*":
                mn, mx = 0, None
            elif this == "+":
                mn, mx = 1, None
            else:
                brace = _parse_brace(source)
                if brace is None:
                    seq.append(("lit", "{"))
                    continue
                mn, mx = brace
            if not seq or seq[-1][0] == "at":
                raise source.error("nothing to repeat")
            item = seq[-1]
            if item[0] == "repeat":
                raise source.error("multiple repeat")
            if item[0] == "group" and item[1] is None:
                body = item[2]
            else:
                body = [item]
            if source.match("?"):
                greedy = False
            elif source.next == "+":
                raise source.error("possessive quantifiers are not supported")
            else:
                greedy = True
            seq[-1] = ("repeat", mn, mx, greedy, body)
        elif this == ".":
            seq.append(("any",))
        elif this == "(":
            capture = True
            if source.match("?"):
                char = source.get()
                if char is None:
                    raise source.error("unexpected end of pattern")
                if char == ":":
                    capture = False
                else:
                    raise source.error("unknown or unsupported extension ?" + char)
            gid = state.opengroup() if capture else None
            body = _parse_sub(source, state, nested + 1)
            if not source.match(")"):
                raise source.error("missing ), unterminated subpattern")
            if gid is not None:
                state.closegroup(gid)
            seq.append(("group", gid, body))
        elif this == "^":
            seq.append(("at", "begin"))
        elif this == "$":
            seq.append(("at", "end"))
        else:  # pragma: no cover
            raise AssertionError(f"unsupported special character {this!r}")
    return seq


def parse(pattern: str) -> tuple[list, int]:
    """Parse ``pattern``; return ``(seq, number_of_groups)``."""
    source = _Source(pattern)
    state = _State()
    seq = _parse_sub(source, state, 0)
    if source.next is not None:
        raise source.error("unbalanced parenthesis")
    return seq, state.ngroups
