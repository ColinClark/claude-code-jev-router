"""Invalid patterns must raise RegexError (and re must reject them too)."""

from __future__ import annotations

import re
import warnings

import pytest

import miniregex
from miniregex import RegexError

# Patterns that re rejects with re.error.
INVALID = [
    "(", ")", "a)", "(a", "((a)", "(a))", "(?", "(?:", "(?:a", "*", "+", "?", "*a", "(*)",
    "a|*", "(?:*)", "a**", "a*+*", "a+*", "a??*", "a{2}*", "a{2}{3}", "a*{2}", "{1}",
    "{1,2}", "a{3,2}", "^*", "$?", r"\b+", r"\A*", r"\Z{2}", "[", "[a", "[^", "[]", "[^]",
    "[a-", "[z-a]", "[b-a]", r"[a-\d]", r"[\d-a]", "\\", "a\\", r"\q", r"\e", r"\g", r"\i",
    r"\x", r"\x4", r"\u12", r"\U0000004", r"[\q]", r"[\A]", r"[\Z]", r"[\B]", r"\N",
    r"\N{NOT A NAME}", r"[\8]", r"\8", r"(?x", "(?<", r"\400", "|*", "a|+", "(|?)",
]

# Patterns re accepts but miniregex rejects on purpose (outside the supported subset).
UNSUPPORTED = [
    "a*+", "a++", "a?+", "a{2}+",  # possessive quantifiers
    "(?=a)", "(?!a)", "(?<=a)", "(?<!a)", "(?P<n>a)", "(?i)a", "(?>a)", "(?#c)",  # extensions
    r"(a)\1",  # backreferences
]


@pytest.mark.parametrize("pattern", INVALID)
def test_invalid_patterns(pattern: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(re.error):
            re.compile(pattern)
    with pytest.raises(RegexError):
        miniregex.compile(pattern)


@pytest.mark.parametrize("pattern", UNSUPPORTED)
def test_unsupported_constructs_raise(pattern: str) -> None:
    with pytest.raises(RegexError):
        miniregex.compile(pattern)


@pytest.mark.parametrize(
    "pattern",
    ["a{", "a{x}", "{", "a{}", "a{,}", "a{1", "a{1,2", "x{,y}", "]", "}", r"\/", r"\ ",
     "a*?", "a{2}?", "(?:)*", "()*", "(?:^)*", "[]a]", "[^]a]", "[a-]", "[-a]"],
)
def test_valid_edge_cases_compile(pattern: str) -> None:
    re.compile(pattern)
    miniregex.compile(pattern)


def test_error_messages_are_informative() -> None:
    with pytest.raises(RegexError, match="nothing to repeat"):
        miniregex.compile("*a")
    with pytest.raises(RegexError, match="multiple repeat"):
        miniregex.compile("a**")
    with pytest.raises(RegexError, match="bad character range"):
        miniregex.compile("[z-a]")
    with pytest.raises(RegexError, match="min repeat greater than max repeat"):
        miniregex.compile("a{3,2}")
    with pytest.raises(RegexError, match="unbalanced parenthesis"):
        miniregex.compile("a)")
    with pytest.raises(RegexError, match="missing \\)"):
        miniregex.compile("(a")
    with pytest.raises(RegexError, match="bad escape"):
        miniregex.compile(r"\q")
