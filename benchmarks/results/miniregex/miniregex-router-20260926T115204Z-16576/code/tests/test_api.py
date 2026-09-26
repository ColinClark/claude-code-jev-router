"""Public API behaviour: compile, Pattern, Match."""

import pytest

import miniregex
from miniregex import Match, Pattern, RegexError, compile


def test_exports():
    assert miniregex.__all__ == ["Match", "Pattern", "RegexError", "compile"]
    assert issubclass(RegexError, Exception)


def test_compile_returns_pattern():
    p = compile(r"(a)(b)?")
    assert isinstance(p, Pattern)
    assert p.pattern == r"(a)(b)?"
    assert p.groups == 2
    assert "(a)(b)?" in repr(p)


def test_compile_type_error():
    with pytest.raises(TypeError):
        compile(b"abc")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        compile("a").match(b"a")  # type: ignore[arg-type]


def test_match_is_anchored_search_is_not():
    p = compile("b")
    assert p.match("ab") is None
    m = p.search("ab")
    assert isinstance(m, Match)
    assert m.span() == (1, 2)


def test_fullmatch_requires_whole_text():
    p = compile("a*")
    assert p.fullmatch("aaa").span() == (0, 3)
    assert p.fullmatch("aab") is None
    # fullmatch backtracks into lazy quantifiers to consume everything
    assert compile("a*?").fullmatch("aaa").span() == (0, 3)
    assert compile("a|ab").fullmatch("ab").span() == (0, 2)


def test_match_object_accessors():
    m = compile(r"(a)(b)?(c)").match("ac")
    assert m.group() == "ac"
    assert m.group(0) == "ac"
    assert m.group(1) == "a"
    assert m.group(2) is None
    assert m.group(3) == "c"
    assert m.group(1, 3) == ("a", "c")
    assert m[0] == "ac"
    assert m[2] is None
    assert m.groups() == ("a", None, "c")
    assert m.groups(default="-") == ("a", "-", "c")
    assert m.span() == (0, 2)
    assert m.span(1) == (0, 1)
    assert m.span(2) == (-1, -1)
    assert m.start(2) == -1
    assert m.end(2) == -1
    assert m.start(3) == 1
    assert m.end(3) == 2
    assert m.string == "ac"
    assert m.pattern.pattern == r"(a)(b)?(c)"
    assert "Match" in repr(m)


def test_invalid_group_index_raises_index_error():
    m = compile(r"(a)").match("a")
    for bad in (2, -1, 100, "1", 1.0, True):
        with pytest.raises(IndexError):
            m.group(bad)
        with pytest.raises(IndexError):
            m.span(bad)
        with pytest.raises(IndexError):
            m.start(bad)


def test_search_tries_every_position_including_end():
    assert compile("$").search("abc").span() == (3, 3)
    assert compile("x").search("abc") is None
    assert compile("").search("").span() == (0, 0)


def test_findall_shapes():
    assert compile("a").findall("banana") == ["a", "a", "a"]
    assert compile("(a)n").findall("banana") == ["a", "a"]
    assert compile("(a)(n)?").findall("banana") == [("a", "n"), ("a", "n"), ("a", "")]
    assert compile("(a)|(b)").findall("ab") == [("a", ""), ("", "b")]
    assert compile("x").findall("abc") == []


def test_finditer_yields_matches():
    spans = [m.span() for m in compile("a*").finditer("baaa")]
    assert spans == [(0, 0), (1, 4), (4, 4)]
