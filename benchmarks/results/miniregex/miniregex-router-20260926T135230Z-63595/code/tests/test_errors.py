"""Invalid patterns must raise RegexError, just like re raises re.error."""

from __future__ import annotations

import sys

import pytest
from helpers import assert_both_reject

import miniregex

INVALID = [
    "*",
    "*a",
    "+",
    "?",
    "{1}",
    "a**",
    "a*+*",
    "a+*",
    "a??*",
    "a{1}{2}",
    "a{2}*",
    "(*)",
    "(+a)",
    "|*",
    "^*",
    "$+",
    r"\b*",
    r"\A?",
    "a|*",
    "(?:)**",
    "a{2,1}",
    "a{3,2}?",
    "(",
    ")",
    "a)",
    "(a",
    "((a)",
    "(a))",
    "(?",
    "(?:",
    "(?:a",
    "())",
    "[",
    "[a",
    "[^",
    "[]",
    "[^]",
    "[a-",
    "[b-a]",
    "[z-a]",
    r"[\d-a]",
    r"[a-\d]",
    r"[\w-\d]",
    "\\",
    "a\\",
    r"\q",
    r"\e",
    r"\c",
    r"\g",
    r"\i",
    r"\j",
    r"\k",
    r"\l",
    r"\m",
    r"\o",
    r"\p",
    r"\y",
    r"\C",
    r"\E",
    r"\F",
    r"\G",
    r"\H",
    r"\I",
    r"\J",
    r"\K",
    r"\L",
    r"\M",
    r"\O",
    r"\P",
    r"\Q",
    r"\R",
    r"\T",
    r"\V",
    r"\X",
    r"\Y",
    r"[\q]",
    r"[\A]",
    r"[\Z]",
    r"[\B]",
    r"[\8]",
    r"\x",
    r"\x6",
    r"\u12",
    r"\U1234",
    r"\1",
    r"(a)\2",
    r"(a\1)",
    r"\8",
    r"\N",
    r"\N{",
    r"\N{NOT A REAL NAME}",
    r"[\x]",
    r"\777",
    r"\U00110000",
]
if sys.version_info < (3, 14):
    INVALID.append(r"\z")  # \z is an alias of \Z since Python 3.14


@pytest.mark.parametrize("pattern", INVALID)
def test_invalid_patterns(pattern: str) -> None:
    assert_both_reject(pattern)


UNSUPPORTED = [
    "a*+",
    "a++",
    "a?+",
    "a{2}+",
    "(?=a)",
    "(?!a)",
    "(?<=a)",
    "(?<!a)",
    "(?i)a",
    "(?P<n>a)",
    "(?#x)",
    "(?>a)",
    "(?i:a)",
]


@pytest.mark.parametrize("pattern", UNSUPPORTED)
def test_unsupported_syntax_is_rejected(pattern: str) -> None:
    with pytest.raises(miniregex.RegexError):
        miniregex.compile(pattern)


def test_regex_error_attributes() -> None:
    with pytest.raises(miniregex.RegexError) as info:
        miniregex.compile("ab)")
    assert info.value.pattern == "ab)"
    assert info.value.pos == 2
    assert isinstance(info.value, Exception)


def test_non_string_pattern() -> None:
    with pytest.raises(TypeError):
        miniregex.compile(b"a")  # type: ignore[arg-type]
