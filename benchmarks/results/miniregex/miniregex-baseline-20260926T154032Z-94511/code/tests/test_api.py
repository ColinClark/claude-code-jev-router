"""Public API behavior."""

from __future__ import annotations

import pathlib

import pytest

import miniregex
from miniregex import RegexError, compile


def test_compile_returns_pattern():
    p = compile(r"(a)(b)?")
    assert isinstance(p, miniregex.Pattern)
    assert p.pattern == r"(a)(b)?"
    assert p.groups == 2


def test_match_methods():
    p = compile(r"b+")
    assert p.match("abb") is None
    assert p.fullmatch("abb") is None
    m = p.search("abbc")
    assert m.group() == "bb"
    assert m.span() == (1, 3)
    assert (m.start(), m.end()) == (1, 3)
    assert compile("a+").match("aab").group() == "aa"
    assert compile("a+").fullmatch("aa").span() == (0, 2)


def test_fullmatch_backtracks_to_reach_end():
    m = compile(r"(a|ab)(c|bcd)?").fullmatch("abcd")
    assert m.groups() == ("a", "bcd")


def test_groups_and_spans():
    m = compile(r"(a)(x)?(b)").search("zab")
    assert m.group(0) == "ab"
    assert m.group(1) == "a"
    assert m.group(2) is None
    assert m.group(1, 3) == ("a", "b")
    assert m.groups() == ("a", None, "b")
    assert m.groups("") == ("a", "", "b")
    assert m.span(2) == (-1, -1)
    assert m.start(2) == -1 and m.end(2) == -1
    assert m.span(3) == (2, 3)
    assert m[1] == "a"


def test_last_iteration_value_is_kept():
    m = compile(r"(?:(a)|(b))+").fullmatch("abb")
    assert m.groups() == ("a", "b")
    assert m.span(1) == (0, 1)
    assert m.span(2) == (2, 3)


@pytest.mark.parametrize("bad", [-1, 3, "1", 1.0, None])
def test_bad_group_index(bad):
    m = compile(r"(a)(b)").match("ab")
    with pytest.raises(IndexError):
        m.group(bad)
    with pytest.raises(IndexError):
        m.span(bad)


def test_findall_shapes():
    assert compile(r"\d").findall("a1b22") == ["1", "2", "2"]
    assert compile(r"(\d)x?").findall("1x2") == ["1", "2"]
    assert compile(r"(\d)(x)?").findall("1x2") == [("1", "x"), ("2", "")]
    assert compile(r"a*").findall("baa") == ["", "aa", ""]
    assert compile(r"a*?").findall("aa") == ["", "a", "", "a", ""]
    assert compile(r"(a)|b").findall("ab") == ["a", ""]
    assert compile(r"z").findall("abc") == []


def test_finditer():
    assert [m.span() for m in compile(r"\w+").finditer("ab cd")] == [(0, 2), (3, 5)]


def test_dollar_before_final_newline():
    assert compile("a$").search("a\n").span() == (0, 1)
    assert compile("a$").search("a\n\n") is None
    assert compile("^b").search("a\nb") is None
    assert compile(".").findall("a\nb") == ["a", "b"]


def test_regex_error_is_value_error():
    assert issubclass(RegexError, ValueError)
    with pytest.raises(RegexError):
        compile("(")


def test_implementation_does_not_use_re():
    src = pathlib.Path(miniregex.__file__).parent
    for path in src.glob("*.py"):
        text = path.read_text()
        assert "import re\n" not in text and "from re " not in text, path
        assert "import regex" not in text, path
