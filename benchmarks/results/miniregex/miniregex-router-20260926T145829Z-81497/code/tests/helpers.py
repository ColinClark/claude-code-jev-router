"""Shared helpers for comparing miniregex with Python's re."""

import re
import warnings

import miniregex


def describe(m):
    """Everything observable about a match (or None)."""
    if m is None:
        return None
    n = len(m.groups())
    return (
        m.group(),
        m.span(),
        m.groups(),
        [m.span(i) for i in range(n + 1)],
        [m.group(i) for i in range(n + 1)],
        [(m.start(i), m.end(i)) for i in range(n + 1)],
    )


def re_compile(pattern):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return re.compile(pattern)


def assert_same(pattern, texts):
    """Assert miniregex agrees with re on ``pattern`` for every text."""
    try:
        expected = re_compile(pattern)
    except re.error:
        expected = None
    try:
        actual = miniregex.compile(pattern)
    except miniregex.RegexError:
        actual = None
    if expected is None or actual is None:
        assert expected is None and actual is None, (
            f"compile disagreement for {pattern!r}: re={expected!r} mini={actual!r}"
        )
        return
    assert actual.groups == expected.groups, pattern
    for text in texts:
        for method in ("match", "fullmatch", "search"):
            want = describe(getattr(expected, method)(text))
            got = describe(getattr(actual, method)(text))
            assert got == want, f"{method}({pattern!r}, {text!r}): re={want} mini={got}"
        want = expected.findall(text)
        got = actual.findall(text)
        assert got == want, f"findall({pattern!r}, {text!r}): re={want} mini={got}"
