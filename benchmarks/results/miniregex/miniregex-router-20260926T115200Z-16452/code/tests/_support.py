"""Shared helpers: compare miniregex against the standard library's re."""

from __future__ import annotations

import re

import miniregex
from miniregex import RegexError


def describe(match, ngroups: int):
    """Reduce a match object (re or miniregex) to comparable plain data."""
    if match is None:
        return None
    return (
        match.span(),
        match.groups(),
        tuple(match.span(i) for i in range(ngroups + 1)),
        tuple(match.group(i) for i in range(ngroups + 1)),
        match.lastindex,
    )


def compile_both(pattern: str):
    """Compile with re and miniregex.

    Returns ``(re_pattern, mini_pattern)`` or ``None`` when re rejects the
    pattern, in which case miniregex must reject it as well.
    """
    try:
        ref = re.compile(pattern)
    except (re.error, OverflowError):
        try:
            miniregex.compile(pattern)
        except RegexError:
            return None
        raise AssertionError(f"re rejects {pattern!r} but miniregex compiled it") from None
    mini = miniregex.compile(pattern)
    assert mini.groups == ref.groups, pattern
    assert mini.pattern == pattern
    return ref, mini


def assert_same(pattern: str, text: str) -> None:
    """Assert identical results for fullmatch/match/search/findall/finditer."""
    both = compile_both(pattern)
    if both is None:
        return
    ref, mini = both
    for method in ("fullmatch", "match", "search"):
        expected = describe(getattr(ref, method)(text), ref.groups)
        actual = describe(getattr(mini, method)(text), mini.groups)
        assert actual == expected, f"{method}({pattern!r}, {text!r}): {actual!r} != {expected!r}"
    expected_all = ref.findall(text)
    actual_all = mini.findall(text)
    assert actual_all == expected_all, f"findall({pattern!r}, {text!r})"
    expected_iter = [describe(m, ref.groups) for m in ref.finditer(text)]
    actual_iter = [describe(m, mini.groups) for m in mini.finditer(text)]
    assert actual_iter == expected_iter, f"finditer({pattern!r}, {text!r})"
