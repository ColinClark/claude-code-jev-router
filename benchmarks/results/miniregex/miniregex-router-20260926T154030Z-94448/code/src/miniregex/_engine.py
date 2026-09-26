"""Backtracking matcher.

Every AST node is compiled into a function ``m(st, i, k)`` that tries to match
the node at position ``i`` of ``st.text`` and then calls the continuation
``k(j)`` with the end position. It returns True as soon as a continuation
succeeds, and False after exhausting all alternatives. Capture marks are
restored when a path fails, so on success ``st.marks`` describes the winning
path. Alternatives are tried in the same order as CPython's ``sre`` engine,
including its handling of empty iterations in repeats, so the first match
found is the one ``re`` reports.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager


class State:
    __slots__ = ("end", "marks", "text")

    def __init__(self, text: str, ngroups: int):
        self.text = text
        self.end = len(text)
        self.marks: list[int | None] = [None] * (2 * ngroups)


def compile_node(node):
    kind = node[0]
    if kind == "lit":
        return _literal(node[1])
    if kind == "set":
        return _charset(node[1])
    if kind == "seq":
        return _sequence([compile_node(n) for n in node[1]])
    if kind == "alt":
        return _alternation([compile_node(n) for n in node[1]])
    if kind == "group":
        body = compile_node(node[2])
        if node[1] is None:
            return body
        return _group(node[1], body)
    if kind == "rep":
        _, lo, hi, lazy, item = node
        if item[0] == "set" or (item[0] == "lit" and len(item[1]) == 1):
            return _single_repeat(item, lo, hi, lazy)
        return _repeat(compile_node(item), lo, hi, lazy)
    if kind == "at":
        return _anchor(node[1])
    raise AssertionError(f"unknown node {kind!r}")


def _literal(s: str):
    n = len(s)
    if n == 1:

        def m(st, i, k):
            return i < st.end and st.text[i] == s and k(i + 1)

    else:

        def m(st, i, k):
            return st.text.startswith(s, i) and k(i + n)

    return m


def _charset(cs):
    def m(st, i, k):
        return i < st.end and st.text[i] in cs and k(i + 1)

    return m


def _sequence(parts):
    if not parts:
        return lambda st, i, k: k(i)
    if len(parts) == 1:
        return parts[0]
    first = parts[0]
    rest = _sequence(parts[1:])

    def m(st, i, k):
        return first(st, i, lambda j: rest(st, j, k))

    return m


def _alternation(branches):
    def m(st, i, k):
        for branch in branches:
            if branch(st, i, k):
                return True
        return False

    return m


def _group(index: int, body):
    a = 2 * (index - 1)
    b = a + 1

    def m(st, i, k):
        marks = st.marks

        def close(j):
            old_a, old_b = marks[a], marks[b]
            marks[a] = i
            marks[b] = j
            if k(j):
                return True
            marks[a] = old_a
            marks[b] = old_b
            return False

        return body(st, i, close)

    return m


def _single_repeat(item, lo: int, hi: int | None, lazy: bool):
    """Repeat of a one-character item; iterative, like sre's REPEAT_ONE."""
    if item[0] == "lit":
        ch = item[1]

        def ok(c):
            return c == ch

    else:
        cs = item[1]

        def ok(c):
            return c in cs

    if lazy:

        def m(st, i, k):
            text, end = st.text, st.end
            j = i
            limit = end if hi is None else min(end, i + hi)
            if i + lo > end:
                return False
            while j < i + lo:
                if not ok(text[j]):
                    return False
                j += 1
            while True:
                if k(j):
                    return True
                if j >= limit or not ok(text[j]):
                    return False
                j += 1

    else:

        def m(st, i, k):
            text = st.text
            limit = st.end if hi is None else min(st.end, i + hi)
            j = i
            while j < limit and ok(text[j]):
                j += 1
            stop = i + lo
            while j >= stop:
                if k(j):
                    return True
                j -= 1
            return False

    return m


def _repeat(body, lo: int, hi: int | None, lazy: bool):
    """General repeat, mirroring sre's REPEAT with MAX_UNTIL / MIN_UNTIL.

    ``count`` is the number of completed iterations. ``last`` is the position
    where the most recent optional iteration started; an optional iteration
    is not attempted again at that same position, which stops endless empty
    iterations exactly the way sre does.
    """
    if lazy:

        def m(st, i, k):
            def until(count, last, p):
                if count < lo:
                    return body(st, p, lambda q: until(count + 1, last, q))
                if k(p):
                    return True
                if (hi is not None and count >= hi) or p == last:
                    return False
                return body(st, p, lambda q: until(count + 1, p, q))

            return until(0, -1, i)

    else:

        def m(st, i, k):
            def until(count, last, p):
                if count < lo:
                    return body(st, p, lambda q: until(count + 1, last, q))
                if (hi is None or count < hi) and p != last and body(st, p, lambda q: until(count + 1, p, q)):
                    return True
                return k(p)

            return until(0, -1, i)

    return m


def _anchor(kind: str):
    if kind == "bol" or kind == "bos":
        return lambda st, i, k: i == 0 and k(i)
    if kind == "eos":
        return lambda st, i, k: i == st.end and k(i)
    if kind == "eol":

        def m(st, i, k):
            end = st.end
            return (i == end or (i == end - 1 and st.text[i] == "\n")) and k(i)

        return m
    raise AssertionError(f"unknown anchor {kind!r}")


@contextmanager
def deep_recursion(text_len: int):
    """The matcher recurses roughly once per consumed character; make room."""
    needed = 2000 + 50 * text_len
    old = sys.getrecursionlimit()
    if needed > old:
        sys.setrecursionlimit(needed)
    try:
        yield
    finally:
        if needed > old:
            sys.setrecursionlimit(old)
