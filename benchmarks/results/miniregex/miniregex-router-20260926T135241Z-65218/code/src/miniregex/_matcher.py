"""Backtracking matcher emulating CPython's ``_sre`` engine (no flags, ASCII classes).

Usage::

    prog = compile_pattern(parse(pattern))        # reusable, stateless
    res = prog.run(text, pos, endpos, mode)       # MatchResult | None

``mode`` is ``"match"`` (anchored at ``pos``), ``"fullmatch"`` (anchored at ``pos``
and must end at ``endpos``) or ``"search"`` (first start in ``pos..endpos``).
``must_advance=True`` (search only) rejects an empty match at ``pos``; this is what
``re`` uses for findall/finditer after an empty match. ``^`` matches only at index 0
of ``text`` (never at ``pos > 0``); ``$`` matches at ``endpos`` or just before a
final ``"\\n"`` at ``endpos - 1``. Positions are clamped like ``re`` does.

``MatchResult.spans[g - 1]`` is ``(start, end)`` for group ``g``'s last successful
participation, or ``None`` if it did not participate; ``lastindex`` mirrors
``re.Match.lastindex`` (``None`` when no group closed).

Implementation: nodes compile to continuation-passing closures ``f(st, i, k)``;
``k(j)`` runs the rest of the pattern. Capture marks, ``lastmark``/``lastindex``
and their save/restore points, the REPEAT/MAX_UNTIL/MIN_UNTIL zero-width guard,
and REPEAT_ONE for single-character bodies all follow ``_sre.c`` so that group
results agree with ``re`` including its corner cases.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from ._ast import Alt, Any, At, CharSet, Group, Literal, Pattern, Repeat, Seq
from ._errors import RegexError

_DIGIT = frozenset("0123456789")
_WORD = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_SPACE = frozenset(" \t\n\r\f\v")


@dataclass(frozen=True)
class MatchResult:
    start: int
    end: int
    spans: tuple  # per group 1..n: (start, end) or None
    lastindex: int | None


class _Rep:
    __slots__ = ("count", "last_ptr", "prev", "tail")

    def __init__(self, prev, tail) -> None:
        self.count = -1
        self.last_ptr = -1
        self.prev = prev
        self.tail = tail


class _State:
    __slots__ = (
        "end",
        "final",
        "lastindex",
        "lastmark",
        "marks",
        "match_all",
        "must_advance",
        "repeat",
        "start",
        "text",
    )


def _set_mark(st: _State, idx: int, pos: int) -> None:
    if idx & 1:
        st.lastindex = idx // 2 + 1
    if idx > st.lastmark:
        marks = st.marks
        for j in range(st.lastmark + 1, idx):
            marks[j] = None
        st.lastmark = idx
    st.marks[idx] = pos


def _category_pred(cat: str):
    base = {"d": _DIGIT, "w": _WORD, "s": _SPACE}[cat.lower()]
    if cat.islower():
        return base.__contains__
    return lambda c: c not in base


def _char_pred(node):
    """Predicate for single-character nodes, or None if ``node`` is not one."""
    if isinstance(node, Literal):
        ch = node.ch
        return lambda c: c == ch
    if isinstance(node, Any):
        return lambda c: c != "\n"
    if isinstance(node, CharSet):
        ranges = [it for it in node.items if isinstance(it, tuple)]
        cats = [_category_pred(it) for it in node.items if isinstance(it, str)]
        negated = node.negated

        def pred(c: str) -> bool:
            o = ord(c)
            hit = any(lo <= o <= hi for lo, hi in ranges) or any(p(c) for p in cats)
            return hit != negated

        return pred
    if isinstance(node, Group) and node.index is None:
        return _char_pred(node.body)
    if isinstance(node, Seq) and len(node.items) == 1:
        return _char_pred(node.items[0])
    return None


def _compile(node):
    pred = _char_pred(node)
    if pred is not None:
        def f_char(st, i, k):
            if i < st.end and pred(st.text[i]):
                return k(i + 1)
            return False
        return f_char
    if isinstance(node, Seq):
        return _compile_seq([_compile(n) for n in node.items])
    if isinstance(node, At):
        return _compile_at(node.kind)
    if isinstance(node, Group):
        body = _compile(node.body)
        if node.index is None:
            return body
        return _compile_group(node.index, body)
    if isinstance(node, Alt):
        return _compile_branch([_compile(b) for b in node.branches])
    if isinstance(node, Repeat):
        pred = _char_pred(node.body)
        if pred is not None:
            if node.greedy:
                return _compile_repeat_one(pred, node.min, node.max)
            return _compile_min_repeat_one(pred, node.min, node.max)
        return _compile_repeat(_compile(node.body), node.min, node.max, node.greedy)
    raise RegexError(f"unknown node {node!r}")  # pragma: no cover


def _compile_seq(fs):
    if not fs:
        return lambda st, i, k: k(i)
    if len(fs) == 1:
        return fs[0]
    head, rest = fs[0], _compile_seq(fs[1:])

    def f_seq(st, i, k):
        return head(st, i, lambda j: rest(st, j, k))

    return f_seq


def _compile_at(kind: str):
    if kind == "begin":
        def f_begin(st, i, k):
            return i == 0 and k(i)
        return f_begin

    def f_end(st, i, k):
        end = st.end
        if i == end or (i + 1 == end and st.text[i] == "\n"):
            return k(i)
        return False

    return f_end


def _compile_group(index: int, body):
    m_open = 2 * (index - 1)
    m_close = m_open + 1

    def f_group(st, i, k):
        _set_mark(st, m_open, i)

        def close(j):
            _set_mark(st, m_close, j)
            return k(j)

        return body(st, i, close)

    return f_group


def _compile_branch(branches):
    def f_branch(st, i, k):
        lastmark, lastindex = st.lastmark, st.lastindex
        saved = st.marks[: lastmark + 1] if st.repeat is not None else None
        for b in branches:
            if b(st, i, k):
                return True
            if saved is not None:
                st.marks[: lastmark + 1] = saved
            st.lastmark, st.lastindex = lastmark, lastindex
        return False

    return f_branch


def _compile_repeat_one(pred, mn: int, mx: int | None):
    def f_repeat_one(st, i, k):
        text, end = st.text, st.end
        limit = end if mx is None else min(end, i + mx)
        j = i
        while j < limit and pred(text[j]):
            j += 1
        if j - i < mn:
            return False
        lastmark, lastindex = st.lastmark, st.lastindex
        saved = st.marks[: lastmark + 1] if st.repeat is not None else None
        low = i + mn
        while j >= low:
            if k(j):
                return True
            if saved is not None:
                st.marks[: lastmark + 1] = saved
            st.lastmark, st.lastindex = lastmark, lastindex
            j -= 1
        return False

    return f_repeat_one


def _compile_min_repeat_one(pred, mn: int, mx: int | None):
    def f_min_repeat_one(st, i, k):
        text, end = st.text, st.end
        j = i
        while j - i < mn:
            if j >= end or not pred(text[j]):
                return False
            j += 1
        lastmark, lastindex = st.lastmark, st.lastindex
        saved = st.marks[: lastmark + 1] if st.repeat is not None else None
        count = mn
        while mx is None or count <= mx:
            if k(j):
                return True
            if saved is not None:
                st.marks[: lastmark + 1] = saved
            st.lastmark, st.lastindex = lastmark, lastindex
            if j >= end or not pred(text[j]):
                break
            j += 1
            count += 1
        return False

    return f_min_repeat_one


def _compile_repeat(body, mn: int, mx: int | None, greedy: bool):
    def until_max(st, i):
        rp = st.repeat
        count = rp.count + 1
        if count < mn:
            rp.count = count
            if body(st, i, lambda j: until(st, j)):
                return True
            rp.count = count - 1
            return False
        if (mx is None or count < mx) and i != rp.last_ptr:
            rp.count = count
            lastmark, lastindex = st.lastmark, st.lastindex
            saved = st.marks[: lastmark + 1]
            old_last = rp.last_ptr
            rp.last_ptr = i
            ok = body(st, i, lambda j: until(st, j))
            rp.last_ptr = old_last
            if ok:
                return True
            st.marks[: lastmark + 1] = saved
            st.lastmark, st.lastindex = lastmark, lastindex
            rp.count = count - 1
        st.repeat = rp.prev
        ok = rp.tail(i)
        st.repeat = rp
        return ok

    def until_min(st, i):
        rp = st.repeat
        count = rp.count + 1
        if count < mn:
            rp.count = count
            if body(st, i, lambda j: until(st, j)):
                return True
            rp.count = count - 1
            return False
        st.repeat = rp.prev
        lastmark, lastindex = st.lastmark, st.lastindex
        saved = st.marks[: lastmark + 1] if st.repeat is not None else None
        ok = rp.tail(i)
        st.repeat = rp
        if ok:
            return True
        if saved is not None:
            st.marks[: lastmark + 1] = saved
        st.lastmark, st.lastindex = lastmark, lastindex
        if (mx is not None and count >= mx) or i == rp.last_ptr:
            return False
        rp.count = count
        old_last = rp.last_ptr
        rp.last_ptr = i
        ok = body(st, i, lambda j: until(st, j))
        rp.last_ptr = old_last
        if ok:
            return True
        rp.count = count - 1
        return False

    until = until_max if greedy else until_min

    def f_repeat(st, i, k):
        rp = _Rep(st.repeat, k)
        st.repeat = rp
        try:
            return until(st, i)
        finally:
            st.repeat = rp.prev

    return f_repeat


class Program:
    """Compiled matcher for one parsed ``Pattern``."""

    def __init__(self, pattern: Pattern) -> None:
        self.pattern = pattern
        self.groups = pattern.groups
        self._code = _compile(pattern.root)

    def run(
        self,
        text: str,
        pos: int = 0,
        endpos: int | None = None,
        mode: str = "search",
        must_advance: bool = False,
    ) -> MatchResult | None:
        n = len(text)
        if endpos is None or endpos > n:
            endpos = n
        elif endpos < 0:
            endpos = 0
        if pos < 0:
            pos = 0
        elif pos > n:
            pos = n
        if mode not in ("match", "fullmatch", "search"):
            raise ValueError(f"bad mode {mode!r}")
        if pos > endpos:
            return None

        st = _State()
        st.text = text
        st.end = endpos
        st.marks = [None] * (2 * self.groups)
        st.repeat = None
        st.match_all = mode == "fullmatch"
        st.final = -1

        def success(j):
            if st.match_all and j != st.end:
                return False
            if st.must_advance and j == st.start:
                return False
            st.final = j
            return True

        old_limit = sys.getrecursionlimit()
        want = 10000 + 40 * (endpos - pos)
        if want > old_limit:
            sys.setrecursionlimit(want)
        try:
            last_start = endpos if mode == "search" else pos
            for start in range(pos, last_start + 1):
                st.lastmark = -1
                st.lastindex = -1
                st.start = start
                st.must_advance = must_advance and start == pos
                if self._code(st, start, success):
                    return self._result(st, start)
            return None
        except RecursionError as exc:  # pragma: no cover - pathological inputs
            raise RegexError("maximum recursion depth exceeded while matching") from exc
        finally:
            if want > old_limit:
                sys.setrecursionlimit(old_limit)

    def _result(self, st: _State, start: int) -> MatchResult:
        spans = []
        marks = st.marks
        for g in range(self.groups):
            a, b = 2 * g, 2 * g + 1
            if b <= st.lastmark and marks[a] is not None and marks[b] is not None:
                spans.append((marks[a], marks[b]))
            else:
                spans.append(None)
        lastindex = st.lastindex if st.lastindex >= 0 else None
        return MatchResult(start, st.final, tuple(spans), lastindex)


def compile_pattern(pattern: Pattern) -> Program:
    """Build a reusable ``Program`` from a parsed ``Pattern``."""
    return Program(pattern)
