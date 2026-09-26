"""Compile a parse tree into a backtracking matcher built from closures.

Every compiled node is a function ``m(state, pos) -> bool`` that already knows
its continuation (the matcher for the rest of the pattern). The control flow
deliberately mirrors CPython's ``_sre`` engine opcode by opcode (REPEAT_ONE,
MIN_REPEAT_ONE, REPEAT + MAX_UNTIL / MIN_UNTIL, BRANCH, MARK, ...), including
its capture-mark bookkeeping and its zero-width-iteration protection, so that
match results are identical to the ``re`` module.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

Matcher = Callable[["State", int], bool]

# Python 3.14 changed ``\B`` to match the empty string (it never matched before).
_NONBOUNDARY_MATCHES_EMPTY = sys.version_info >= (3, 14)


class State:
    """Mutable per-attempt matching state (like ``SRE_STATE``)."""

    __slots__ = (
        "text",
        "end",
        "marks",
        "lastmark",
        "repeat",
        "match_all",
        "must_advance",
        "start",
        "endpos",
    )

    def __init__(self, text: str, nmarks: int) -> None:
        self.text = text
        self.end = len(text)
        self.marks = [-1] * nmarks
        self.lastmark = -1
        self.repeat: _Rep | None = None
        self.match_all = False
        self.must_advance = False
        self.start = 0
        self.endpos = -1

    def reset(self, start: int) -> None:
        self.lastmark = -1
        self.repeat = None
        self.start = start
        self.endpos = -1


class _Rep:
    """Repeat context of one execution of a general REPEAT."""

    __slots__ = ("count", "last_ptr", "prev")

    def __init__(self, prev: _Rep | None) -> None:
        self.count = -1
        self.last_ptr = -1
        self.prev = prev


# --------------------------------------------------------------------------
# character predicates


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


_CATEGORIES: dict[str, Callable[[str], bool]] = {
    "digit": str.isdecimal,
    "notdigit": lambda ch: not ch.isdecimal(),
    "space": str.isspace,
    "notspace": lambda ch: not ch.isspace(),
    "word": _is_word,
    "notword": lambda ch: not _is_word(ch),
}


def _set_predicate(negate: bool, items: tuple) -> Callable[[str], bool]:
    lits = frozenset(item[1] for item in items if item[0] == "lit")
    ranges = tuple((item[1], item[2]) for item in items if item[0] == "range")
    cats = tuple(_CATEGORIES[item[1]] for item in items if item[0] == "cat")

    def contains(ch: str) -> bool:
        if ch in lits:
            return True
        if ranges:
            o = ord(ch)
            for lo, hi in ranges:
                if lo <= o <= hi:
                    return True
        for cat in cats:
            if cat(ch):
                return True
        return False

    if negate:
        return lambda ch: not contains(ch)
    return contains


def _char_predicate(node: tuple) -> Callable[[str], bool]:
    kind = node[0]
    if kind == "lit":
        c = node[1]
        return lambda ch: ch == c
    if kind == "notlit":
        c = node[1]
        return lambda ch: ch != c
    if kind == "any":
        return lambda ch: ch != "\n"
    if kind == "in":
        return _set_predicate(node[1], node[2])
    raise AssertionError(node)  # pragma: no cover


_UNIT_KINDS = frozenset(("lit", "notlit", "any", "in"))


def _simple_unit(seq: list) -> tuple | None:
    """Return the single-character node if ``seq`` is sre-"simple"."""
    if len(seq) != 1:
        return None
    node = seq[0]
    if node[0] == "group":
        if node[1] is None:
            return _simple_unit(node[2])
        return None
    if node[0] in _UNIT_KINDS:
        return node
    return None


# --------------------------------------------------------------------------
# compiler


class Compiler:
    def __init__(self, ngroups: int) -> None:
        self.ngroups = ngroups
        self.has_marks = ngroups > 0
        self.size = 0

    def compile(self, seq: list) -> Matcher:
        def success(s: State, p: int) -> bool:
            if s.match_all and p != s.end:
                return False
            if s.must_advance and p == s.start:
                return False
            s.endpos = p
            return True

        return self.seq(seq, success)

    def seq(self, seq: list, nxt: Matcher) -> Matcher:
        i = len(seq)
        while i > 0:
            node = seq[i - 1]
            if node[0] == "lit":
                j = i - 1
                while j > 0 and seq[j - 1][0] == "lit":
                    j -= 1
                nxt = self.literal("".join(n[1] for n in seq[j:i]), nxt)
                i = j
            else:
                nxt = self.node(node, nxt)
                i -= 1
        return nxt

    def node(self, node: tuple, nxt: Matcher) -> Matcher:
        self.size += 1
        kind = node[0]
        if kind == "lit":
            return self.literal(node[1], nxt)
        if kind in _UNIT_KINDS:
            return self.char(_char_predicate(node), nxt)
        if kind == "at":
            return self.at(node[1], nxt)
        if kind == "group":
            return self.group(node[1], node[2], nxt)
        if kind == "branch":
            return self.branch(node[1], nxt)
        if kind == "repeat":
            _, mn, mx, greedy, body = node
            unit = _simple_unit(body)
            if unit is not None:
                pred = _char_predicate(unit)
                if greedy:
                    return self.repeat_one(pred, mn, mx, nxt)
                return self.min_repeat_one(pred, mn, mx, nxt)
            return self.repeat(body, mn, mx, greedy, nxt)
        if kind == "groupref":
            return self.groupref(node[1], nxt)
        raise AssertionError(node)  # pragma: no cover

    # -- single characters -------------------------------------------------

    def literal(self, lit: str, nxt: Matcher) -> Matcher:
        self.size += 1
        n = len(lit)
        if n == 1:

            def m1(s: State, p: int) -> bool:
                if p < s.end and s.text[p] == lit:
                    return nxt(s, p + 1)
                return False

            return m1

        def m(s: State, p: int) -> bool:
            if s.text.startswith(lit, p):
                return nxt(s, p + n)
            return False

        return m

    def char(self, pred: Callable[[str], bool], nxt: Matcher) -> Matcher:
        def m(s: State, p: int) -> bool:
            if p < s.end and pred(s.text[p]):
                return nxt(s, p + 1)
            return False

        return m

    # -- assertions ----------------------------------------------------------

    def at(self, kind: str, nxt: Matcher) -> Matcher:
        if kind in ("begin", "begin_string"):

            def m_begin(s: State, p: int) -> bool:
                return p == 0 and nxt(s, p)

            return m_begin
        if kind == "end":

            def m_end(s: State, p: int) -> bool:
                end = s.end
                if p == end or (p + 1 == end and s.text[p] == "\n"):
                    return nxt(s, p)
                return False

            return m_end
        if kind == "end_string":

            def m_end_string(s: State, p: int) -> bool:
                return p == s.end and nxt(s, p)

            return m_end_string

        want_boundary = kind == "boundary"
        empty_result = not want_boundary and _NONBOUNDARY_MATCHES_EMPTY

        def m_boundary(s: State, p: int) -> bool:
            end = s.end
            if end == 0:
                return empty_result and nxt(s, p)
            text = s.text
            that = p > 0 and _is_word(text[p - 1])
            this = p < end and _is_word(text[p])
            if (this != that) == want_boundary:
                return nxt(s, p)
            return False

        return m_boundary

    # -- groups --------------------------------------------------------------

    def group(self, gid: int | None, body: list, nxt: Matcher) -> Matcher:
        if gid is None:
            return self.seq(body, nxt)
        i_open = 2 * (gid - 1)
        i_close = i_open + 1

        def close(s: State, p: int) -> bool:
            if i_close > s.lastmark:
                marks = s.marks
                for j in range(s.lastmark + 1, i_close):
                    marks[j] = -1
                s.lastmark = i_close
            s.marks[i_close] = p
            return nxt(s, p)

        inner = self.seq(body, close)

        def open_(s: State, p: int) -> bool:
            if i_open > s.lastmark:
                marks = s.marks
                for j in range(s.lastmark + 1, i_open):
                    marks[j] = -1
                s.lastmark = i_open
            s.marks[i_open] = p
            return inner(s, p)

        return open_

    def groupref(self, gid: int, nxt: Matcher) -> Matcher:
        i = 2 * (gid - 1)

        def m(s: State, p: int) -> bool:
            if i >= s.lastmark:
                return False
            a = s.marks[i]
            b = s.marks[i + 1]
            if a < 0 or b < 0 or b < a:
                return False
            n = b - a
            text = s.text
            if p + n > s.end or text[p : p + n] != text[a:b]:
                return False
            return nxt(s, p + n)

        return m

    # -- alternation ---------------------------------------------------------

    def branch(self, alternatives: list, nxt: Matcher) -> Matcher:
        alts = tuple(self.seq(alt, nxt) for alt in alternatives)
        if not self.has_marks:

            def m_nomarks(s: State, p: int) -> bool:
                for alt in alts:
                    if alt(s, p):
                        return True
                return False

            return m_nomarks

        def m(s: State, p: int) -> bool:
            lastmark = s.lastmark
            saved = s.marks[:] if s.repeat is not None else None
            for alt in alts:
                if alt(s, p):
                    return True
                if saved is not None:
                    s.marks[:] = saved
                s.lastmark = lastmark
            return False

        return m

    # -- single-character repeats (REPEAT_ONE / MIN_REPEAT_ONE) --------------

    def repeat_one(
        self, pred: Callable[[str], bool], mn: int, mx: int | None, nxt: Matcher
    ) -> Matcher:
        has_marks = self.has_marks

        def m(s: State, p: int) -> bool:
            end = s.end
            if mn > end - p:
                return False
            limit = end if mx is None else min(end, p + mx)
            text = s.text
            q = p
            while q < limit and pred(text[q]):
                q += 1
            stop = p + mn
            if q < stop:
                return False
            if has_marks:
                lastmark = s.lastmark
                saved = s.marks[:] if s.repeat is not None else None
                while q >= stop:
                    if nxt(s, q):
                        return True
                    if saved is not None:
                        s.marks[:] = saved
                    s.lastmark = lastmark
                    q -= 1
                return False
            while q >= stop:
                if nxt(s, q):
                    return True
                q -= 1
            return False

        return m

    def min_repeat_one(
        self, pred: Callable[[str], bool], mn: int, mx: int | None, nxt: Matcher
    ) -> Matcher:
        has_marks = self.has_marks

        def m(s: State, p: int) -> bool:
            end = s.end
            if mn > end - p:
                return False
            text = s.text
            q = p
            stop = p + mn
            while q < stop:
                if not pred(text[q]):
                    return False
                q += 1
            count = mn
            lastmark = s.lastmark
            saved = s.marks[:] if has_marks and s.repeat is not None else None
            while mx is None or count <= mx:
                if nxt(s, q):
                    return True
                if saved is not None:
                    s.marks[:] = saved
                s.lastmark = lastmark
                if q < end and pred(text[q]):
                    q += 1
                    count += 1
                else:
                    break
            return False

        return m

    # -- general repeats (REPEAT + MAX_UNTIL / MIN_UNTIL) --------------------

    def repeat(
        self, body_seq: list, mn: int, mx: int | None, greedy: bool, nxt: Matcher
    ) -> Matcher:
        body: Matcher

        if greedy:

            def until(s: State, p: int) -> bool:
                rep = s.repeat
                assert rep is not None
                count = rep.count + 1
                if count < mn:
                    rep.count = count
                    if body(s, p):
                        return True
                    rep.count = count - 1
                    return False
                if (mx is None or count < mx) and p != rep.last_ptr:
                    rep.count = count
                    lastmark = s.lastmark
                    saved = s.marks[:]
                    saved_last_ptr = rep.last_ptr
                    rep.last_ptr = p
                    ok = body(s, p)
                    rep.last_ptr = saved_last_ptr
                    if ok:
                        return True
                    s.marks[:] = saved
                    s.lastmark = lastmark
                    rep.count = count - 1
                s.repeat = rep.prev
                if nxt(s, p):
                    return True
                s.repeat = rep
                return False

        else:

            def until(s: State, p: int) -> bool:
                rep = s.repeat
                assert rep is not None
                count = rep.count + 1
                if count < mn:
                    rep.count = count
                    if body(s, p):
                        return True
                    rep.count = count - 1
                    return False
                prev = rep.prev
                s.repeat = prev
                lastmark = s.lastmark
                saved = s.marks[:] if prev is not None else None
                if nxt(s, p):
                    return True
                s.repeat = rep
                if saved is not None:
                    s.marks[:] = saved
                s.lastmark = lastmark
                if (mx is not None and count >= mx) or p == rep.last_ptr:
                    return False
                rep.count = count
                saved_last_ptr = rep.last_ptr
                rep.last_ptr = p
                ok = body(s, p)
                rep.last_ptr = saved_last_ptr
                if ok:
                    return True
                rep.count = count - 1
                return False

        body = self.seq(body_seq, until)

        def m(s: State, p: int) -> bool:
            rep = _Rep(s.repeat)
            s.repeat = rep
            if until(s, p):
                return True
            s.repeat = rep.prev
            return False

        return m
