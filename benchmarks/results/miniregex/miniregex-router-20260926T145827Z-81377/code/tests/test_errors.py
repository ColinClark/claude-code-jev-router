import re

import pytest

from miniregex import RegexError, compile

INVALID = [
    "(",
    ")",
    "a)",
    "(a",
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
    "a|*",
    "(*)",
    "^*",
    "$+",
    "a**",
    "a*+?",
    "a+*",
    "a??+",
    "a{2}{3}",
    "a{2}*",
    "a*??",
    "a{3,2}",
    "{1}",
    "\\",
    "a\\",
    r"\q",
    r"\e",
    r"[\q]",
    r"\x4",
    r"\x",
    r"\u12",
]

UNSUPPORTED = [
    "(?P<x>a)",
    "(?=a)",
    "(?!a)",
    "(?<=a)",
    "(?i)a",
    r"(a)\1",
    "a*+",
    "a{2}+",
]


@pytest.mark.parametrize("pattern", INVALID)
def test_invalid_patterns_raise(pattern):
    with pytest.raises(re.error):
        re.compile(pattern)
    with pytest.raises(RegexError):
        compile(pattern)


@pytest.mark.parametrize("pattern", UNSUPPORTED)
def test_unsupported_syntax_raises(pattern):
    with pytest.raises(RegexError):
        compile(pattern)


def test_regex_error_is_value_error():
    with pytest.raises(ValueError):
        compile("(")


LITERAL_BRACES = ["{", "a{", "a{}", "a{x}", "a{1", "a{1,", "a{,x}", "}", "]", "a{1}{", "x{ 1}"]


@pytest.mark.parametrize("pattern", LITERAL_BRACES)
def test_braces_that_are_literals(pattern):
    re.compile(pattern)
    compile(pattern)
