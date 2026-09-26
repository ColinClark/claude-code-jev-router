"""Pattern string -> AST (see ``_ast``). Entry point: ``parse(pattern) -> Pattern``.

Follows CPython's ``sre_parse`` structure closely (including its alternation
optimisations: common-prefix factoring and single-character alternations turned
into a character set), because the matcher emulates ``sre`` backtracking and
capture bookkeeping exactly. Deviations from ``re``: only the documented syntax
subset is accepted; anything else (unknown escapes, ``(?...`` extensions,
malformed ``{...}``, possessive quantifiers) raises ``RegexError``.
"""

from __future__ import annotations

from ._ast import Alt, Any, At, CharSet, Group, Literal, Pattern, Repeat, Seq
from ._errors import RegexError

_SPECIAL = set(".\\[{()*+?^$|")
_REPEAT_CHARS = set("*+?{")
_DIGITS = set("0123456789")
_CATEGORIES = set("dDwWsS")
_CONTROL_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v"}
_ASCII_ALNUM = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


class _Source:
    def __init__(self, pattern: str) -> None:
        self.s = pattern
        self.i = 0

    def peek(self) -> str | None:
        return self.s[self.i] if self.i < len(self.s) else None

    def get(self) -> str | None:
        if self.i < len(self.s):
            ch = self.s[self.i]
            self.i += 1
            return ch
        return None

    def match(self, ch: str) -> bool:
        if self.peek() == ch:
            self.i += 1
            return True
        return False

    def error(self, msg: str, pos: int | None = None) -> RegexError:
        return RegexError(msg, self.s, self.i if pos is None else pos)


class _State:
    def __init__(self) -> None:
        self.groups = 0


def parse(pattern: str) -> Pattern:
    """Parse ``pattern`` into a ``Pattern``; raises ``RegexError`` if invalid."""
    if not isinstance(pattern, str):
        raise RegexError("pattern must be a str")
    src = _Source(pattern)
    state = _State()
    root = _parse_alternation(src, state)
    if src.peek() is not None:
        # Only a stray ')' can stop the top-level parse early.
        raise src.error("unbalanced parenthesis")
    return Pattern(root=root, groups=state.groups, source=pattern)


def _parse_alternation(src: _Source, state: _State):
    branches = [_parse_sequence(src, state)]
    while src.match("|"):
        branches.append(_parse_sequence(src, state))
    if len(branches) == 1:
        return Seq(tuple(branches[0]))

    # Factor out a common prefix (sre_parse does this; prefixes never contain groups).
    prefix = []
    while True:
        first = None
        for b in branches:
            if not b:
                break
            if first is None:
                first = b[0]
            elif b[0] != first:
                break
        else:
            for b in branches:
                del b[0]
            prefix.append(first)
            continue
        break

    # Alternation of single characters / non-negated sets -> one character set.
    items: list = []
    for b in branches:
        if len(b) != 1:
            break
        node = b[0]
        if isinstance(node, Literal):
            items.append((ord(node.ch), ord(node.ch)))
        elif isinstance(node, CharSet) and not node.negated:
            items.extend(node.items)
        else:
            break
    else:
        uniq = tuple(dict.fromkeys(items))
        return Seq(tuple(prefix) + (CharSet(False, uniq),))

    alt = Alt(tuple(Seq(tuple(b)) for b in branches))
    return Seq(tuple(prefix) + (alt,)) if prefix else alt


def _parse_sequence(src: _Source, state: _State) -> list:
    items: list = []
    while True:
        ch = src.peek()
        if ch is None or ch in "|)":
            break
        start = src.i
        src.get()
        if ch == "\\":
            items.append(_escape(src, start))
        elif ch not in _SPECIAL:
            items.append(Literal(ch))
        elif ch == "[":
            items.append(_parse_set(src, start))
        elif ch in _REPEAT_CHARS:
            _apply_quantifier(src, ch, start, items)
        elif ch == ".":
            items.append(Any())
        elif ch == "(":
            items.append(_parse_group(src, state, start))
        elif ch == "^":
            items.append(At("begin"))
        elif ch == "$":
            items.append(At("end"))
        else:  # pragma: no cover - every special char is handled above
            raise src.error(f"unexpected character {ch!r}", start)
    return items


def _parse_group(src: _Source, state: _State, start: int) -> Group:
    index: int | None
    if src.match("?"):
        if not src.match(":"):
            raise src.error("unsupported group extension", start)
        index = None
    else:
        state.groups += 1
        index = state.groups
    body = _parse_alternation(src, state)
    if not src.match(")"):
        raise src.error("missing ), unterminated subpattern", start)
    return Group(index, body)


def _read_int(src: _Source) -> str:
    digits = ""
    while src.peek() is not None and src.peek() in _DIGITS:
        digits += src.get()
    return digits


def _apply_quantifier(src: _Source, ch: str, start: int, items: list) -> None:
    if ch == "*":
        lo, hi = 0, None
    elif ch == "+":
        lo, hi = 1, None
    elif ch == "?":
        lo, hi = 0, 1
    else:  # "{"
        lo_s = _read_int(src)
        if src.match(","):
            hi_s = _read_int(src)
        else:
            hi_s = lo_s
            if not lo_s:
                raise src.error("bad quantifier syntax", start)
        if not src.match("}"):
            raise src.error("bad quantifier syntax", start)
        lo = int(lo_s) if lo_s else 0
        hi = int(hi_s) if hi_s else None
        if hi is not None and hi < lo:
            raise src.error("min repeat greater than max repeat", start)

    if not items or isinstance(items[-1], At):
        raise src.error("nothing to repeat", start)
    if isinstance(items[-1], Repeat):
        raise src.error("multiple repeat", start)
    greedy = not src.match("?")
    body = items[-1]
    if isinstance(body, Group) and body.index is None:
        body = body.body  # (?:...) is transparent under a quantifier
    items[-1] = Repeat(body, lo, hi, greedy)
    nxt = src.peek()
    if nxt is not None and nxt in _REPEAT_CHARS:
        raise src.error("multiple repeat", src.i)


def _escape(src: _Source, start: int):
    ch = src.get()
    if ch is None:
        raise src.error("bad escape (end of pattern)", start)
    if ch in _CATEGORIES:
        return CharSet(False, (ch,))
    if ch in _CONTROL_ESCAPES:
        return Literal(_CONTROL_ESCAPES[ch])
    if ch in _ASCII_ALNUM:
        raise src.error(f"bad escape \\{ch}", start)
    return Literal(ch)


def _class_escape(src: _Source, start: int):
    """Escape inside a set: returns a ``str`` literal char or a category tuple."""
    ch = src.get()
    if ch is None:
        raise src.error("bad escape (end of pattern)", start)
    if ch in _CATEGORIES:
        return ("cat", ch)
    if ch in _CONTROL_ESCAPES:
        return _CONTROL_ESCAPES[ch]
    if ch in _ASCII_ALNUM:
        raise src.error(f"bad escape \\{ch}", start)
    return ch


def _parse_set(src: _Source, start: int):
    items: list = []
    negated = src.match("^")
    while True:
        pos = src.i
        ch = src.get()
        if ch is None:
            raise src.error("unterminated character set", start)
        if ch == "]" and items:
            break
        code1 = _class_escape(src, pos) if ch == "\\" else ch
        if src.match("-"):
            pos2 = src.i
            that = src.get()
            if that is None:
                raise src.error("unterminated character set", start)
            if that == "]":
                items.append(_set_item(code1))
                items.append((ord("-"), ord("-")))
                break
            code2 = _class_escape(src, pos2) if that == "\\" else that
            if not isinstance(code1, str) or not isinstance(code2, str):
                raise src.error("bad character range", pos)
            if ord(code2) < ord(code1):
                raise src.error("bad character range", pos)
            items.append((ord(code1), ord(code2)))
        else:
            items.append(_set_item(code1))

    single = len(items) == 1 and isinstance(items[0], tuple) and items[0][0] == items[0][1]
    if single and not negated:
        return Literal(chr(items[0][0]))
    return CharSet(negated, tuple(items))


def _set_item(code):
    if isinstance(code, str):
        return (ord(code), ord(code))
    return code[1]  # category letter
