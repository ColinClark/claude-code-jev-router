"""CPython sre quirks that miniregex reproduces.

Each case pins the concrete value we expect (so a change in behaviour is
visible in the test itself) and additionally asserts that re agrees.
"""

import re
import sys

import pytest

from miniregex import compile


def details(m):
    if m is None:
        return None
    ngroups = m.re.groups if isinstance(m, re.Match) else m.pattern.groups
    return (m.span(), m.groups(), tuple(m.span(i) for i in range(1, ngroups + 1)))


@pytest.mark.parametrize(
    ("pattern", "text", "expected"),
    [
        # last iteration wins
        ("(a|b)*", "ab", ((0, 2), ("b",), ((1, 2),))),
        # non-participating alternative
        ("(a)|b", "b", ((0, 1), (None,), ((-1, -1),))),
        # captures from an earlier iteration persist when a later one skips the group
        ("(?:(a)|b)+", "ab", ((0, 2), ("a",), ((0, 1),))),
        ("(?:(a)|(b))+", "ab", ((0, 2), ("a", "b"), ((0, 1), (1, 2)))),
        ("(?:(b)|(a))+", "ab", ((0, 2), ("b", "a"), ((1, 2), (0, 1)))),
        # captures restored on backtracking
        ("(a)*ab", "aab", ((0, 3), ("a",), ((0, 1),))),
        ("(a)+?a", "aa", ((0, 2), ("a",), ((0, 1),))),
        ("(a|ab)(c|bcd)(d*)", "abcd", ((0, 4), ("a", "bcd", ""), ((0, 1), (1, 4), (4, 4)))),
        # empty iterations inside unbounded repeats
        ("(a*)*", "b", ((0, 0), ("",), ((0, 0),))),
        ("(a*)+", "aab", ((0, 2), ("",), ((2, 2),))),
        ("(a|)*", "aab", ((0, 2), ("",), ((2, 2),))),
        ("(a*)*?b", "aab", ((0, 3), ("aa",), ((0, 2),))),
        ("(a*?)*", "aa", ((0, 0), ("",), ((0, 0),))),
        ("(a*?)+", "aa", ((0, 0), ("",), ((0, 0),))),
        ("(a?)*?b", "aab", ((0, 3), ("a",), ((1, 2),))),
        ("(a?)*b", "aab", ((0, 3), ("",), ((2, 2),))),
        ("(a*){2,}", "b", ((0, 0), ("",), ((0, 0),))),
        ("(a|b?){2,}", "ab", ((0, 2), ("",), ((2, 2),))),
        ("(a|b?)*?$", "ab", ((0, 2), ("b",), ((1, 2),))),
        ("()*", "a", ((0, 0), ("",), ((0, 0),))),
        ("(?:)*", "a", ((0, 0), (), ())),
        ("(?:a*?)*", "aa", ((0, 0), (), ())),
        ("(?:a*)*", "aa", ((0, 2), (), ())),
        ("((a*)*)*b", "aab", ((0, 3), ("", ""), ((2, 2), (2, 2)))),
        ("(a*)*$", "aa", ((0, 2), ("",), ((2, 2),))),
        ("(a*)+$", "aa", ((0, 2), ("",), ((2, 2),))),
        ("(a*)?$", "aa", ((0, 2), ("aa",), ((0, 2),))),
        ("(a*){1,2}$", "aa", ((0, 2), ("",), ((2, 2),))),
        ("(a*){2}", "aa", ((0, 2), ("",), ((2, 2),))),
        ("(a|b*)*", "ab", ((0, 2), ("",), ((2, 2),))),
        # zero-width group inside a group inside a repeat
        ("((a)|())*", "a", ((0, 1), ("", "a", ""), ((1, 1), (0, 1), (1, 1)))),
        ("(()|(a))*", "a", ((0, 0), ("", "", None), ((0, 0), (0, 0), (-1, -1)))),
        # {0} never runs the body
        ("(a){0}b", "b", ((0, 1), (None,), ((-1, -1),))),
    ],
)
def test_capture_and_empty_iteration_quirks(pattern, text, expected):
    assert details(re.match(pattern, text)) == expected, "expectation disagrees with re"
    assert details(compile(pattern).match(text)) == expected


@pytest.mark.parametrize(
    ("pattern", "text", "expected"),
    [
        ("a*", "baaa", ["", "aaa", ""]),
        ("a*?", "aa", ["", "a", "", "a", ""]),
        ("^", "abc", [""]),
        ("^a*", "aab", ["aa"]),
        ("$", "a\n", ["", ""]),
        ("", "ab", ["", "", ""]),
        ("a|", "ab", ["a", "", ""]),
        ("(a)|(b)", "ab", [("a", ""), ("", "b")]),
        ("(a*)", "baa", ["", "aa", ""]),
        ("a??", "aa", ["", "a", "", "a", ""]),
        ("(?:a|b)*?", "ab", ["", "a", "", "b", ""]),
        ("x*", "", [""]),
        ("(a)(b)?", "aab", [("a", ""), ("a", "b")]),
    ],
)
def test_findall_empty_match_semantics(pattern, text, expected):
    assert re.findall(pattern, text) == expected, "expectation disagrees with re"
    assert compile(pattern).findall(text) == expected


def test_search_scans_all_start_positions():
    assert compile("b").search("aab").span() == (2, 2 + 1)
    assert compile("$").search("aa").span() == (2, 2)
    assert compile("a*").search("baa").span() == (0, 0)
    assert compile("a+").search("baa").span() == (1, 3)
    assert compile("^b").search("ab") is None


def test_fullmatch_backtracks_to_consume_everything():
    assert compile("a*?").fullmatch("aaa").span() == (0, 3)
    assert compile("(a|ab)").fullmatch("ab").group(1) == "ab"
    assert compile("(a+?)").fullmatch("aaa").group(1) == "aaa"
    assert compile("a*").fullmatch("aab") is None


def test_dot_excludes_newline_only():
    assert compile(".").match("\n") is None
    assert compile(".").match("\r") is not None
    assert compile("(?:.|\n)*").fullmatch("a\nb\n") is not None


def test_no_recursion_depth_dependence_on_text_length():
    """Matching must not recurse proportionally to the text length."""
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(120)
    try:
        long_a = "a" * 5000
        assert compile("a*").match(long_a).span() == (0, 5000)
        assert compile("a*?b").match(long_a + "b").span() == (0, 5001)
        assert compile("(?:ab)*").match("ab" * 3000).span() == (0, 6000)
        assert compile("(a|b)*c").search("ab" * 2000 + "c").group(1) == "b"
        assert compile("(?:a|b)*$").fullmatch("ab" * 2500) is not None
        assert compile(".*x").search("a" * 4000) is None
        assert compile("[ab]{1000,}").match("ab" * 1000).span() == (0, 2000)
        assert compile("a*").findall("a" * 3000 + "b" * 3000) == ["a" * 3000] + [""] * 3001
    finally:
        sys.setrecursionlimit(old)
