"""Pattern parser.

The parser deliberately mirrors the structure of CPython's ``re._parser`` so
that the set of accepted patterns, and the shape of the resulting tree (which
influences matching order and capture semantics), is the same as the standard
library's for the supported subset of the syntax.

Tree nodes are tuples:

* ``("LIT", ch)``            -- literal character
* ``("NLIT", ch)``           -- any character except ``ch`` (``[^x]``)
* ``("ANY",)``               -- ``.``
* ``("IN", items, negate)``  -- character set; items are ``("LIT", ch)``,
  ``("RANGE", lo, hi)`` or ``("CAT", letter)``
* ``("AT", "BEG" | "END")``  -- ``^`` / ``$``
* ``("SUB", group, seq)``    -- group (``group`` is ``None`` when non-capturing)
* ``("BRANCH", [seq, ...])`` -- alternation
* ``("REPEAT", lo, hi, seq, greedy)`` -- quantifier (``hi`` may be MAXREPEAT)

A ``seq`` is a list of nodes.
"""

from __future__ import annotations

MAXREPEAT = 4294967295  # same value as _sre.MAXREPEAT; means "unbounded"

SPECIAL_CHARS = ".\\[{()*+?^$|"
REPEAT_CHARS = "*+?{"
DIGITS = frozenset("0123456789")
ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

# Character escapes accepted both inside and outside sets.
_CHAR_ESCAPES = {
    "\\a": "\a",
    "\\f": "\f",
    "\\n": "\n",
    "\\r": "\r",
    "\\t": "\t",
    "\\v": "\v",
    "\\\\": "\\",
}
_CATEGORY_ESCAPES = frozenset("dDsSwW")


class RegexError(ValueError):
    """Raised for invalid (or unsupported) regular expressions."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None):
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)


class _Source:
    def __init__(self, pattern: str):
        self.string = pattern
        self.index = 0
        self.next: str | None = None
        self._advance()

    def _advance(self) -> None:
        index = self.index
        s = self.string
        if index >= len(s):
            self.next = None
            return
        char = s[index]
        if char == "\\":
            if index + 1 >= len(s):
                raise RegexError("bad escape (end of pattern)", s, index)
            char += s[index + 1]
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
        return RegexError(msg, self.string, self.tell() - offset)


class _State:
    def __init__(self) -> None:
        self.groups = 0

    def opengroup(self) -> int:
        self.groups += 1
        return self.groups


def parse(pattern: str) -> tuple[list, int]:
    """Parse ``pattern`` and return ``(seq, number_of_groups)``."""
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a str")
    source = _Source(pattern)
    state = _State()
    seq = _parse_sub(source, state, 0)
    if source.next is not None:
        # only ")" can stop the top-level parse early
        raise source.error("unbalanced parenthesis")
    return seq, state.groups


def _unsupported(source: _Source, what: str, length: int) -> RegexError:
    return source.error(f"unsupported syntax {what!r}", length)


def _escape(source: _Source, escape: str) -> tuple:
    """Escape outside a character set."""
    c = escape[1:2]
    if c in _CATEGORY_ESCAPES:
        return ("IN", [("CAT", c)], False)
    code = _CHAR_ESCAPES.get(escape)
    if code is not None:
        return ("LIT", code)
    if c in ASCII_LETTERS or c in DIGITS:
        # Either invalid in ``re`` too (e.g. \q) or outside the supported
        # subset (\b, \A, \Z, \x.., \u...., octal and back references).
        raise source.error(f"bad escape {escape}", len(escape))
    return ("LIT", c)


def _class_escape(source: _Source, escape: str) -> tuple:
    """Escape inside a character set."""
    code = _CHAR_ESCAPES.get(escape)
    if code is not None:
        return ("LIT", code)
    if escape == "\\b":
        return ("LIT", "\b")
    c = escape[1:2]
    if c in _CATEGORY_ESCAPES:
        return ("CAT", c)
    if c in ASCII_LETTERS or c in DIGITS:
        raise source.error(f"bad escape {escape}", len(escape))
    return ("LIT", c)


def _uniq(items: list) -> list:
    return list(dict.fromkeys(items))


def _same_prefix(a: tuple, b: tuple) -> bool:
    # In CPython, nodes holding sub-patterns compare by identity (SubPattern
    # has no __eq__), so only "flat" nodes can ever be equal.
    if a[0] in ("SUB", "BRANCH", "REPEAT"):
        return a is b
    return a == b


def _parse_sub(source: _Source, state: _State, nested: int) -> list:
    items = []
    while True:
        items.append(_parse(source, state, nested + 1))
        if not source.match("|"):
            break

    if len(items) == 1:
        return items[0]

    subpattern: list = []

    # move a common prefix out of the branch
    while True:
        prefix = None
        for item in items:
            if not item:
                break
            if prefix is None:
                prefix = item[0]
            elif not _same_prefix(item[0], prefix):
                break
        else:
            for item in items:
                del item[0]
            subpattern.append(prefix)
            continue
        break

    # a branch of single characters becomes a character set
    charset: list = []
    for item in items:
        if len(item) != 1:
            break
        node = item[0]
        if node[0] == "LIT":
            charset.append(("LIT", node[1]))
        elif node[0] == "IN" and not node[2]:
            charset.extend(node[1])
        else:
            break
    else:
        subpattern.append(("IN", _uniq(charset), False))
        return subpattern

    subpattern.append(("BRANCH", items))
    return subpattern


def _parse_set(source: _Source) -> tuple:
    here = source.tell() - 1
    items: list = []
    negate = source.match("^")
    while True:
        this = source.get()
        if this is None:
            raise source.error("unterminated character set", source.tell() - here)
        if this == "]" and items:
            break
        if this[0] == "\\":
            code1 = _class_escape(source, this)
        else:
            code1 = ("LIT", this)
        if source.match("-"):
            that = source.get()
            if that is None:
                raise source.error("unterminated character set", source.tell() - here)
            if that == "]":
                items.append(code1)
                items.append(("LIT", "-"))
                break
            if that[0] == "\\":
                code2 = _class_escape(source, that)
            else:
                code2 = ("LIT", that)
            if code1[0] != "LIT" or code2[0] != "LIT":
                raise source.error(
                    f"bad character range {this}-{that}", len(this) + 1 + len(that)
                )
            lo, hi = code1[1], code2[1]
            if hi < lo:
                raise source.error(
                    f"bad character range {this}-{that}", len(this) + 1 + len(that)
                )
            items.append(("RANGE", lo, hi))
        else:
            items.append(code1)

    items = _uniq(items)
    if len(items) == 1 and items[0][0] == "LIT":
        if negate:
            return ("NLIT", items[0][1])
        return items[0]
    return ("IN", items, negate)


def _parse_repeat(source: _Source, this: str, subpattern: list) -> bool:
    """Handle a quantifier.  Returns False if ``{`` turned out to be a literal."""
    here = source.tell()
    if this == "?":
        lo, hi = 0, 1
    elif this == "*":
        lo, hi = 0, MAXREPEAT
    elif this == "+":
        lo, hi = 1, MAXREPEAT
    else:  # "{"
        if source.next == "}":
            subpattern.append(("LIT", "{"))
            return False
        lo, hi = 0, MAXREPEAT
        lo_s = hi_s = ""
        while source.next is not None and source.next in DIGITS:
            lo_s += source.get()  # type: ignore[operator]
        if source.match(","):
            while source.next is not None and source.next in DIGITS:
                hi_s += source.get()  # type: ignore[operator]
        else:
            hi_s = lo_s
        if not source.match("}"):
            subpattern.append(("LIT", "{"))
            source.seek(here)
            return False
        if lo_s:
            lo = int(lo_s)
            if lo >= MAXREPEAT:
                raise source.error("the repetition number is too large")
        if hi_s:
            hi = int(hi_s)
            if hi >= MAXREPEAT:
                raise source.error("the repetition number is too large")
            if hi < lo:
                raise source.error(
                    "min repeat greater than max repeat", source.tell() - here
                )

    if not subpattern or subpattern[-1][0] == "AT":
        raise source.error("nothing to repeat", source.tell() - here + len(this))
    item = subpattern[-1]
    if item[0] == "REPEAT":
        raise source.error("multiple repeat", source.tell() - here + len(this))
    if item[0] == "SUB" and item[1] is None:
        body = item[2]
    else:
        body = [item]
    if source.match("?"):
        greedy = False
    elif source.next == "+":
        raise _unsupported(source, "possessive quantifier", 0)
    else:
        greedy = True
    subpattern[-1] = ("REPEAT", lo, hi, body, greedy)
    return True


def _parse(source: _Source, state: _State, nested: int) -> list:
    subpattern: list = []
    while True:
        this = source.next
        if this is None:
            break
        if this in "|)":
            break
        source.get()

        if this[0] == "\\":
            subpattern.append(_escape(source, this))
        elif this not in SPECIAL_CHARS:
            subpattern.append(("LIT", this))
        elif this == "[":
            subpattern.append(_parse_set(source))
        elif this in REPEAT_CHARS:
            _parse_repeat(source, this, subpattern)
        elif this == ".":
            subpattern.append(("ANY",))
        elif this == "(":
            start = source.tell() - 1
            capture = True
            if source.match("?"):
                char = source.get()
                if char is None:
                    raise source.error("unexpected end of pattern")
                if char == ":":
                    capture = False
                else:
                    raise _unsupported(source, "(?" + char, len(char) + 1)
            group = state.opengroup() if capture else None
            p = _parse_sub(source, state, nested + 1)
            if not source.match(")"):
                raise source.error(
                    "missing ), unterminated subpattern", source.tell() - start
                )
            subpattern.append(("SUB", group, p))
        elif this == "^":
            subpattern.append(("AT", "BEG"))
        elif this == "$":
            subpattern.append(("AT", "END"))
        else:  # pragma: no cover - every special character is handled above
            raise AssertionError(f"unsupported special character {this!r}")
    return subpattern
