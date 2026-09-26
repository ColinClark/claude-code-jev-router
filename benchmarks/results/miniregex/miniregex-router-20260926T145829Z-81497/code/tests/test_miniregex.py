"""Hand-written tests for miniregex, each compared against Python's re."""

import re

import pytest
from helpers import assert_same

from miniregex import RegexError, compile

TEXTS = ["", "a", "abc", "aXb", "a.b", "a\nb", "abc\n", "\n", "112 ab_c", "a-b]c", "{}|^$*"]


@pytest.mark.parametrize(
    "pattern",
    [
        # literals, dot and escapes
        "abc", "a.c", ".", "..", "\\.", "\\\\", "\\*", "\\+", "\\?", "\\(\\)", "\\[\\]",
        "\\{\\}", "\\|", "\\^", "\\$", "\\-", "a\\nb", "\\t",
        # classes
        "\\d", "\\D+", "\\w+", "\\W", "\\s", "\\S+", "\\d\\s\\w",
        # sets
        "[abc]", "[^abc]", "[a-c]+", "[-a]", "[a-]", "[]a]", "[^]a]", "[\\]]", "[\\d]", "[^\\d]",
        "[\\w-]+", "[a\\-z]", "[.]", "[$^]", "[\\n]", "[\\s\\d]+", "[^\\W_]+", "[]-a]", "[--/]",
        # anchors
        "^a", "a$", "^$", "^", "$", "^abc$", "b$", "\\n$", "$\\n", "a|^b", "(^a|b)",
        # quantifiers
        "a*", "a+", "a?", "a*?", "a+?", "a??", "a{2}", "a{1,2}", "a{2,}", "a{,2}", "a{0}",
        "a{1,2}?", "a{2,}?", "a{,2}?", "a{", "a{x}", "a{1", "a{1,", "{", "}", "a{}", "a{,}",
        "(?:ab)*", "(?:ab)+?c", ".*b", ".*?b", ".+", "(.*)(.*)",
        # alternation and groups
        "a|b", "ab|ac", "a|ab|abc", "(a)|b", "(a)(b)?", "(a|ab)(c|bcd)(d*)", "(?:a|b)(c)",
        "()", "(|a)", "((a)(b))", "(a(b(c)))", "(a)|(b)|(c)", "a||b", "|",
    ],
)
def test_against_re(pattern):
    assert_same(pattern, TEXTS)


def test_api_basics():
    p = compile(r"(\w+)@(\w+)\.com")
    m = p.search("mail bob@example.com now")
    assert m is not None
    assert m.group() == "bob@example.com"
    assert m.group(0) == m.group()
    assert m.group(1) == "bob"
    assert m.group(1, 2) == ("bob", "example")
    assert m.groups() == ("bob", "example")
    assert m.span() == (5, 20)
    assert m.span(2) == (9, 16)
    assert m.start(1) == 5 and m.end(1) == 8
    assert p.match("bob@example.com!") is not None
    assert p.match(" bob@example.com") is None
    assert p.fullmatch("bob@example.com!") is None
    assert p.groups == 2


def test_unmatched_group():
    m = compile("(a)|(b)").match("b")
    assert m.groups() == (None, "b")
    assert m.group(1) is None
    assert m.span(1) == (-1, -1)
    assert m.start(1) == -1 and m.end(1) == -1
    assert m.groups("x") == ("x", "b")


def test_last_iteration_value():
    m = compile("(?:(a)|(b))*").match("abab")
    assert m.groups() == re.match("(?:(a)|(b))*", "abab").groups() == ("a", "b")
    m = compile("(a|b)*").match("aab")
    assert m.group(1) == "b" and m.span(1) == (2, 3)


def test_no_such_group():
    m = compile("(a)").match("a")
    with pytest.raises(IndexError):
        m.group(2)
    with pytest.raises(IndexError):
        m.span(-1)


def test_findall_shapes():
    assert compile("a").findall("banana") == ["a", "a", "a"]
    assert compile("(a)n").findall("banana") == ["a", "a"]
    assert compile("(a)(n)?").findall("banana") == [("a", "n"), ("a", "n"), ("a", "")]
    assert compile("a*").findall("baac") == re.findall("a*", "baac")
    assert compile("a*?").findall("aa") == re.findall("a*?", "aa")
    assert compile("|a").findall("aa") == re.findall("|a", "aa")
    assert compile("(a)|b").findall("ab") == ["a", ""]


def test_dollar_before_final_newline():
    assert compile("a$").search("a\n").span() == (0, 1)
    assert compile("a$").search("a\n\n") is None
    assert compile("$").findall("a\n") == re.findall("$", "a\n")


@pytest.mark.parametrize(
    "pattern",
    [
        "(", ")", "a)", "(a", "(?:a", "[", "[a", "[]", "[^]", "*", "+a", "?", "a**", "a*?*",
        "a+*", "(*)", "^*", "$+", "a{2,1}", "[b-a]", "[\\d-z]", "[a-\\d]", "\\", "a\\",
        "|*",
    ],
)
def test_invalid_patterns(pattern):
    with pytest.raises(re.error):
        re.compile(pattern)
    with pytest.raises(RegexError):
        compile(pattern)


@pytest.mark.parametrize("pattern", ["(?=a)", "(?P<n>a)", "\\1", "\\b", "a*+", "\\x41", "\\A"])
def test_unsupported_syntax_is_rejected(pattern):
    with pytest.raises(RegexError):
        compile(pattern)


def test_regex_error_is_value_error():
    assert issubclass(RegexError, ValueError)


def test_long_inputs_do_not_hit_recursion_limit():
    text = "ab" * 20000 + "c"
    for pattern in ["(?:ab)*c", "(a|b)*c", "(a|b)*?c$", "(ab)+", ".*c", "[ab]*?c"]:
        want = re.search(pattern, text)
        got = compile(pattern).search(text)
        assert got.span() == want.span()
        assert got.groups() == want.groups()


def test_type_errors():
    with pytest.raises(TypeError):
        compile(b"a")
    with pytest.raises(TypeError):
        compile("a").search(b"a")


def test_ascii_classes():
    assert compile(r"\s+").fullmatch(" \t\n\r\f\v")
    assert compile(r"\w+").fullmatch("azAZ09_")
    assert compile(r"\d+").fullmatch("0123456789")
    assert compile(r"\W").fullmatch("-")
