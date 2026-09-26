"""Per-feature differential tests against the ``re`` module."""

from __future__ import annotations

import pytest
from helpers import assert_same

TEXTS = [
    "",
    "a",
    "b",
    "ab",
    "ba",
    "aab",
    "abab",
    "aaa",
    "abc",
    "a\n",
    "\n",
    "a\nb\n",
    "x1_y 2",
    "hello world",
    "aaaaabbbbb",
    "{}",
    "a{2}",
    "\t\r\x0b\x0c ",
    "é٣ ",
]


def check(pattern: str, extra: tuple[str, ...] = ()) -> None:
    assert_same(pattern, TEXTS + list(extra))


@pytest.mark.parametrize(
    "pattern",
    ["", "a", "ab", "abc", "hello", "x", " ", "a b", "é", "}", "]", ",", ":", "-", "a}"],
)
def test_literals(pattern: str) -> None:
    check(pattern)


@pytest.mark.parametrize("pattern", [".", "..", "a.b", ".*", ".+", "a.*b", ".\n", "\n"])
def test_dot(pattern: str) -> None:
    check(pattern, ("a\nb", "\n\n"))


@pytest.mark.parametrize(
    "pattern",
    [
        r"\.",
        r"\\",
        r"\*",
        r"\+",
        r"\?",
        r"\(",
        r"\)",
        r"\[",
        r"\]",
        r"\{",
        r"\}",
        r"\|",
        r"\^",
        r"\$",
        r"\-",
        r"\n",
        r"\t",
        r"\r",
        r"\f",
        r"\v",
        r"\a",
        r"\x61",
        r"a",
        r"\U00000061",
        r"\0",
        r"\141",
        r"\N{LATIN SMALL LETTER A}",
        r"\#",
        r"\ ",
        r"\/",
    ],
)
def test_escapes(pattern: str) -> None:
    check(pattern, (".\\*+?()[]{}|^$-", "a\x00\x07"))


@pytest.mark.parametrize(
    "pattern",
    [r"\d", r"\D", r"\w", r"\W", r"\s", r"\S", r"\d+", r"\w+", r"\s*", r"\W\w", r"\S+\s\S+"],
)
def test_classes(pattern: str) -> None:
    check(pattern, ("abc 123_\t\n", "٣x", "\x1c\x1f", "ß"))


@pytest.mark.parametrize(
    "pattern",
    [
        "[abc]",
        "[a-c]",
        "[^abc]",
        "[^a-c]",
        "[a-]",
        "[-a]",
        "[]a]",
        "[^]a]",
        "[]]",
        "[^]]",
        r"[\d]",
        r"[\D]",
        r"[\w-]",
        r"[\s\d]",
        r"[^\s\d]",
        r"[\]]",
        r"[\\]",
        r"[\^]",
        r"[\-a]",
        "[a-a]",
        "[.]",
        "[*+?]",
        "[(){}|$^]",
        "[a-cx-z]",
        "[---]",
        "[--a]",
        r"[\n]",
        r"[\b]",
        r"[\x61-\x63]",
        r"[\0-\x20]",
        "[ab]+",
        "[^b]*",
        r"[\w\W]",
        "[a^]",
        r"[\1]",
    ],
)
def test_sets(pattern: str) -> None:
    check(pattern, ("abcxyz-]^\\.", "a-b", "\x08"))


@pytest.mark.parametrize(
    "pattern",
    [
        "^",
        "$",
        "^a",
        "a$",
        "^a$",
        "^$",
        "a^",
        "$a",
        r"\Aa",
        r"a\Z",
        r"\ba",
        r"a\b",
        r"\B",
        r"\Ba\B",
        r"\b",
        "^a|b$",
        "a$\n",
        "(^a|b)+",
        "(?:$|a)+",
    ],
)
def test_anchors(pattern: str) -> None:
    check(pattern, ("a\n", "\na", "a\n\n", "b a b", "ab\n"))


@pytest.mark.parametrize(
    "pattern",
    [
        "a*",
        "a+",
        "a?",
        "a*?",
        "a+?",
        "a??",
        "a{2}",
        "a{2,}",
        "a{2,3}",
        "a{,2}",
        "a{0}",
        "a{0,0}",
        "a{2}?",
        "a{2,}?",
        "a{1,3}?",
        "a{,2}?",
        "a{,}",
        "ab*",
        "(ab)*",
        "(ab)+?",
        "a*b",
        "a*?b",
        "a+b+",
        ".*a",
        ".*?a",
        "(a|ab)*c",
        "(a|b)*?b",
        "[ab]{2,3}",
        "x*",
        "a{1,1}",
        "(?:ab){2}",
        "(?:a|b){1,2}?b",
        "a{3}a*",
        "(a{2})*",
    ],
)
def test_quantifiers(pattern: str) -> None:
    check(pattern, ("aaaa", "abababc", "aabbabc", "c"))


@pytest.mark.parametrize(
    "pattern",
    [
        "a{",
        "a{x}",
        "a{1,x}",
        "a{1",
        "a{1,",
        "{",
        "}",
        "a{}",
        "{a}",
        "a{,",
        "x{ 1}",
        "a{1,2,3}",
        "^{",
        "a{-1}",
        "{1,2",
    ],
)
def test_literal_braces(pattern: str) -> None:
    check(pattern, ("a{x}", "a{1,x}", "{", "a{}", "a{1,2,3}", "a{-1}", "{1,2"))


@pytest.mark.parametrize(
    "pattern",
    [
        "a|b",
        "a|",
        "|a",
        "|",
        "a||b",
        "ab|a",
        "a|ab",
        "(a|ab)(c|bcd)(d*)",
        "(?:a|b|)+",
        "x(a|b)y|x(c)y",
        "(a)|b",
        "(a)|(b)",
        "((a)|(b))*",
    ],
)
def test_alternation(pattern: str) -> None:
    check(pattern, ("abcd", "xay", "xcy", "abba"))


@pytest.mark.parametrize(
    "pattern",
    [
        "(a)",
        "(a)(b)",
        "((a)b)",
        "(a(b))",
        "(?:a)(b)",
        "(?:(a)|b)*",
        "(a)*",
        "(a)+b",
        "(a|b)*",
        "(a)?b",
        "(a)?(b)?",
        "((a)|b)+",
        "(a*)+",
        "(a*)*",
        "(a|)*",
        "(a?)+?",
        "(?:)*",
        "()*",
        "()",
        "(|a)*",
        "(a*?)*",
        "(a*)*?",
        "(a|b|)*?c",
        "((a)|(b))+",
        "(?:(a)|(b))+",
        "(a*)+b",
        "(a+|b)*",
        "(a+|b){0,}",
        "(a+|b){1,}",
        "(a+|b){0,1}",
        "((a)|(b)|())*",
        "(a?){2,}",
        "(a?){3}",
        "(a??){2,}",
        "(?:a|()){2,3}",
        "(a?)*?b",
        "(?:(a)|b)*?c",
        "(()|a)+",
        "((a?)*)*",
        "(a)(?:(b)|c)*",
    ],
)
def test_groups(pattern: str) -> None:
    check(pattern, ("aab", "abab", "bab", "c", "abc", "aac", "baac"))


@pytest.mark.parametrize(
    "pattern",
    [r"(a)\1", r"(a*)\1", r"(a|b)\1+", r"(?:(a)|b)\1", r"(a)|\1", r"((a)b)\2\1", r"(a*)b\1"],
)
def test_backreferences(pattern: str) -> None:
    check(pattern, ("aa", "aabaab", "abab", "bb", "aaba", "abaab"))


@pytest.mark.parametrize(
    "pattern,text",
    [
        ("", "abc"),
        ("a*", "baaa"),
        ("a|", "baac"),
        ("(a)|b", "abxb"),
        ("(a)|(b)", "abxb"),
        (r"\b", "ab cd"),
        ("$", "a\n"),
        ("(a*)*", "aab"),
        ("a*?", "aaa"),
        ("x*", "\n\n"),
    ],
)
def test_findall_empty_matches(pattern: str, text: str) -> None:
    assert_same(pattern, text)


def test_long_inputs_do_not_overflow() -> None:
    long_a = "a" * 5000
    assert_same("a*", long_a)
    assert_same("(?:a)*", long_a)
    assert_same("(a)*", long_a)
    assert_same("(?:aa)*", long_a)
    assert_same("(a|b)*c?", long_a)
    assert_same(".*b", long_a)
    assert_same("[ab]*?$", long_a[:2000])
