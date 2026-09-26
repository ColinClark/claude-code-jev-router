import re
import warnings

import pytest
from fuzzgen import compare

import miniregex
from miniregex import RegexError, compile

TEXTS = ["", "a", "ab", "aab", "abab", "ba", "a\n", "\n", "a b_1-", "xyz", "aaa\nbbb\n", "1a-"]


def check(pattern, texts=TEXTS):
    compare(pattern, texts)


# --- API --------------------------------------------------------------------


def test_public_api():
    assert miniregex.compile is compile
    assert issubclass(RegexError, Exception)
    p = compile(r"(\w+)-(\d+)?")
    m = p.search("  foo-  ")
    assert m.group() == "foo-"
    assert m.group(0) == "foo-"
    assert m.group(1) == "foo"
    assert m.group(2) is None
    assert m.group(1, 2) == ("foo", None)
    assert m.groups() == ("foo", None)
    assert m.groups("") == ("foo", "")
    assert m.span() == (2, 6)
    assert m.span(1) == (2, 5)
    assert m.span(2) == (-1, -1)
    assert (m.start(), m.end()) == (2, 6)
    assert (m.start(2), m.end(2)) == (-1, -1)
    assert m[1] == "foo"
    assert p.groups == 2
    assert p.pattern == r"(\w+)-(\d+)?"


def test_bad_group_index():
    m = compile("(a)").match("a")
    for n in (2, -1):
        with pytest.raises(IndexError):
            m.group(n)
        with pytest.raises(IndexError):
            m.span(n)


def test_match_vs_search_vs_fullmatch():
    p = compile("b+")
    assert p.match("abb") is None
    assert p.search("abb").span() == (1, 3)
    assert p.fullmatch("abb") is None
    assert p.fullmatch("bb").span() == (0, 2)
    # fullmatch backtracks into alternatives to reach the end
    assert compile("a|ab").fullmatch("ab").group() == "ab"
    assert compile("a|ab").match("ab").group() == "a"


def test_findall_shapes():
    assert compile(r"\d+").findall("a1b22c333") == ["1", "22", "333"]
    assert compile(r"(\w)=(\d)?").findall("a=1 b= c=3") == [("a", "1"), ("b", ""), ("c", "3")]
    assert compile(r"(\w)\d").findall("a1b2") == ["a", "b"]
    assert compile("x*").findall("axxb") == ["", "xx", "", ""]
    assert compile("a??").findall("a") == ["", "a", ""]


# --- syntax and semantics against re ----------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [
        "abc",
        "a.c",
        ".",
        r"a\.b",
        r"\\",
        r"\*\+\?\(\)\[\]\{\}\|\^\$\-",
        r"\d+",
        r"\D+",
        r"\w+",
        r"\W+",
        r"\s+",
        r"\S+",
        r"\n",
        "[abc]+",
        "[^abc]+",
        "[a-c1]+",
        "[-a]+",
        "[a-]+",
        "[]a]+",
        "[^]a]+",
        r"[\d\s]+",
        r"[^\w]+",
        r"[\]\\\-]+",
        r"[.*+?]+",
        "[a-a]",
        "^a",
        "a$",
        "^$",
        "$",
        "^",
        "a*",
        "a+",
        "a?",
        "a*?",
        "a+?",
        "a??",
        "a{2}",
        "a{2,}",
        "a{1,2}",
        "a{,2}",
        "a{0}",
        "a{2}?",
        "a{1,}?",
        "a{,2}?",
        "a{0,0}",
        "a{",
        "a{x}",
        "a{1",
        "a{1,2",
        "x{}",
        "}",
        "]",
        "{",
        "a|b|",
        "|",
        "a|ab",
        "(a)|(b)",
        "(a)(b)?",
        "(?:ab)+",
        "(a|b)*",
        "(a|b)*?b",
        "(a*)*",
        "(a*)+",
        "(a*?)*",
        "(a|)*",
        "(|a)*",
        "(|a)+?",
        "(a|b|)+",
        "((a)|b)+",
        "(?:(a)|b)+",
        "(?:(a)|(b))*",
        "((a)|(b))*?$",
        "(a+|b+)*c?",
        "(a(b)?)+",
        "()",
        "()*",
        "(?:)*",
        "(()|a)+",
        "(a?){2,3}",
        "(a?){,2}?",
        "(a|ab)(c|bcd)?(d*)",
        r"(\w+)\s(\w+)",
        r"^(\w+)\s*$",
        r"(.*)\n",
        r"(.*)$",
        "(?:a|b)*?(b)",
        "a(?:b|c)*?c",
    ],
)
def test_against_re(pattern):
    check(pattern, TEXTS + ["abcbcd", "abcd", "acbbc", "bab", "aaaa", "ab\n", "a\nb"])


def test_dollar_before_final_newline():
    assert compile("a$").search("a\n").span() == (0, 1)
    assert compile("a$").search("a\n\n") is None
    assert compile("$").findall("a\n") == re.findall("$", "a\n")
    assert compile("^a").search("b\na") is None


def test_dot_excludes_newline_and_negated_set_includes_it():
    assert compile(".").fullmatch("\n") is None
    assert compile("[^a]").fullmatch("\n").group() == "\n"


def test_last_iteration_captures():
    m = compile(r"(?:(\d)|([a-z]))+").fullmatch("1a2b")
    assert m.groups() == ("2", "b")
    assert m.span(1) == (2, 3)
    m = compile("(a|b)*").fullmatch("abba")
    assert m.group(1) == "a"
    assert m.span(1) == (3, 4)


def test_long_input_does_not_recurse():
    text = "ab" * 20000
    assert compile("(ab)*").fullmatch(text).span(1) == (len(text) - 2, len(text))
    assert compile("(?:a|b)*c").search(text[:2000]) is None
    assert compile(".*?b$").match(text).end() == len(text)


# --- errors -----------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [
        "(",
        "(a",
        ")",
        "a)",
        "(?:a",
        "[",
        "[a",
        "[]",
        "[^]",
        "[b-a]",
        r"[\d-z]",
        r"[a-\w]",
        "*",
        "+a",
        "?",
        "a**",
        "a*??",
        "a{2}{3}",
        "a{3,2}",
        "{2}",
        "^*",
        "$+",
        "a|*",
        "(*)",
        "\\",
        r"\q",
        r"[\q]",
    ],
)
def test_invalid_patterns(pattern):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(re.error):
            re.compile(pattern)
    with pytest.raises(RegexError):
        compile(pattern)


@pytest.mark.parametrize("pattern", ["a*+", "(?=a)", "(?P<x>a)", r"\1", r"\b"])
def test_unsupported_patterns_raise(pattern):
    with pytest.raises(RegexError):
        compile(pattern)


def test_error_has_position():
    with pytest.raises(RegexError) as info:
        compile("ab)")
    assert info.value.pos == 2
