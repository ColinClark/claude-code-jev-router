import pytest

import miniregex
from miniregex import RegexError, compile


def test_public_names():
    assert miniregex.compile is compile
    assert issubclass(RegexError, Exception)


def test_fullmatch_match_search():
    p = compile(r"b+")
    assert p.fullmatch("abb") is None
    assert p.match("abb") is None
    m = p.search("abb")
    assert m is not None
    assert m.group() == "bb"
    assert m.span() == (1, 3)
    assert p.fullmatch("bbb").span() == (0, 3)
    assert p.match("bba").span() == (0, 2)


def test_match_accessors():
    m = compile(r"(\w+)@(\w+)(x)?").search("mail bob@example now")
    assert m.group(0) == m.group() == "bob@example"
    assert m.group(1) == "bob"
    assert m.group(2) == "example"
    assert m.group(3) is None
    assert m.group(1, 2) == ("bob", "example")
    assert m.groups() == ("bob", "example", None)
    assert m.groups("-") == ("bob", "example", "-")
    assert m.span(2) == (9, 16)
    assert m.start(1) == 5 and m.end(1) == 8
    assert m.span(3) == (-1, -1)
    assert m.start(3) == -1 and m.end(3) == -1
    assert m[1] == "bob"
    assert "bob@example" in repr(m)


def test_bad_group_index():
    m = compile("(a)").match("a")
    for bad in (2, -1, "1"):
        with pytest.raises(IndexError):
            m.group(bad)
        with pytest.raises(IndexError):
            m.span(bad)


def test_findall_shapes():
    assert compile(r"\d+").findall("a1b22c333") == ["1", "22", "333"]
    assert compile(r"(\d)\d*").findall("a1b22c333") == ["1", "2", "3"]
    assert compile(r"(\w)(\d)?").findall("a1b") == [("a", "1"), ("b", "")]
    assert compile(r"x*").findall("axx") == ["", "xx", ""]
    assert compile("(a)|b").findall("ab") == ["a", ""]


def test_finditer():
    spans = [m.span() for m in compile("a*").finditer("baaa")]
    assert spans == [(0, 0), (1, 4), (4, 4)]


def test_pattern_attributes():
    p = compile("(a)(?:b)(c)")
    assert p.pattern == "(a)(?:b)(c)"
    assert p.groups == 2


def test_last_iteration_capture():
    m = compile(r"(?:(\d)|x)*").fullmatch("1x2x")
    assert m.group(1) == "2"
    assert m.span(1) == (2, 3)


def test_long_input_does_not_recurse():
    text = "ab" * 20000
    m = compile("(ab)*").fullmatch(text)
    assert m.span(1) == (len(text) - 2, len(text))
    assert compile(r"(?:a|b)*?$").match(text).end() == len(text)


def test_pattern_must_be_str():
    with pytest.raises(TypeError):
        compile(b"a")
