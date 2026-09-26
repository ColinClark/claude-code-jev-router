"""Backtracking matcher built from the parser's AST.

Each AST node compiles to a function ``m(s, i, caps, k) -> bool`` in
continuation-passing style: it tries to match at ``s[i:]`` and, for every way it
can match (in ``re``'s preference order), calls the continuation ``k(j)`` with
the end position. ``caps`` is a list of ``(start, end)`` spans (or ``None``)
indexed by group number; a node that sets a capture undoes it on failure.

Repetition follows CPython's ``_sre`` rules exactly, including its zero-width
protection: after the minimum count, another iteration is only attempted if the
previous optional iteration consumed input.
"""

from __future__ import annotations

from collections.abc import Callable

Cont = Callable[[int], bool]
Matcher = Callable[[str, int, list, Cont], bool]


def _single_char_pred(node) -> Callable[[str], bool] | None:
    """Predicate if ``node`` always matches exactly one character and has no groups."""
    kind = node[0]
    if kind == "char":
        return node[1]
    if kind == "lit":
        c = node[1]
        return c.__eq__
    if kind == "group" and node[1] is None:
        return _single_char_pred(node[2])
    return None


def build(node) -> Matcher:
    kind = node[0]
    if kind == "lit":
        return _literal(node[1])
    if kind == "char":
        return _char(node[1])
    if kind == "bol":
        return lambda s, i, caps, k: i == 0 and k(i)
    if kind == "eol":

        def eol(s: str, i: int, caps: list, k: Cont) -> bool:
            n = len(s)
            return (i == n or (i == n - 1 and s[i] == "\n")) and k(i)

        return eol
    if kind == "seq":
        return _sequence(node[1])
    if kind == "alt":
        return _alternation([build(b) for b in node[1]])
    if kind == "group":
        return _group(node[1], build(node[2]))
    if kind == "rep":
        _, body, mn, mx, lazy = node
        pred = _single_char_pred(body)
        if pred is not None:
            return (_lazy_single if lazy else _greedy_single)(pred, mn, mx)
        return _general_repeat(build(body), mn, mx, lazy)
    raise AssertionError(f"unknown node {kind!r}")


def _literal(c: str) -> Matcher:
    def lit(s: str, i: int, caps: list, k: Cont) -> bool:
        return i < len(s) and s[i] == c and k(i + 1)

    return lit


def _literal_run(text: str) -> Matcher:
    n = len(text)

    def run(s: str, i: int, caps: list, k: Cont) -> bool:
        return s.startswith(text, i) and k(i + n)

    return run


def _char(pred: Callable[[str], bool]) -> Matcher:
    def char(s: str, i: int, caps: list, k: Cont) -> bool:
        return i < len(s) and pred(s[i]) and k(i + 1)

    return char


def _sequence(items: list) -> Matcher:
    # Merge adjacent literal characters into one startswith() check.
    matchers: list[Matcher] = []
    run: list[str] = []
    for item in items:
        if item[0] == "lit":
            run.append(item[1])
            continue
        if run:
            matchers.append(_literal_run("".join(run)))
            run = []
        matchers.append(build(item))
    if run:
        matchers.append(_literal_run("".join(run)))

    if not matchers:
        return lambda s, i, caps, k: k(i)
    m = matchers[-1]
    for first in reversed(matchers[:-1]):
        m = _then(first, m)
    return m


def _then(first: Matcher, rest: Matcher) -> Matcher:
    def seq(s: str, i: int, caps: list, k: Cont) -> bool:
        return first(s, i, caps, lambda j: rest(s, j, caps, k))

    return seq


def _alternation(branches: list[Matcher]) -> Matcher:
    def alt(s: str, i: int, caps: list, k: Cont) -> bool:
        for b in branches:
            if b(s, i, caps, k):
                return True
        return False

    return alt


def _group(index: int | None, inner: Matcher) -> Matcher:
    if index is None:
        return inner

    def group(s: str, i: int, caps: list, k: Cont) -> bool:
        def close(j: int) -> bool:
            old = caps[index]
            caps[index] = (i, j)
            if k(j):
                return True
            caps[index] = old
            return False

        return inner(s, i, caps, close)

    return group


def _greedy_single(pred: Callable[[str], bool], mn: int, mx: int | None) -> Matcher:
    def rep(s: str, i: int, caps: list, k: Cont) -> bool:
        n = len(s)
        limit = n if mx is None else min(n, i + mx)
        j = i
        while j < limit and pred(s[j]):
            j += 1
        low = i + mn
        while j >= low:
            if k(j):
                return True
            j -= 1
        return False

    return rep


def _lazy_single(pred: Callable[[str], bool], mn: int, mx: int | None) -> Matcher:
    def rep(s: str, i: int, caps: list, k: Cont) -> bool:
        n = len(s)
        limit = n if mx is None else min(n, i + mx)
        j = i
        low = i + mn
        while j < low:
            if j >= n or not pred(s[j]):
                return False
            j += 1
        while True:
            if k(j):
                return True
            if j >= limit or not pred(s[j]):
                return False
            j += 1

    return rep


def _general_repeat(body: Matcher, mn: int, mx: int | None, lazy: bool) -> Matcher:
    # ``count`` is the number of completed iterations; ``last`` is the start of
    # the most recent optional iteration (-1 if none), mirroring _sre's
    # MAX_UNTIL / MIN_UNTIL ``last_ptr`` zero-width protection.
    def rep(s: str, i: int, caps: list, k: Cont) -> bool:
        def step(count: int, pos: int, last: int) -> bool:
            if count < mn:
                return body(s, pos, caps, lambda j: step(count + 1, j, last))
            more = (mx is None or count < mx) and pos != last
            if lazy:
                if k(pos):
                    return True
                return more and body(s, pos, caps, lambda j: step(count + 1, j, pos))
            if more and body(s, pos, caps, lambda j: step(count + 1, j, pos)):
                return True
            return k(pos)

        return step(0, i, -1)

    return rep
