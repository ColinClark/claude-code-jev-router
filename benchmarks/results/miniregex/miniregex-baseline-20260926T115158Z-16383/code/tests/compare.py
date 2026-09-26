"""Differential-testing helpers: compare miniregex against the standard ``re`` module."""

from __future__ import annotations

import re

import miniregex


def describe(m) -> tuple | None:
    """Everything observable about a match: overall span plus every group's value and span."""
    if m is None:
        return None
    n = len(m.groups())
    return (
        m.span(),
        m.group(),
        m.groups(),
        tuple(m.span(i) for i in range(1, n + 1)),
        tuple(m.start(i) for i in range(n + 1)),
        tuple(m.end(i) for i in range(n + 1)),
    )


def assert_same(pattern: str, text: str) -> None:
    expected = re.compile(pattern)
    actual = miniregex.compile(pattern)
    assert actual.groups == expected.groups, pattern
    for method in ("fullmatch", "match", "search"):
        want = describe(getattr(expected, method)(text))
        got = describe(getattr(actual, method)(text))
        assert got == want, f"{method}({pattern!r}, {text!r}): got {got}, want {want}"
    want_all = expected.findall(text)
    got_all = actual.findall(text)
    assert got_all == want_all, f"findall({pattern!r}, {text!r}): got {got_all}, want {want_all}"
