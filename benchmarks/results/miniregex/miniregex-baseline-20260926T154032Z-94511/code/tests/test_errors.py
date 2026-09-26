"""Invalid patterns raise RegexError wherever ``re`` raises re.error."""

from __future__ import annotations

import re

import pytest
from helpers import re_compile

from miniregex import RegexError, compile

INVALID = [
    "(", ")", "a)", "(a", "((a)", "[", "[a", "[]", "[^]", "[a-", "[b-a]", r"[\d-z]", r"[a-\w]",
    "*", "+", "?", "*a", "a**", "a+*", "a?*", "a{2}*",
    "a{2}{3}", "{2}", "a|*", "(*)", "(?:*)", "^*", "$+", r"\b*", r"\A?", "a{3,2}", "\\", r"\q",
    r"\x", r"\x1", r"\u12", r"[\q]", r"[\A]", r"(?", "(?:", "a{4294967295}",
]

UNSUPPORTED = [
    r"(a)\1", r"(?P<n>a)", r"(?=a)", r"(?!a)", r"(?<=a)", r"(?i)a", "a*+", "a++", "a?+",
    "a{2}+", r"\N{DIGIT ONE}",
]


@pytest.mark.parametrize("pattern", INVALID)
def test_invalid_patterns(pattern):
    with pytest.raises((re.error, OverflowError)):
        re_compile(pattern)
    with pytest.raises(RegexError):
        compile(pattern)


@pytest.mark.parametrize("pattern", UNSUPPORTED)
def test_unsupported_features(pattern):
    with pytest.raises(RegexError, match="not supported"):
        compile(pattern)


@pytest.mark.parametrize(
    "pattern", ["a{", "a{}", "a{x}", "a{1,2", "{", "}", "]", "a{,}", "(?:)*", "()*", "(?:a*)*"]
)
def test_valid_edge_syntax(pattern):
    re_compile(pattern)
    compile(pattern)


def test_error_carries_position():
    with pytest.raises(RegexError) as info:
        compile("ab)")
    assert info.value.pos == 2
