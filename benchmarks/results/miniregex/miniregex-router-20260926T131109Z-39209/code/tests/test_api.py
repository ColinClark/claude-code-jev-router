"""Tests for the public API: compile, Pattern methods and Match methods."""

from __future__ import annotations

import re

import pytest

import miniregex
from miniregex import RegexError, compile


def test_public_names() -> None:
    assert miniregex.compile is compile
    assert issubclass(RegexError, Exception)


def test_fullmatch_match_search() -> None:
    p = compile("ab+")
    assert p.fullmatch("abb").span() == (0, 3)
    assert p.fullmatch("abbc") is None
    assert p.match("abbc").span() == (0, 3)
    assert p.match("xab") is None
    assert p.search("xxabbx").span() == (2, 5)
    assert p.search("xxx") is None


def test_fullmatch_backtracks_to_reach_end() -> None:
    assert compile("a|ab").match("ab").span() == (0, 1)
    assert compile("a|ab").fullmatch("ab").span() == (0, 2)
    assert compile("a*?").fullmatch("aaa").span() == (0, 3)


def test_match_group_accessors() -> None:
    m = compile("(a)(b)?(c)").search("xac")
    assert m.group() == "ac"
    assert m.group(0) == "ac"
    assert m.group(1) == "a"
    assert m.group(2) is None
    assert m.group(1, 3) == ("a", "c")
    assert m.groups() == ("a", None, "c")
    assert m.groups("-") == ("a", "-", "c")
    assert m.span() == (1, 3)
    assert m.span(2) == (-1, -1)
    assert m.start(2) == -1 and m.end(2) == -1
    assert m.start(3) == 2 and m.end(3) == 3
    assert m[1] == "a"


@pytest.mark.parametrize("bad", [-1, 4, 100])
def test_invalid_group_index_raises_index_error(bad: int) -> None:
    m = compile("(a)(b)?(c)").search("ac")
    rm = re.search("(a)(b)?(c)", "ac")
    for meth in ("group", "span", "start", "end"):
        with pytest.raises(IndexError):
            getattr(rm, meth)(bad)
        with pytest.raises(IndexError):
            getattr(m, meth)(bad)


def test_group_with_non_int_raises_index_error() -> None:
    m = compile("(a)").match("a")
    with pytest.raises(IndexError):
        m.group("x")


def test_last_iteration_value() -> None:
    m = compile("(a|b)*").match("abba")
    assert m.group(1) == "a"
    assert m.span(1) == (3, 4)


def test_earlier_iteration_value_kept() -> None:
    m = compile(r"(?:(a)|b)*").match("ab")
    assert m.groups() == ("a",)
    assert m.span(1) == (0, 1)


@pytest.mark.parametrize(
    ("pattern", "text"),
    [
        ("a*", "baaa"),
        ("", "abc"),
        ("a|", "aba"),
        ("a*?", "aa"),
        ("(a)|(b)", "abx"),
        ("(a)", "aaa"),
        ("(a)(b)?", "aab"),
        (r"\b", "ab a"),
        ("$", "a\n"),
        ("a??", "aa"),
        ("(?:a|)*", "aab"),
        ("x*", "\n"),
    ],
)
def test_findall_matches_re(pattern: str, text: str) -> None:
    assert compile(pattern).findall(text) == re.findall(pattern, text)


def test_findall_documented_example() -> None:
    assert compile("a*").findall("baaa") == ["", "aaa", ""]


def test_findall_shapes() -> None:
    assert compile("a.").findall("abacad") == ["ab", "ac", "ad"]
    assert compile("a(.)").findall("abacad") == ["b", "c", "d"]
    assert compile("(a)(x)?").findall("aa") == [("a", ""), ("a", "")]


def test_finditer() -> None:
    spans = [m.span() for m in compile("a*").finditer("baaa")]
    assert spans == [m.span() for m in re.finditer("a*", "baaa")]


def test_pattern_attributes() -> None:
    p = compile("(a)(?:b)(c)")
    assert p.groups == 2
    assert p.pattern == "(a)(?:b)(c)"
    assert compile(p) is p


def test_text_must_be_str() -> None:
    with pytest.raises(TypeError):
        compile("a").match(b"a")  # type: ignore[arg-type]


def test_long_input_does_not_recurse() -> None:
    text = "a" * 5000
    assert compile("a*").match(text).end() == 5000
    assert compile("(a)*").match(text).span(1) == (4999, 5000)
    assert compile("(?:a|b)*?$").match(text).end() == 5000
    assert compile("(a*?)*$").match(text).groups() == re.match("(a*?)*$", text).groups()
    assert compile("(?:ab)+").search("x" + "ab" * 3000).span() == (1, 6001)


def test_regex_error_attributes() -> None:
    with pytest.raises(RegexError) as info:
        compile("a)")
    assert info.value.pos == 1
    assert info.value.pattern == "a)"
