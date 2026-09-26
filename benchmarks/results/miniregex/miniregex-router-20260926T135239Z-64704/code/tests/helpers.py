"""Helpers for comparing miniregex results with re."""

from __future__ import annotations

import re

import miniregex


def describe(m):
    """A comparable summary of a match: overall span, group values and group spans."""
    if m is None:
        return None
    ngroups = len(m.groups())
    return (
        m.span(),
        m.group(),
        m.groups(),
        tuple(m.span(i) for i in range(1, ngroups + 1)),
        tuple((m.start(i), m.end(i)) for i in range(ngroups + 1)),
    )


def assert_same(pattern: str, text: str) -> None:
    expected = re.compile(pattern)
    actual = miniregex.compile(pattern)
    assert actual.groups == expected.groups
    for method in ("fullmatch", "match", "search"):
        exp = describe(getattr(expected, method)(text))
        got = describe(getattr(actual, method)(text))
        assert got == exp, f"{method}({pattern!r}, {text!r}): {got} != {exp}"
    assert actual.findall(text) == expected.findall(text), f"findall({pattern!r}, {text!r})"
