"""Edge cases: empty iterations, capture values under repetition, anchors,
lazy quantifiers, brace literals and deep inputs.

Expected values are hard-coded (taken from CPython's re, verified on 3.12 and
3.14) so the tests document the behaviour, and every case is additionally
compared against re directly.
"""

from __future__ import annotations

import sys

import pytest
from _support import assert_same

from miniregex import compile


def result(pattern: str, text: str, method: str = "fullmatch"):
    m = getattr(compile(pattern), method)(text)
    if m is None:
        return None
    return m.span(), m.groups(), tuple(m.span(i) for i in range(compile(pattern).groups + 1))


# (pattern, text, expected (span, groups, all spans) for fullmatch)
CAPTURE_IN_REPEAT_CASES = [
    # a group that matched in an earlier iteration keeps its value
    (r"(?:(a)|b)+", "ab", ((0, 2), ("a",), ((0, 2), (0, 1)))),
    (r"(?:(a)|b)+", "ba", ((0, 2), ("a",), ((0, 2), (1, 2)))),
    (r"(a|(b))+", "ba", ((0, 2), ("a", "b"), ((0, 2), (1, 2), (0, 1)))),
    (r"(a|(b))+", "ab", ((0, 2), ("b", "b"), ((0, 2), (1, 2), (1, 2)))),
    (r"((a)|b)*", "ab", ((0, 2), ("b", "a"), ((0, 2), (1, 2), (0, 1)))),
    (r"((a)|b)*", "ba", ((0, 2), ("a", "a"), ((0, 2), (1, 2), (1, 2)))),
    (r"(a|b(c))*", "bca", ((0, 3), ("a", "c"), ((0, 3), (2, 3), (1, 2)))),
    (r"(?:(a)|(b))*", "ab", ((0, 2), ("a", "b"), ((0, 2), (0, 1), (1, 2)))),
    (r"(?:(a)b|a(b))*", "abab", ((0, 4), ("a", None), ((0, 4), (2, 3), (-1, -1)))),
    (r"((a)|(b))+", "ab", ((0, 2), ("b", "a", "b"), ((0, 2), (1, 2), (0, 1), (1, 2)))),
    (r"((a)|(b))+", "ba", ((0, 2), ("a", "a", "b"), ((0, 2), (1, 2), (1, 2), (0, 1)))),
    (r"((a)?)+", "a", ((0, 1), ("", "a"), ((0, 1), (1, 1), (0, 1)))),
    (r"((a)?)+", "aa", ((0, 2), ("", "a"), ((0, 2), (2, 2), (1, 2)))),
    (r"(?:(a)|b){2}", "ba", ((0, 2), ("a",), ((0, 2), (1, 2)))),
    (r"(?:(a)|b){2}", "ab", ((0, 2), ("a",), ((0, 2), (0, 1)))),
    (r"(?:(a)|b){2}?", "ba", ((0, 2), ("a",), ((0, 2), (1, 2)))),
    (r"(?:(a)|b)*?$", "ab", ((0, 2), ("a",), ((0, 2), (0, 1)))),
    (r"(?:(a)|b)+?c", "bac", ((0, 3), ("a",), ((0, 3), (1, 2)))),
    (r"(?:(a)|(b))+?c", "bac", ((0, 3), ("a", "b"), ((0, 3), (1, 2), (0, 1)))),
    # a group set inside a failed alternative is not reported
    (r"(?:(a)|ab)(c)", "abc", ((0, 3), (None, "c"), ((0, 3), (-1, -1), (2, 3)))),
    (r"(?:a*(a)b|a*(b))", "aab", ((0, 3), ("a", None), ((0, 3), (1, 2), (-1, -1)))),
    (r"(a)|b", "b", ((0, 1), (None,), ((0, 1), (-1, -1)))),
    (r"(a){0}", "", ((0, 0), (None,), ((0, 0), (-1, -1)))),
    (r"(a){0,0}", "", ((0, 0), (None,), ((0, 0), (-1, -1)))),
    (r"(a?)??", "", ((0, 0), (None,), ((0, 0), (-1, -1)))),
    (r"(a?)?", "", ((0, 0), ("",), ((0, 0), (0, 0)))),
]

EMPTY_ITERATION_CASES = [
    (r"(a*)*", "aa", ((0, 2), ("",), ((0, 2), (2, 2)))),
    (r"(a*)*", "", ((0, 0), ("",), ((0, 0), (0, 0)))),
    (r"(a*)+", "", ((0, 0), ("",), ((0, 0), (0, 0)))),
    (r"(a*)+b", "aab", ((0, 3), ("",), ((0, 3), (2, 2)))),
    (r"(a*)*b", "aab", ((0, 3), ("",), ((0, 3), (2, 2)))),
    (r"(a*?)*", "aa", ((0, 2), ("",), ((0, 2), (2, 2)))),
    (r"(a*?)*?", "aa", ((0, 2), ("a",), ((0, 2), (1, 2)))),
    (r"(a?)*?", "aa", ((0, 2), ("a",), ((0, 2), (1, 2)))),
    (r"(a?)+?", "a", ((0, 1), ("a",), ((0, 1), (0, 1)))),
    (r"(a?)+?", "", ((0, 0), ("",), ((0, 0), (0, 0)))),
    (r"(a?)+?b", "ab", ((0, 2), ("a",), ((0, 2), (0, 1)))),
    (r"(a?)+?$", "aa", ((0, 2), ("a",), ((0, 2), (1, 2)))),
    (r"(a*)+?$", "aa", ((0, 2), ("aa",), ((0, 2), (0, 2)))),
    (r"(a*)*?$", "aa", ((0, 2), ("aa",), ((0, 2), (0, 2)))),
    (r"(a?){2,}?", "aa", ((0, 2), ("a",), ((0, 2), (1, 2)))),
    (r"(|a)+", "a", ((0, 1), ("",), ((0, 1), (1, 1)))),
    (r"(|a)*", "a", ((0, 1), ("",), ((0, 1), (1, 1)))),
    (r"(a|)+", "a", ((0, 1), ("",), ((0, 1), (1, 1)))),
    (r"((|a)*)*", "a", ((0, 1), ("", ""), ((0, 1), (1, 1), (1, 1)))),
    (r"((a*)*)*", "aa", ((0, 2), ("", ""), ((0, 2), (2, 2), (2, 2)))),
    (r"((a*)+)+", "aa", ((0, 2), ("", ""), ((0, 2), (2, 2), (2, 2)))),
    (r"(a?)*b", "ab", ((0, 2), ("",), ((0, 2), (1, 1)))),
    (r"(a??)*b", "ab", ((0, 2), ("",), ((0, 2), (1, 1)))),
    (r"(a?)*?b", "b", ((0, 1), (None,), ((0, 1), (-1, -1)))),
    (r"(a?)+?b", "b", ((0, 1), ("",), ((0, 1), (0, 0)))),
    (r"(a*)*?b", "b", ((0, 1), (None,), ((0, 1), (-1, -1)))),
    (r"(a*)*?b", "ab", ((0, 2), ("a",), ((0, 2), (0, 1)))),
    (r"(a*)+?b", "aab", ((0, 3), ("aa",), ((0, 3), (0, 2)))),
    (r"(a*?)+?b", "aab", ((0, 3), ("a",), ((0, 3), (1, 2)))),
    (r"(a*){2}", "aa", ((0, 2), ("",), ((0, 2), (2, 2)))),
    (r"(a*){2,3}", "aa", ((0, 2), ("",), ((0, 2), (2, 2)))),
    (r"(a*){2,3}?", "aa", ((0, 2), ("",), ((0, 2), (2, 2)))),
    (r"(a*){1,}?a", "aa", ((0, 2), ("a",), ((0, 2), (0, 1)))),
    (r"(a+)+?b", "aab", ((0, 3), ("aa",), ((0, 3), (0, 2)))),
    (r"(a+?)+b", "aab", ((0, 3), ("a",), ((0, 3), (1, 2)))),
    (r"(?:)*", "x", None),
    (r"(?:)*", "", ((0, 0), (), ((0, 0),))),
    (r"(?:)+", "", ((0, 0), (), ((0, 0),))),
    (r"(?:a*)*", "aa", ((0, 2), (), ((0, 2),))),
    (r"(?:a|)*", "a", ((0, 1), (), ((0, 1),))),
    (r"(?:^)*", "", ((0, 0), (), ((0, 0),))),
    (r"(?:a?)+?b", "b", ((0, 1), (), ((0, 1),))),
    (r"(?:a?)*?b", "b", ((0, 1), (), ((0, 1),))),
    (r"()*", "", ((0, 0), ("",), ((0, 0), (0, 0)))),
    (r"()+", "", ((0, 0), ("",), ((0, 0), (0, 0)))),
    (r"()*?", "", ((0, 0), (None,), ((0, 0), (-1, -1)))),
    (r"()+?", "", ((0, 0), ("",), ((0, 0), (0, 0)))),
    (r"(){2,}a", "a", ((0, 1), ("",), ((0, 1), (0, 0)))),
]


@pytest.mark.parametrize(
    ("pattern", "text", "expected"), CAPTURE_IN_REPEAT_CASES + EMPTY_ITERATION_CASES
)
def test_fullmatch_expected_values(pattern: str, text: str, expected) -> None:
    assert result(pattern, text) == expected
    assert_same(pattern, text)


@pytest.mark.parametrize(
    "pattern",
    [p for p, _, _ in CAPTURE_IN_REPEAT_CASES + EMPTY_ITERATION_CASES],
)
def test_capture_and_empty_loop_patterns_match_re_on_many_texts(pattern: str) -> None:
    for text in [
        "",
        "a",
        "b",
        "c",
        "aa",
        "ab",
        "ba",
        "bb",
        "aab",
        "abb",
        "bab",
        "abc",
        "bac",
        "aaab",
        "abab",
        "baab",
        "cab",
    ]:
        assert_same(pattern, text)


@pytest.mark.parametrize(
    ("pattern", "text", "expected_span"),
    [
        ("x$", "x", (0, 1)),
        ("x$", "x\n", None),  # fullmatch must consume the newline too
        ("x$", "x\n\n", None),
        ("$", "", (0, 0)),
        ("$", "\n", None),
        ("^x", "\nx", None),
        ("^", "", (0, 0)),
        ("^$", "\n", None),
        ("a$\n", "a\n", (0, 2)),
        ("a$\n$", "a\n", (0, 2)),
        ("$$", "", (0, 0)),
    ],
)
def test_anchors_fullmatch(pattern: str, text: str, expected_span) -> None:
    m = compile(pattern).fullmatch(text)
    assert (m.span() if m else None) == expected_span
    assert_same(pattern, text)


@pytest.mark.parametrize(
    ("pattern", "text", "expected_span"),
    [
        ("x$", "x\n", (0, 1)),  # $ matches before a final newline
        ("x$", "x\n\n", None),
        ("$", "a\n", (1, 1)),
        ("$", "a\n\n", (2, 2)),
        ("^", "\na", (0, 0)),
        ("^a", "\na", None),  # ^ only matches at position 0
        ("a$", "ba\nb", None),
        ("a.", "a\n", None),  # . excludes newline
        ("a[^x]", "a\n", (0, 2)),
        ("a\\s", "a\n", (0, 2)),
    ],
)
def test_anchors_and_dot_search(pattern: str, text: str, expected_span) -> None:
    m = compile(pattern).search(text)
    assert (m.span() if m else None) == expected_span
    assert_same(pattern, text)


@pytest.mark.parametrize(
    ("pattern", "text", "expected"),
    [
        ("a*?", "aaa", ((0, 0), (0, 3))),
        ("a+?", "aaa", ((0, 1), (0, 3))),
        ("a??", "a", ((0, 0), (0, 1))),
        ("a{2,3}?", "aaaa", ((0, 2), None)),
        ("a{,2}?", "aa", ((0, 0), (0, 2))),
        ("a{2}?", "aa", ((0, 2), (0, 2))),
        ("a{1,}?", "aaa", ((0, 1), (0, 3))),
        ("(a|ab)(c|bcd)(d*)", "abcd", ((0, 4), (0, 4))),
        ("(ab)*?ab", "abab", ((0, 2), (0, 4))),
        ("(a+?)(a*)", "aaa", ((0, 3), (0, 3))),
        (".*?b", "aabab", ((0, 3), (0, 5))),
        ("[ab]*?b", "aabab", ((0, 3), (0, 5))),
        (".*?b", "aababa", ((0, 3), None)),
        ("a|ab", "ab", ((0, 1), (0, 2))),
        ("ab|a", "ab", ((0, 2), (0, 2))),
    ],
)
def test_lazy_and_priority(pattern: str, text: str, expected) -> None:
    match_span, full_span = expected
    m = compile(pattern).match(text)
    f = compile(pattern).fullmatch(text)
    assert (m.span() if m else None) == match_span
    assert (f.span() if f else None) == full_span
    assert_same(pattern, text)


def test_lazy_groups_match_re() -> None:
    for pattern in [
        "(a+?)(a*?)",
        "(a*?)(a+)",
        "(a??)(a?)",
        "(.*?)(.*)",
        "((a)*?)(a)",
        "(a|ab)??(b?)",
    ]:
        for text in ["", "a", "aa", "aaa", "ab", "aab"]:
            assert_same(pattern, text)


@pytest.mark.parametrize(
    ("pattern", "text"),
    [
        ("a{", "a{"),
        ("a{x}", "a{x}"),
        ("a{1,x}", "a{1,x}"),
        ("a{,x}", "a{,x}"),
        ("a{}", "a{}"),
        ("a{1", "a{1"),
        ("a{1,", "a{1,"),
        ("a{,", "a{,"),
        ("a{1,2", "a{1,2"),
        ("{", "{"),
        ("a{1}{", "a{"),
        ("a{ 1}", "a{ 1}"),
        ("a{1 }", "a{1 }"),
    ],
)
def test_brace_literals(pattern: str, text: str) -> None:
    assert compile(pattern).fullmatch(text) is not None
    assert_same(pattern, text)


def test_brace_quantifier_forms() -> None:
    assert compile("a{,}").fullmatch("aaa").span() == (0, 3)
    assert compile("a{,}").fullmatch("").span() == (0, 0)
    assert compile("a{2,}").fullmatch("a") is None
    assert compile("a{2,}").fullmatch("aaaa").span() == (0, 4)
    assert compile("a{,2}").fullmatch("aaa") is None
    assert compile("a{2}").fullmatch("aa").span() == (0, 2)
    assert compile("a{2}").fullmatch("aaa") is None
    assert compile("a{0}").fullmatch("") is not None
    assert compile("a{0}").fullmatch("a") is None
    assert compile("ba{0}").fullmatch("b") is not None


def test_sets_edge_cases() -> None:
    assert compile("[]a]").fullmatch("]") is not None
    assert compile("[]a]").fullmatch("a") is not None
    assert compile("[^]a]").fullmatch("b") is not None
    assert compile("[^]a]").fullmatch("]") is None
    assert compile("[a-]").fullmatch("-") is not None
    assert compile("[-a]").fullmatch("-") is not None
    assert compile("[--a]").fullmatch("-") is not None
    assert compile("[--a]").fullmatch("a") is not None
    assert compile("[--a]").fullmatch("Z") is not None  # '-' .. 'a' includes 'Z'
    assert compile("[a\\-z]").fullmatch("-") is not None
    assert compile("[a\\-z]").fullmatch("b") is None
    assert compile("[\\]]").fullmatch("]") is not None
    assert compile("[\\d-]").fullmatch("-") is not None
    assert compile("[a-b\\d]").fullmatch("5") is not None


def test_escapes_are_ascii() -> None:
    assert compile(r"\d").fullmatch("5") is not None
    assert compile(r"\d").fullmatch("a") is None
    assert compile(r"\w").fullmatch("_") is not None
    assert compile(r"\w").fullmatch("-") is None
    assert compile(r"\s+").fullmatch(" \t\n\r\f\v") is not None
    assert compile(r"\S").fullmatch(" ") is None
    assert compile(r"\D").fullmatch("5") is None
    assert compile(r"\W").fullmatch("_") is None
    assert compile(r"\\").fullmatch("\\") is not None
    assert compile(r"\-").fullmatch("-") is not None
    assert compile(r"[\b]").fullmatch("\b") is not None


def test_alternation_empty_branches() -> None:
    assert compile("a|").fullmatch("") is not None
    assert compile("a|").fullmatch("a") is not None
    assert compile("a|").fullmatch("b") is None
    assert compile("|").fullmatch("") is not None
    assert compile("(|a)").fullmatch("a").groups() == ("a",)
    assert compile("(|a)").match("a").groups() == ("",)
    assert compile("(a|)").match("a").groups() == ("a",)
    assert compile("(|a)(a?)").fullmatch("a").groups() == ("", "a")


def test_deep_input_no_recursion_error() -> None:
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(100)
    try:
        assert compile("a*").fullmatch("a" * 5000).span() == (0, 5000)
        assert compile("a*?").fullmatch("a" * 5000).span() == (0, 5000)
        assert compile("(ab)*").fullmatch("ab" * 2500).groups() == ("ab",)
        assert compile("(ab)*?$").match("ab" * 2500).span() == (0, 5000)
        assert compile("(a|b)*").fullmatch("ab" * 2500).span(1) == (4999, 5000)
        assert compile("(?:ab|ba)+").fullmatch("ab" * 2500) is not None
        assert compile("(a*)*b").fullmatch("a" * 3000 + "b").groups() == ("",)
        assert len(compile("(ab)").findall("ab" * 2500)) == 2500
        assert len(compile("(a)|(b)").findall("ab" * 2500)) == 5000
        assert compile("x").search("a" * 5000) is None
        assert compile("(a)(?:b|c)*d").search("a" + "bc" * 2000) is None
    finally:
        sys.setrecursionlimit(old)


def test_findall_with_groups_inside_repeats_matches_re() -> None:
    for pattern in [
        "(?:(a)|b)+",
        "(a|(b))+",
        "(a*)*",
        "(a?)+?",
        "(|a)+",
        "()",
        "(a)|(b)|",
        "(?:)*",
    ]:
        for text in ["", "ab", "ba", "aab", "bb", "abab"]:
            assert_same(pattern, text)
