"""Hand-picked patterns compared against the standard ``re`` module."""

from __future__ import annotations

import re

import pytest
from helpers import assert_same

import miniregex

TEXTS = ["", "a", "ab", "abc", "aaa", "abab", "ba", "a\n", "\n", "xabcx", "a1 b2_c3", "a.b", "{}"]

PATTERNS = [
    # literals and escapes
    "a", "abc", "", r"\.", r"\\", r"\*\+\?", r"\(\)", r"\[\]", r"\{\}", r"\|", r"\^\$", r"\-",
    r"a\.b", r"\n", r"\t",
    # dot and classes
    ".", "..", "a.c", r"\d", r"\D", r"\w+", r"\W", r"\s", r"\S+", r"\d\w", r"\w\s\w",
    # sets
    "[abc]", "[^abc]", "[a-c]+", "[^a-c]*", "[]a]", "[^]a]+", "[-a]", "[a-]", "[a\\-c]",
    r"[\d]", r"[\w.]+", r"[^\s]+", r"[\]\\]", r"[.]", "[*+?]", "[{}]", "[$^]", "[a^]",
    "[a-cx-z1]", r"[\D]", r"[^\W]", r"[\s\S]",
    # anchors
    "^", "$", "^a", "a$", "^$", "^a*$", "a|^b", "b$|a", "$\n", "a$\n?", "^\n", "(^a|b)+", "(a$)*",
    # quantifiers
    "a*", "a+", "a?", "a*?", "a+?", "a??", "a{2}", "a{1,2}", "a{2,}", "a{,2}", "a{0}", "a{1,2}?",
    "a{2,}?", "a{,2}?", "a{0,0}", "(ab)*", "(ab)+?", "(?:ab){1,2}", ".*", ".*?", ".+b", ".*?b",
    "a{", "a{x}", "a{1", "a{1,", "a{,}", "a{}", "{", "}", "x{2}y", "a{0,}",
    # alternation and groups
    "a|b", "a|ab", "ab|a", "|a", "a|", "a||b", "(a)", "(a)(b)", "(a|b)", "(a)|(b)", "((a)|b)+",
    "(a|ab)(c|bcd)?", "(?:a|b)+", "(?:(a)|b)*", "(a*)*", "(a*)+", "(a?)*", "(a|)+", "(|a)+",
    "(a*?)*", "(a?)*?", "((a)|(b))*", "(a)*", "(a)+?b", "(?:)", "()", "()*", "(?:)*", "(()|a)+",
    "(a(b)?)+", "(a(b)?)*?", "(a|b)*?b", "(ab|a)(bc|c)?", "(a+)+b", "((ab)*|b)*", "(?:a*)*",
    "([ab])+", "(\\w)(\\d)?", "(.)(.)?(.)?", "(a{0,2}){2}", "(a?){2,3}", "(a?){2,}?b",
    "((a?)(b?))+", "(a|b|)+c", "(^|a)+", "($|a)+", "(a|$)*", "(?:^|b)(a)", "(a{2})*",
    "(a{2,}?)(a*)", "(a*)(a+)", "(a+?)(a*?)", "(b)?(a)", "(x)?", "(a)|b", "b|(a)",
]


@pytest.mark.parametrize("pattern", PATTERNS)
def test_pattern_matches_re(pattern):
    for text in TEXTS:
        assert_same(pattern, text)


@pytest.mark.parametrize(
    ("pattern", "text"),
    [
        (r"(\d+)-(\d+)", "call 555-1234 or 555-9876"),
        (r"(\w+)@(\w+)\.com", "mail bob@example.com and amy@test.com"),
        (r"[A-Z][a-z]+", "Alice met Bob in Paris"),
        (r"\s+", "  lots   of \t\n whitespace  "),
        (r"(a|b)*c", "ababababc"),
        (r"^(\w+)\s(\w+)$", "hello world\n"),
        (r"(?:(\d)|x)+", "1x2x3xx"),
        (r"([^,]*),?", "a,bb,,ccc"),
        (r"<(.*?)>", "<a><bb><>"),
        (r"<(.*)>", "<a><bb><>"),
        (r"x*", "axxbxxx"),
        (r"x*?", "axxbxxx"),
        (r"\b", "ab cd"),
        (r"\B", "ab cd"),
        (r"\bab\b", "ab abc ab"),
        (r"\Aab|ab\Z", "abxab"),
        (r"\w+", "héllo wörld ٣٤"),
        (r"\d+", "٣٤5x"),
        (r"\s", "a b c"),
        (r"[\x41-\x43]+", "ABCD"),
        (r"é+", "ééé"),
        (r"\101\0", "A\0"),
    ],
)
def test_realistic(pattern, text):
    assert_same(pattern, text)


def test_long_input_does_not_recurse():
    # tens of thousands of iterations and backtracking steps, no RecursionError
    text = "ab" * 20000 + "c"
    for pattern in (r"(a|b)*c", r"(?:ab)+?c", r".*c", r"^(ab)*$", r"^(a|b)*?$"):
        m = miniregex.compile(pattern).match(text)
        expected = re.match(pattern, text)
        assert (m and (m.span(), m.groups())) == (expected and (expected.span(), expected.groups()))
