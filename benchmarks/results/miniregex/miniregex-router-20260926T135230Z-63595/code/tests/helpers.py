"""Shared helpers: compare miniregex against the standard ``re`` module."""

from __future__ import annotations

import re
import warnings

import miniregex


def re_compile(pattern: str) -> re.Pattern[str] | None:
    """Compile with ``re``; return None if ``re`` rejects the pattern."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return re.compile(pattern)
        except (re.error, OverflowError, RecursionError):
            return None


def _describe(m: re.Match[str] | miniregex.Match | None, ngroups: int) -> object:
    if m is None:
        return None
    return (
        [m.span(i) for i in range(ngroups + 1)],
        [m.group(i) for i in range(ngroups + 1)],
        m.groups(),
        m.group(),
        m.start(),
        m.end(),
    )


def assert_same(pattern: str, texts: list[str] | tuple[str, ...] | str) -> None:
    """Assert that miniregex and re agree on every operation for ``texts``."""
    if isinstance(texts, str):
        texts = [texts]
    expected = re_compile(pattern)
    assert expected is not None, f"re rejects {pattern!r}"
    ours = miniregex.compile(pattern)
    assert ours.groups == expected.groups, pattern
    n = expected.groups
    for text in texts:
        for op in ("fullmatch", "match", "search"):
            want = _describe(getattr(expected, op)(text), n)
            got = _describe(getattr(ours, op)(text), n)
            assert got == want, f"{op}({pattern!r}, {text!r}): got {got!r}, want {want!r}"
        want_all = expected.findall(text)
        got_all = ours.findall(text)
        assert got_all == want_all, f"findall({pattern!r}, {text!r}): {got_all!r} != {want_all!r}"
        want_iter = [_describe(m, n) for m in expected.finditer(text)]
        got_iter = [_describe(m, n) for m in ours.finditer(text)]
        assert got_iter == want_iter, f"finditer({pattern!r}, {text!r})"


def assert_both_reject(pattern: str) -> None:
    assert re_compile(pattern) is None, f"re accepts {pattern!r}"
    try:
        miniregex.compile(pattern)
    except miniregex.RegexError:
        return
    raise AssertionError(f"miniregex accepts {pattern!r}")
