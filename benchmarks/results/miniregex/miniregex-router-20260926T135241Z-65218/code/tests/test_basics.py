import re

import pytest

from miniregex import RegexError, compile


def fm(p, t):
    m = compile(p).fullmatch(t)
    return None if m is None else m.group()


@pytest.mark.parametrize(
    "p,t,ok",
    [
        ("abc", "abc", True), ("abc", "abd", False), (".", "x", True), (".", "\n", False),
        (r"\.", ".", True), (r"\.", "a", False), (r"\\", "\\", True), (r"\*", "*", True),
        (r"\+", "+", True), (r"\?", "?", True), (r"\(", "(", True), (r"\)", ")", True),
        (r"\[", "[", True), (r"\]", "]", True), (r"\{", "{", True), (r"\}", "}", True),
        (r"\|", "|", True), (r"\^", "^", True), (r"\$", "$", True), (r"\-", "-", True),
        (r"\d", "5", True), (r"\d", "a", False), (r"\D", "a", True), (r"\D", "5", False),
        (r"\w", "_", True), (r"\w", "-", False), (r"\W", "-", True), (r"\W", "a", False),
        (r"\s", " ", True), (r"\s", "\t", True), (r"\s", "x", False), (r"\S", "x", True),
        (r"\S", " ", False),
        ("[a-c]", "b", True), ("[a-c]", "d", False), ("[^a-c]", "d", True), ("[^a-c]", "a", False),
        (r"[\d]", "7", True), (r"[\w-]", "-", True), ("[-a]", "-", True), ("[a-]", "-", True),
        ("[]a]", "]", True), ("[]a]", "a", True), ("[^]a]", "b", True), ("[^]a]", "]", False),
        ("[a-cx-z0-9]", "y", True), ("[a-cx-z0-9]", "m", False), (r"[^\s]", "a", True),
        (r"[^\s]", " ", False), ("[.]", ".", True), ("[.]", "a", False),
    ],
)
def test_single(p, t, ok):
    assert (re.fullmatch(p, t) is not None) is ok
    assert (compile(p).fullmatch(t) is not None) is ok


def test_anchors():
    assert compile("^a").search("ba") is None
    assert compile("a$").search("ab") is None
    assert compile("a$").search("a\n").span() == (0, 1)
    assert compile("a$").search("a\n\n") is None
    assert compile("^$").search("") is not None


def test_greedy_vs_lazy():
    assert compile("a+").match("aaa").group() == "aaa"
    assert compile("a+?").match("aaa").group() == "a"
    assert compile("a*?").match("aaa").group() == ""
    assert compile("a??").match("a").group() == ""
    assert compile("a?").match("a").group() == "a"
    assert compile("a{2,3}").match("aaaa").group() == "aaa"
    assert compile("a{2,3}?").match("aaaa").group() == "aa"
    assert compile("a{2,}?").match("aaaa").group() == "aa"
    assert compile("a{2,}").match("aaaa").group() == "aaaa"
    assert compile("a{,2}").match("aaaa").group() == "aa"
    assert compile("a{,2}?").match("aaaa").group() == ""
    assert compile("a{3}").match("aaaa").group() == "aaa"
    assert compile("<.*>").search("<a><b>").group() == "<a><b>"
    assert compile("<.*?>").search("<a><b>").group() == "<a>"


def test_alternation():
    assert fm("a|ab", "ab") == "ab"
    assert compile("a|ab").match("ab").group() == "a"
    assert compile("ab|a").match("ab").group() == "ab"
    assert compile("cat|category").search("category").group() == "cat"


def test_groups():
    m = compile("(a)(?:b)((c)d)").match("abcd")
    assert m.groups() == ("a", "cd", "c")
    assert m.span(2) == (2, 4) and m.start(3) == 2 and m.end(3) == 3
    assert compile("(a|b)+").fullmatch("abab").group(1) == "b"
    m = compile("(a)|(b)").match("b")
    assert m.group(1) is None and m.span(1) == (-1, -1) and m.group(2) == "b"
    assert compile("(a)|(b)").findall("ab") == [("a", ""), ("", "b")]


def test_modes():
    p = compile("b+")
    assert p.match("abb") is None
    assert p.search("abb").span() == (1, 3)
    assert p.fullmatch("bbc") is None
    assert p.match("bbc").group() == "bb"


def test_findall():
    assert compile("a*").findall("aabaaac") == ["aa", "", "aaa", "", ""]
    assert compile(r"\d+").findall("a1b22") == ["1", "22"]
    assert compile(r"(\w)=\d").findall("a=1 b=2") == ["a", "b"]
    assert compile(r"(\w)=(\d)").findall("a=1 b=2") == [("a", "1"), ("b", "2")]


@pytest.mark.parametrize(
    "p", ["(", ")", "(a", "a)", "[a", "[", "*", "+a", "a**", "(?:a", "a|*", "[b-a]", "?", "\\"]
)
def test_errors(p):
    with pytest.raises(re.error):
        re.compile(p)
    with pytest.raises(RegexError):
        compile(p)
