import re

import pytest

from miniregex import RegexError, compile

INVALID = [
    "(",
    "(a",
    "((a)",
    ")",
    "a)",
    "a|b)",
    "[",
    "[a",
    "[]",
    "[^]",
    "[a-",
    "[z-a]",
    r"[\d-z]",
    r"[a-\w]",
    "*",
    "+a",
    "?",
    "{1}",
    "a**",
    "a*+*",
    "a{2}{3}",
    "a?*",
    "^*",
    "$+",
    "a{3,2}",
    "\\",
    "a\\",
    r"\q",
    "|*",
    "(*)",
    "(?",
]

UNSUPPORTED_BUT_VALID_IN_RE = [
    r"\1",
    r"(a)\1",
    r"\b",
    r"\A",
    r"\Z",
    r"\x41",
    "(?=a)",
    "(?!a)",
    "(?P<name>a)",
    "(?i)a",
    "a*+",
    "a++",
    "(?>a)",
]


@pytest.mark.parametrize("pattern", INVALID)
def test_invalid_patterns_raise(pattern):
    with pytest.raises(re.error):
        re.compile(pattern)
    with pytest.raises(RegexError):
        compile(pattern)


@pytest.mark.parametrize("pattern", UNSUPPORTED_BUT_VALID_IN_RE)
def test_unsupported_syntax_raises(pattern):
    with pytest.raises(RegexError):
        compile(pattern)


def test_error_has_message_and_position():
    with pytest.raises(RegexError) as info:
        compile("ab(cd")
    assert "missing )" in str(info.value)
    assert info.value.pos == 2
    assert info.value.pattern == "ab(cd"


def test_regex_error_is_value_error():
    assert issubclass(RegexError, ValueError)
