import pytest

import miniregex as mr


def test_literal_match():
    p = mr.compile("abc")
    assert p.fullmatch("abc")
    assert p.fullmatch("abcd") is None
    assert p.match("abcd").span() == (0, 3)
    assert p.search("xxabcxx").span() == (2, 5)


def test_dot_excludes_newline():
    p = mr.compile("a.c")
    assert p.fullmatch("abc")
    assert p.fullmatch("a\nc") is None


def test_escapes():
    for pat, s in [
        (r"\.", "."),
        (r"\\", "\\"),
        (r"\*", "*"),
        (r"\+", "+"),
        (r"\?", "?"),
        (r"\(", "("),
        (r"\)", ")"),
        (r"\[", "["),
        (r"\]", "]"),
        (r"\{", "{"),
        (r"\}", "}"),
        (r"\|", "|"),
        (r"\^", "^"),
        (r"\$", "$"),
        (r"\-", "-"),
    ]:
        assert mr.compile(pat).fullmatch(s), pat


def test_character_classes():
    assert mr.compile(r"\d+").fullmatch("12345")
    assert mr.compile(r"\d+").fullmatch("123a5") is None
    assert mr.compile(r"\D+").fullmatch("abc")
    assert mr.compile(r"\w+").fullmatch("abc_123")
    assert mr.compile(r"\W+").fullmatch(" -!")
    assert mr.compile(r"\s+").fullmatch(" \t\n\r\f\v")
    assert mr.compile(r"\S+").fullmatch("abc")


def test_character_sets():
    assert mr.compile(r"[abc]+").fullmatch("abcabc")
    assert mr.compile(r"[a-z]+").fullmatch("hello")
    assert mr.compile(r"[a-z]+").fullmatch("Hello") is None
    assert mr.compile(r"[^a-z]+").fullmatch("HELLO")
    assert mr.compile(r"[\d\w]+").fullmatch("abc123")
    assert mr.compile(r"[]a]+").fullmatch("]a]a")
    assert mr.compile(r"[a\]]+").fullmatch("a]a]")
    assert mr.compile(r"[a-]+").fullmatch("a-a-")
    assert mr.compile(r"[-a]+").fullmatch("-a-a")
    assert mr.compile(r"[^]]+").fullmatch("abc")
    assert mr.compile(r"[^]]+").fullmatch("ab]c") is None


def test_anchors():
    p = mr.compile(r"^abc$")
    assert p.fullmatch("abc")
    assert p.search("xabc") is None
    m = p.search("abc\n")
    assert m is not None
    assert m.span() == (0, 3)


def test_quantifiers():
    assert mr.compile("a*").fullmatch("")
    assert mr.compile("a*").fullmatch("aaaa")
    assert mr.compile("a+").fullmatch("") is None
    assert mr.compile("a+").fullmatch("aaaa")
    assert mr.compile("a?").fullmatch("")
    assert mr.compile("a?").fullmatch("a")
    assert mr.compile("a?").fullmatch("aa") is None
    assert mr.compile("a{3}").fullmatch("aaa")
    assert mr.compile("a{3}").fullmatch("aa") is None
    assert mr.compile("a{2,4}").fullmatch("aaa")
    assert mr.compile("a{2,}").fullmatch("aaaaaa")
    assert mr.compile("a{,3}").fullmatch("aa")


def test_lazy_quantifiers():
    m = mr.compile("a+?").search("aaa")
    assert m.group() == "a"
    m = mr.compile("a{2,4}?").search("aaaa")
    assert m.group() == "aa"
    m = mr.compile("<.+?>").search("<a><b>")
    assert m.group() == "<a>"


def test_alternation():
    p = mr.compile("cat|dog")
    assert p.fullmatch("cat")
    assert p.fullmatch("dog")
    assert p.fullmatch("cow") is None


def test_groups():
    m = mr.compile(r"(\d+)-(\d+)").fullmatch("123-456")
    assert m.groups() == ("123", "456")
    assert m.group(0) == "123-456"
    assert m.group(1) == "123"
    assert m.group(2) == "456"
    assert m.span(1) == (0, 3)
    assert m.span(2) == (4, 7)


def test_optional_group_none():
    m = mr.compile(r"(a)(b)?").fullmatch("a")
    assert m.groups() == ("a", None)
    assert m.group(2) is None
    assert m.span(2) == (-1, -1)


def test_noncapturing_group():
    m = mr.compile(r"(?:abc)+(def)").fullmatch("abcabcdef")
    assert m.groups() == ("def",)


def test_findall_no_groups():
    assert mr.compile(r"\d+").findall("a1 b22 c333") == ["1", "22", "333"]


def test_findall_one_group():
    assert mr.compile(r"(\d)\d*").findall("1 22 333") == ["1", "2", "3"]


def test_findall_multi_group():
    assert mr.compile(r"(\d)(\d)").findall("12 34") == [("1", "2"), ("3", "4")]


def test_findall_zero_width():
    assert mr.compile(r"a*").findall("aabaa") == ["aa", "", "aa", ""]


def test_invalid_patterns_raise():
    for pat in ["(", ")", "a**", "[a-", "*a", "a{3,1}", "(?P<x>a)", r"\q", "[z-a]"]:
        with pytest.raises(mr.RegexError):
            mr.compile(pat)


def test_pattern_repr_and_attrs():
    p = mr.compile("abc")
    assert p.pattern == "abc"
    assert "abc" in repr(p)
