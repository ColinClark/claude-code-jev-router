"""Compile an AST into a backtracking matcher built from continuation-passing closures.

Every compiled node is a function ``m(ctx, i, k) -> bool`` that tries to match
at position ``i`` of ``ctx.text`` and, for each way it can match (in the
priority order Python's ``re`` uses), calls the continuation ``k(j)`` with the
end position ``j``. It returns True as soon as a continuation succeeds, and
False once every alternative is exhausted. Capture marks live in
``ctx.marks``; every node that writes a mark restores it before returning
False, so a failed branch never leaves stale captures behind.

Repetition of complex bodies follows the semantics of CPython's ``_sre``
``REPEAT``/``MAX_UNTIL``/``MIN_UNTIL`` opcodes, including its zero-width
protection: once the minimum count is reached, another iteration is only
attempted if the previous iteration consumed input.
"""

from __future__ import annotations

from collections.abc import Callable

from .nodes import (
    Alternation,
    Anchor,
    AnyChar,
    CharClass,
    Group,
    Literal,
    Node,
    Repeat,
    Sequence,
)

_DIGIT = frozenset("0123456789")
_WORD = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_SPACE = frozenset(" \t\n\r\f\v")
CLASS_SETS: dict[str, tuple[frozenset[str], bool]] = {
    "d": (_DIGIT, False),
    "D": (_DIGIT, True),
    "w": (_WORD, False),
    "W": (_WORD, True),
    "s": (_SPACE, False),
    "S": (_SPACE, True),
}


class Context:
    """Mutable per-attempt matching state."""

    __slots__ = ("text", "n", "marks", "end")

    def __init__(self, text: str, ngroups: int) -> None:
        self.text = text
        self.n = len(text)
        self.marks = [-1] * (2 * ngroups + 2)
        self.end = -1


Cont = Callable[[int], bool]
MatchFn = Callable[[Context, int, Cont], bool]
CharPred = Callable[[str], bool]


def _class_predicate(node: CharClass) -> CharPred:
    chars = set(node.chars)
    neg_sets: list[frozenset[str]] = []
    for c in node.classes:
        s, neg = CLASS_SETS[c]
        if neg:
            neg_sets.append(s)
        else:
            chars |= s
    fchars = frozenset(chars)
    ranges = node.ranges
    negated = node.negated

    def pred(ch: str) -> bool:
        if ch in fchars:
            return not negated
        o = ord(ch)
        for lo, hi in ranges:
            if lo <= o <= hi:
                return not negated
        for s in neg_sets:
            if ch not in s:
                return not negated
        return negated

    return pred


def _char_predicate(node: Node) -> CharPred | None:
    """Return a predicate if ``node`` always matches exactly one character."""
    if isinstance(node, Literal) and len(node.text) == 1:
        c = node.text
        return lambda ch: ch == c
    if isinstance(node, AnyChar):
        return lambda ch: ch != "\n"
    if isinstance(node, CharClass):
        return _class_predicate(node)
    if isinstance(node, Group) and node.index is None:
        return _char_predicate(node.body)
    if isinstance(node, Sequence) and len(node.items) == 1:
        return _char_predicate(node.items[0])
    return None


def _is_word(text: str, i: int) -> bool:
    return 0 <= i < len(text) and text[i] in _WORD


def _anchor(kind: str) -> MatchFn:
    if kind in ("bol", "A"):

        def m(ctx: Context, i: int, k: Cont) -> bool:
            return i == 0 and k(i)

    elif kind == "eol":

        def m(ctx: Context, i: int, k: Cont) -> bool:
            n = ctx.n
            if i == n or (i == n - 1 and ctx.text[i] == "\n"):
                return k(i)
            return False

    elif kind == "Z":

        def m(ctx: Context, i: int, k: Cont) -> bool:
            return i == ctx.n and k(i)

    elif kind == "b":

        def m(ctx: Context, i: int, k: Cont) -> bool:
            if ctx.n == 0:
                return False
            return _is_word(ctx.text, i - 1) != _is_word(ctx.text, i) and k(i)

    elif kind == "B":

        def m(ctx: Context, i: int, k: Cont) -> bool:
            if ctx.n == 0:
                return False
            return _is_word(ctx.text, i - 1) == _is_word(ctx.text, i) and k(i)

    else:  # pragma: no cover - parser never produces other kinds
        raise ValueError(f"unknown anchor {kind!r}")
    return m


def _pred_matcher(pred: CharPred) -> MatchFn:
    def m(ctx: Context, i: int, k: Cont) -> bool:
        return i < ctx.n and pred(ctx.text[i]) and k(i + 1)

    return m


def _literal(text: str) -> MatchFn:
    if len(text) == 1:

        def m1(ctx: Context, i: int, k: Cont) -> bool:
            return i < ctx.n and ctx.text[i] == text and k(i + 1)

        return m1
    size = len(text)

    def m(ctx: Context, i: int, k: Cont) -> bool:
        return ctx.text.startswith(text, i) and k(i + size)

    return m


def _chain(a: MatchFn, b: MatchFn) -> MatchFn:
    def m(ctx: Context, i: int, k: Cont) -> bool:
        return a(ctx, i, lambda j: b(ctx, j, k))

    return m


def _sequence(items: tuple[Node, ...]) -> MatchFn:
    # Merge adjacent literals into a single string comparison.
    merged: list[Node] = []
    for item in items:
        if isinstance(item, Literal) and merged and isinstance(merged[-1], Literal):
            merged[-1] = Literal(merged[-1].text + item.text)
        else:
            merged.append(item)
    fns = [build(x) for x in merged]
    if not fns:

        def empty(ctx: Context, i: int, k: Cont) -> bool:
            return k(i)

        return empty
    fn = fns[-1]
    for a in reversed(fns[:-1]):
        fn = _chain(a, fn)
    return fn


def _alternation(branches: tuple[Node, ...]) -> MatchFn:
    fns = [build(b) for b in branches]

    def m(ctx: Context, i: int, k: Cont) -> bool:
        for f in fns:
            if f(ctx, i, k):
                return True
        return False

    return m


def _group(index: int, body: MatchFn) -> MatchFn:
    s_idx = 2 * index
    e_idx = s_idx + 1

    def m(ctx: Context, i: int, k: Cont) -> bool:
        def close(j: int) -> bool:
            marks = ctx.marks
            old_s, old_e = marks[s_idx], marks[e_idx]
            marks[s_idx] = i
            marks[e_idx] = j
            if k(j):
                return True
            marks[s_idx] = old_s
            marks[e_idx] = old_e
            return False

        return body(ctx, i, close)

    return m


def _simple_repeat(pred: CharPred, lo: int, hi: int | None, greedy: bool) -> MatchFn:
    """Repetition of a single-character matcher (like sre's REPEAT_ONE)."""
    if greedy:

        def mg(ctx: Context, i: int, k: Cont) -> bool:
            text = ctx.text
            limit = ctx.n if hi is None else min(ctx.n, i + hi)
            j = i
            while j < limit and pred(text[j]):
                j += 1
            stop = i + lo
            while j >= stop:
                if k(j):
                    return True
                j -= 1
            return False

        return mg

    def ml(ctx: Context, i: int, k: Cont) -> bool:
        text = ctx.text
        n = ctx.n
        j = i
        stop = i + lo
        while j < stop:
            if j >= n or not pred(text[j]):
                return False
            j += 1
        limit = n if hi is None else min(n, i + hi)
        while True:
            if k(j):
                return True
            if j < limit and pred(text[j]):
                j += 1
            else:
                return False

    return ml


def _general_repeat(body: MatchFn, lo: int, hi: int | None, greedy: bool) -> MatchFn:
    """Repetition of an arbitrary body, mirroring sre's MAX_UNTIL / MIN_UNTIL."""

    def m(ctx: Context, i: int, k: Cont) -> bool:
        count = -1  # iterations completed so far (sre starts at -1 and increments)
        last = -1  # position at which the most recent optional iteration started

        def until(p: int) -> bool:
            nonlocal count, last
            c = count + 1
            if c < lo:
                count = c
                if body(ctx, p, until):
                    return True
                count = c - 1
                return False
            if greedy:
                if (hi is None or c < hi) and p != last:
                    count = c
                    old_last = last
                    last = p
                    if body(ctx, p, until):
                        return True
                    last = old_last
                    count = c - 1
                return k(p)
            # lazy: try the continuation first, then one more iteration
            if k(p):
                return True
            if (hi is not None and c >= hi) or p == last:
                return False
            count = c
            old_last = last
            last = p
            if body(ctx, p, until):
                return True
            last = old_last
            count = c - 1
            return False

        return until(i)

    return m


def build(node: Node) -> MatchFn:
    """Compile an AST node into a matcher function."""
    if isinstance(node, Literal):
        return _literal(node.text)
    if isinstance(node, (AnyChar, CharClass)):
        pred = _char_predicate(node)
        assert pred is not None
        return _pred_matcher(pred)
    if isinstance(node, Anchor):
        return _anchor(node.kind)
    if isinstance(node, Sequence):
        return _sequence(node.items)
    if isinstance(node, Alternation):
        return _alternation(node.branches)
    if isinstance(node, Group):
        body = build(node.body)
        if node.index is None:
            return body
        return _group(node.index, body)
    if isinstance(node, Repeat):
        pred = _char_predicate(node.body)
        if pred is not None:
            return _simple_repeat(pred, node.min, node.max, node.greedy)
        return _general_repeat(build(node.body), node.min, node.max, node.greedy)
    raise TypeError(f"unknown node {node!r}")  # pragma: no cover


def count_nodes(node: Node) -> int:
    """Rough size of the AST, used to size the recursion budget."""
    if isinstance(node, Sequence):
        return 1 + sum(count_nodes(x) for x in node.items)
    if isinstance(node, Alternation):
        return 1 + sum(count_nodes(x) for x in node.branches)
    if isinstance(node, (Group, Repeat)):
        return 1 + count_nodes(node.body)
    return 1
