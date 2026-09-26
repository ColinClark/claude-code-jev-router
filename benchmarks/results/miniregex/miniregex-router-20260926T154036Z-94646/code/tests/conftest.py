import re
import warnings

import pytest

import miniregex


def outcome(m):
    """Comparable summary of a match object (from re or miniregex)."""
    if m is None:
        return None
    n = len(m.groups())
    return (m.span(), m.group(), m.groups(), [m.span(i) for i in range(n + 1)])


def compile_both(pattern):
    """Compile with re and miniregex; return (re_pattern, mini_pattern) or (None, None).

    Asserts that both accept or both reject the pattern.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            rp = re.compile(pattern)
        except re.error:
            rp = None
    try:
        mp = miniregex.compile(pattern)
    except miniregex.RegexError:
        mp = None
    assert (rp is None) == (mp is None), f"compile disagreement for {pattern!r}: re={rp}"
    return rp, mp


def assert_same(pattern, texts):
    rp, mp = compile_both(pattern)
    if rp is None:
        return
    assert mp.groups == rp.groups, pattern
    for text in texts:
        for meth in ("fullmatch", "match", "search"):
            want = outcome(getattr(rp, meth)(text))
            got = outcome(getattr(mp, meth)(text))
            assert got == want, f"{meth}({pattern!r}, {text!r}): got {got}, want {want}"
        assert mp.findall(text) == rp.findall(text), f"findall({pattern!r}, {text!r})"


@pytest.fixture
def same():
    return assert_same
