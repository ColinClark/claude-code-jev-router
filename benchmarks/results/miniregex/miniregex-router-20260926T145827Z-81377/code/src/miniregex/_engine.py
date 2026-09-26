"""Backtracking matcher compiled from the parser's AST.

Every node becomes a function ``m(s, i, caps, k)`` in continuation-passing
style: it tries to match at ``s[i:]`` and, for each way it can, calls
``k(j, caps2)`` with the end position and updated captures. The first truthy
result from a continuation is returned; ``None`` means failure (and makes the
caller backtrack). ``caps`` is an immutable tuple of ``2 * ngroups`` ints
(start, end per group, ``-1`` when unset), so backtracking restores captures
for free.

The order in which alternatives are explored mirrors CPython's ``_sre``,
including its zero-width protection for repeats, so results are identical to
the ``re`` module.
"""

from __future__ import annotations

from ._parser import is_word


def compile_node(node):
    kind = node[0]
    if kind == "char":
        return _char(node[1])
    if kind == "at":
        return _assertion(node[1])
    if kind == "seq":
        return _seq([compile_node(n) for n in node[1]])
    if kind == "alt":
        return _alt([compile_node(n) for n in node[1]])
    if kind == "group":
        inner = compile_node(node[2])
        if node[1] is None:
            return inner
        return _group(node[1], inner)
    if kind == "rep":
        _, item, lo, hi, greedy = node
        single = _single_char_pred(item)
        if single is not None:
            return _rep_single(single, lo, hi, greedy)
        return _rep(compile_node(item), lo, hi, greedy)
    raise AssertionError(f"unknown node {kind!r}")


def _single_char_pred(node):
    """Return the predicate if ``node`` always matches exactly one character."""
    while node[0] == "group" and node[1] is None:
        node = node[2]
    if node[0] == "char":
        return node[1]
    return None


def _char(pred):
    def m(s, i, caps, k):
        if i < len(s) and pred(s[i]):
            return k(i + 1, caps)
        return None

    return m


def _is_word_at(s, i):
    return 0 <= i < len(s) and is_word(s[i])


def _assertion(kind):
    if kind == "bol" or kind == "A":

        def test(s, i):
            return i == 0
    elif kind == "eol":

        def test(s, i):
            n = len(s)
            return i == n or (i == n - 1 and s[i] == "\n")
    elif kind == "Z":

        def test(s, i):
            return i == len(s)
    elif kind == "b":

        def test(s, i):
            return bool(s) and _is_word_at(s, i - 1) != _is_word_at(s, i)
    elif kind == "B":

        def test(s, i):
            return bool(s) and _is_word_at(s, i - 1) == _is_word_at(s, i)
    else:
        raise AssertionError(kind)

    def m(s, i, caps, k):
        if test(s, i):
            return k(i, caps)
        return None

    return m


def _seq(parts):
    if not parts:
        return lambda s, i, caps, k: k(i, caps)
    m = parts[-1]
    for first in reversed(parts[:-1]):
        m = _seq2(first, m)
    return m


def _seq2(m1, m2):
    def m(s, i, caps, k):
        return m1(s, i, caps, lambda j, c: m2(s, j, c, k))

    return m


def _alt(branches):
    def m(s, i, caps, k):
        for b in branches:
            r = b(s, i, caps, k)
            if r is not None:
                return r
        return None

    return m


def _group(index, inner):
    a = 2 * (index - 1)
    b = a + 2

    def m(s, i, caps, k):
        return inner(s, i, caps, lambda j, c: k(j, c[:a] + (i, j) + c[b:]))

    return m


def _rep_single(pred, lo, hi, greedy):
    """Repeat of a one-character item (CPython's REPEAT_ONE / MIN_REPEAT_ONE)."""

    def m(s, i, caps, k):
        n = len(s)
        limit = n if hi is None else min(n, i + hi)
        if greedy:
            j = i
            while j < limit and pred(s[j]):
                j += 1
            end = i + lo
            while j >= end:
                r = k(j, caps)
                if r is not None:
                    return r
                j -= 1
            return None
        j = i
        while j < i + lo:
            if j >= n or not pred(s[j]):
                return None
            j += 1
        while True:
            r = k(j, caps)
            if r is not None:
                return r
            if j >= limit or not pred(s[j]):
                return None
            j += 1

    return m


def _rep(item, lo, hi, greedy):
    """General repeat (CPython's REPEAT with MAX_UNTIL / MIN_UNTIL).

    ``count`` is the number of completed iterations and ``last`` the position
    where the latest optional iteration started (``None`` before any). Once
    ``min`` is reached, no further iteration is attempted from a position
    equal to ``last``: an optional iteration that matched the empty string
    stops the loop.
    """

    def until(s, i, caps, count, last, k):
        if count < lo:
            return item(s, i, caps, lambda j, c: until(s, j, c, count + 1, last, k))
        can_iterate = (hi is None or count < hi) and i != last
        if greedy:
            if can_iterate:
                r = item(s, i, caps, lambda j, c: until(s, j, c, count + 1, i, k))
                if r is not None:
                    return r
            return k(i, caps)
        r = k(i, caps)
        if r is not None:
            return r
        if can_iterate:
            return item(s, i, caps, lambda j, c: until(s, j, c, count + 1, i, k))
        return None

    def m(s, i, caps, k):
        return until(s, i, caps, 0, None, k)

    return m
