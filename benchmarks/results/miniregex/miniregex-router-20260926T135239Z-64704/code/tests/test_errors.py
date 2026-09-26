import re

import pytest

from miniregex import RegexError, compile

INVALID = [
    "(",
    "(a",
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
    "a|*",
    "(*)",
    "(?:+)",
    "a**",
    "a*?*",
    "a{2}{3}",
    "a+*",
    "{2}",
    "{1,3}",
    "x{2,1}",
    "^*",
    "$+",
    "^{2}",
    "\\",
    "a\\",
    r"\q",
    r"[\q]",
]


@pytest.mark.parametrize("pattern", INVALID)
def test_invalid_patterns(pattern):
    with pytest.raises(re.error):
        re.compile(pattern)
    with pytest.raises(RegexError):
        compile(pattern)


@pytest.mark.parametrize("pattern", ["(?P<n>a)", "(?=a)", "(?i)a", r"\1", r"(a)\1", "a*+"])
def test_unsupported_features_raise(pattern):
    with pytest.raises(RegexError):
        compile(pattern)


def test_error_position():
    with pytest.raises(RegexError) as info:
        compile("ab**")
    assert info.value.pos == 3
    assert "multiple repeat" in str(info.value)


LITERAL_BRACES = ["a{", "a{}", "a{x}", "a{1,x}", "a{1", "{", "}", "a{,", "x{-1}"]


@pytest.mark.parametrize("pattern", LITERAL_BRACES)
def test_invalid_brace_is_literal(pattern):
    re.compile(pattern)
    p = compile(pattern)
    text = pattern.replace("\\", "")
    assert p.search(text).span() == re.search(pattern, text).span()
