import pytest

import miniregex as mr


def test_literal_match():
    p = mr.compile("abc")
    assert p.fullmatch("abc") is not None
    assert p.fullmatch("abcd") is None
    assert p.match("abcd").span() == (0, 3)
    assert p.search("xxabcyy").span() == (2, 5)


def test_dot_excludes_newline():
    p = mr.compile("a.b")
    assert p.fullmatch("axb") is not None
    assert p.fullmatch("a\nb") is None


def test_escapes():
    p = mr.compile(r"\d\.\d")
    assert p.fullmatch("1.2") is not None
    assert p.fullmatch("a.b") is None
    p2 = mr.compile(r"\$\^\|\(\)\[\]\{\}\+\*\?\-\\")
    assert p2.fullmatch("$^|()[]{}+*?-\\") is not None


def test_classes():
    assert mr.compile(r"\d+").fullmatch("123") is not None
    assert mr.compile(r"\D+").fullmatch("abc") is not None
    assert mr.compile(r"\w+").fullmatch("abc_123") is not None
    assert mr.compile(r"\W+").fullmatch("!@#") is not None
    assert mr.compile(r"\s+").fullmatch(" \t\n\r\f\v") is not None
    assert mr.compile(r"\S+").fullmatch("abc") is not None


def test_char_set_ranges_and_negation():
    p = mr.compile("[a-c]+")
    assert p.fullmatch("abcabc") is not None
    assert p.fullmatch("abd") is None

    p2 = mr.compile("[^a-c]+")
    assert p2.fullmatch("xyz") is not None
    assert p2.fullmatch("axz") is None

    p3 = mr.compile("[-a]+")
    assert p3.fullmatch("-a-a") is not None

    p4 = mr.compile("[a-]+")
    assert p4.fullmatch("-a-a") is not None

    p5 = mr.compile("[]a]+")
    assert p5.fullmatch("]a]a") is not None

    p6 = mr.compile(r"[\d\s]+")
    assert p6.fullmatch("1 2\t3") is not None


def test_anchors():
    p = mr.compile("^abc$")
    assert p.fullmatch("abc") is not None
    assert p.search("xabcx") is None
    assert p.search("abc\n") is not None  # $ matches before trailing \n


def test_quantifiers():
    assert mr.compile("a*").fullmatch("") is not None
    assert mr.compile("a*").fullmatch("aaa") is not None
    assert mr.compile("a+").fullmatch("") is None
    assert mr.compile("a+").fullmatch("aaa") is not None
    assert mr.compile("a?").fullmatch("") is not None
    assert mr.compile("a?").fullmatch("a") is not None
    assert mr.compile("a?").fullmatch("aa") is None
    assert mr.compile("a{3}").fullmatch("aaa") is not None
    assert mr.compile("a{3}").fullmatch("aa") is None
    assert mr.compile("a{2,}").fullmatch("a") is None
    assert mr.compile("a{2,}").fullmatch("aa") is not None
    assert mr.compile("a{2,4}").fullmatch("aaaaa") is None
    assert mr.compile("a{2,4}").fullmatch("aaa") is not None
    assert mr.compile("a{,3}").fullmatch("aa") is not None


def test_lazy_quantifiers():
    p = mr.compile("a+?")
    m = p.search("aaa")
    assert m.span() == (0, 1)
    p2 = mr.compile("a{2,4}?")
    assert p2.search("aaaa").span() == (0, 2)


def test_alternation_and_groups():
    p = mr.compile("(ab|a)(c|bc)")
    m = p.fullmatch("abc")
    assert m.groups() == ("ab", "c")

    p2 = mr.compile("(?:ab)+")
    assert p2.fullmatch("abab") is not None


def test_group_not_participating():
    p = mr.compile("(a)?b")
    m = p.match("b")
    assert m.group(1) is None
    assert m.span(1) == (-1, -1)
    assert m.start(1) == -1
    assert m.end(1) == -1


def test_group_last_iteration_wins():
    p = mr.compile("(a|b)+")
    m = p.fullmatch("aba")
    assert m.group(1) == "a"
    assert m.span(1) == (2, 3)


def test_findall():
    assert mr.compile(r"\d+").findall("a12b345c") == ["12", "345"]
    assert mr.compile(r"(a)(b)?").findall("a ab") == [("a", ""), ("a", "b")]
    assert mr.compile("").findall("ab") == ["", "", ""]
    assert mr.compile("a*").findall("aaa") == ["aaa", ""]


def test_invalid_patterns_raise():
    for bad in ["a**", "*a", "(a", "a)", "[a", "a{2,1}", r"\q", "(?P<x>a)"]:
        with pytest.raises(mr.RegexError):
            mr.compile(bad)


def test_findall_single_group_none_is_empty_string():
    p = mr.compile(r"(a)?b")
    assert p.findall("b ab") == ["", "a"]
