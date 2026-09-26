"""Invalid patterns raise RegexError; re's edge-case literals are accepted."""

import re

import pytest

from miniregex import RegexError, compile

REJECTED_BY_RE = [
    "*a",
    "+a",
    "?a",
    "(*)",
    "(+)",
    "a|*",
    "^*",
    "$*",
    "$+",
    "a**",
    "a*+*",
    "a*?*",
    "a??*",
    "a{3}{2}",
    "a{2}??",
    "a*{2}",
    "{2}",
    "{1,2}",
    "a{2,1}",
    "a{5,3}?",
    "[z-a]",
    "[b-a]",
    "[a-\\d]",
    "[\\d-z]",
    "[abc",
    "[",
    "[^",
    "[^]",
    "[]",
    "[a-",
    "a\\",
    "\\",
    "(a",
    "(",
    "((a)",
    "a)",
    ")",
    "(?:a",
    "(?",
    "(?x",
    "\\q",
    "\\1",
    "\\2",
]


@pytest.mark.parametrize("pattern", REJECTED_BY_RE)
def test_patterns_re_rejects_are_rejected(pattern):
    with pytest.raises(re.error):
        re.compile(pattern)
    with pytest.raises(RegexError):
        compile(pattern)


# re accepts these but miniregex intentionally does not implement them.
UNSUPPORTED = [
    "(?=a)",
    "(?!a)",
    "(?<=a)",
    "(?<!a)",
    "(?P<n>a)",
    "(?P<n>a)(?P=n)",
    "(?i)a",
    "(?#c)",
    "(?>a)",
    "a*+",
    "a++",
    "a?+",
    "a{1,2}+",
    "\\b",
    "\\B",
    "\\A",
    "\\Z",
    "\\x41",
    "\\u0041",
    "\\N{BULLET}",
    "\\0",
    "[\\b]",
]


@pytest.mark.parametrize("pattern", UNSUPPORTED)
def test_unsupported_constructs_raise(pattern):
    re.compile(pattern)  # sanity: re accepts these
    with pytest.raises(RegexError):
        compile(pattern)


def test_error_message_mentions_position():
    with pytest.raises(RegexError, match="nothing to repeat at position 0"):
        compile("*")
    with pytest.raises(RegexError, match="multiple repeat"):
        compile("a**")
    with pytest.raises(RegexError, match="unterminated character set"):
        compile("[ab")
    with pytest.raises(RegexError, match="unbalanced parenthesis"):
        compile("a)")
    with pytest.raises(RegexError, match="min repeat greater than max repeat"):
        compile("a{2,1}")


def test_huge_repeat_count_rejected():
    with pytest.raises(RegexError):
        compile("a{4294967295}")
    with pytest.raises(RegexError):
        compile("a{1,4294967295}")


# Strings where re treats a special character as a plain literal.
LITERAL_EDGE_CASES = [
    ("a{", "a{"),
    ("a{x}", "a{x}"),
    ("{", "{"),
    ("a{}", "a{}"),
    ("a{1", "a{1"),
    ("a{1,", "a{1,"),
    ("a{1,2", "a{1,2"),
    ("}", "}"),
    ("]", "]"),
    ("a{3}}", "aaa}"),
    ("\\-", "-"),
    ("\\#", "#"),
    ("\\ ", " "),
    ("\\.", "."),
    ("\\\\", "\\"),
]


@pytest.mark.parametrize(("pattern", "text"), LITERAL_EDGE_CASES)
def test_literal_edge_cases_match_like_re(pattern, text):
    assert re.fullmatch(pattern, text) is not None
    assert compile(pattern).fullmatch(text) is not None
    assert compile(pattern).fullmatch(text + "x") is None


def test_nothing_to_repeat_check_uses_last_item_like_re():
    # `(?:^)*` is accepted by re because the repeated item is a group.
    re.compile("(?:^)*")
    assert compile("(?:^)*").match("a").span() == (0, 0)
    # `(?:a*)*` is fine, `a**` is not.
    assert compile("(?:a*)*").match("aa").span() == (0, 2)
