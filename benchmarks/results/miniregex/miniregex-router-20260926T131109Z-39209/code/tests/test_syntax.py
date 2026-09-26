"""Per-feature tests; every case is checked against Python's re."""

from __future__ import annotations

import re

import pytest
from fuzzlib import compare

import miniregex

TEXTS = ["", "a", "b", "ab", "ba", "aab", "abab", "a\n", "\na", "a-b", "a.b", "x y_z9",
         "{a}", "a{2}", "[]", "a\\b", "\t\r\x0b\x0c", "AbC", "0123", "aaaa", "a b\n"]


def check(pattern: str, texts=TEXTS) -> None:
    for text in texts:
        compare(pattern, text)


LITERALS = ["a", "ab", "abc", "", "-", "a b", "]", "}", "a}", "é", ","]
ESCAPES = [r"\.", r"\\", r"\*", r"\+", r"\?", r"\(", r"\)", r"\[", r"\]", r"\{", r"\}",
           r"\|", r"\^", r"\$", r"\-", r"\/", r"\n", r"\t", r"\r", r"\f", r"\v", r"\a",
           r"\x41", r"b", r"\U00000061", r"\0", r"\012", r"\N{LATIN SMALL LETTER A}",
           r"\ ", r"\,", "\\é"]
CLASSES = [".", r"\d", r"\D", r"\w", r"\W", r"\s", r"\S", r"a.b", r"\w+", r"\s*\S"]
SETS = ["[ab]", "[^ab]", "[a-c]", "[^a-c]", "[-a]", "[a-]", "[]a]", "[^]a]", "[]]", "[^]]",
        r"[\d]", r"[\w-]", r"[\s\d]", r"[^\s]", r"[\]]", r"[\-a]", r"[a\-z]", r"[\\]",
        "[.]", "[*+?]", "[(){}|$^]", r"[\n]", r"[\x41-\x43]", "[a-b-]", "[a-a]", "[--/]",
        r"[\^]", "[a^]", r"[\b]", "[ab]+", "[^\n]*"]
ANCHORS = ["^", "$", "^a", "a$", "^$", "^a$", r"\Aa", r"a\Z", r"\b", r"\B", r"\ba", r"a\b",
           r"\Ba", "$\n", "a$\n?", "(?:^)*a", "(^)*", "($)+"]
QUANTS = ["a*", "a+", "a?", "a*?", "a+?", "a??", "a{2}", "a{2,}", "a{1,2}", "a{,2}", "a{0}",
          "a{2}?", "a{2,}?", "a{1,2}?", "a{,2}?", "a{,}", "a{}", "a{", "a{x}", "a{1", "a{1,",
          "a{,1", "{", "}", "x{", "a{ 1}", "a{1,2}{", "(ab)*", "(ab)+?", "(?:ab){2}",
          "(a|b){2,3}", "a{01}", ".*", ".+?", "[ab]{1,3}"]
ALTERNATION = ["a|b", "a|", "|a", "|", "a||b", "ab|a", "a|ab", "(a|ab)(c|bcd)", "(|a)+",
               "(a|b|)*", "x(a|b)y|x"]
GROUPS = ["(a)", "(a)(b)", "((a)b)", "(?:a)", "(?:a)(b)", "()", "(?:)", "(a)?", "(a)*",
          "(a*)*", "(a?)*", "(a|)*", "(?:a*)*", "(?:a?)+", "(a*)+", "((a)|b)*", "(?:(a)|b)*",
          "(?:(a)|(b))*", "(a)|(b)", "(a(b)?)+", "((a)|(b))+", "(a*?)*", "(a??)+?",
          "(?:(a)|b)*?b", "(a|b)*?b", "((a)*)*", "(a{0})", "(a){0}", "(){2}", "(a?){3}",
          "(a*){2,}", "(a|)+?b", "(?:()|a)*"]


@pytest.mark.parametrize("pattern", LITERALS)
def test_literals(pattern: str) -> None:
    check(pattern)


@pytest.mark.parametrize("pattern", ESCAPES)
def test_escapes(pattern: str) -> None:
    check(pattern, TEXTS + [".*+?()[]{}|^$-/\\ ,é", "\x07\x00\n"])


@pytest.mark.parametrize("pattern", CLASSES)
def test_classes(pattern: str) -> None:
    check(pattern, TEXTS + ["٣", "é", "\x1c", "\xa0"])


@pytest.mark.parametrize("pattern", SETS)
def test_sets(pattern: str) -> None:
    check(pattern, TEXTS + ["-", "^", "\x08", "B", "/", ".", "*"])


@pytest.mark.parametrize("pattern", ANCHORS)
def test_anchors(pattern: str) -> None:
    check(pattern, TEXTS + ["\n", "\n\n", "a\n\n", " a "])


@pytest.mark.parametrize("pattern", QUANTS)
def test_quantifiers(pattern: str) -> None:
    check(pattern)


@pytest.mark.parametrize("pattern", ALTERNATION)
def test_alternation(pattern: str) -> None:
    check(pattern, TEXTS + ["abcd", "abc", "xay", "xy"])


@pytest.mark.parametrize("pattern", GROUPS)
def test_groups(pattern: str) -> None:
    check(pattern)


@pytest.mark.parametrize(
    ("pattern", "text", "groups"),
    [
        (r"(?:(a)|b)*", "ab", ("a",)),
        (r"(a?)*", "b", ("",)),
        (r"(a|)*", "aa", ("",)),
        (r"(a)*", "aaa", ("a",)),
        (r"((a)|(b))*", "ab", ("b", "a", "b")),
        (r"(?:(a)|(b))*", "ba", ("a", "b")),
    ],
)
def test_capture_semantics(pattern: str, text: str, groups: tuple) -> None:
    assert miniregex.compile(pattern).match(text).groups() == groups
    assert re.match(pattern, text).groups() == groups


def test_dot_excludes_newline() -> None:
    assert miniregex.compile(".").match("\n") is None
    assert miniregex.compile(".").match("x").group() == "x"


def test_dollar_before_final_newline() -> None:
    p = miniregex.compile("a$")
    assert p.search("a\n").span() == (0, 1)
    assert p.search("a\n\n") is None


def test_lazy_vs_greedy() -> None:
    assert miniregex.compile("a+?").match("aaa").group() == "a"
    assert miniregex.compile("a+").match("aaa").group() == "aaa"
    assert miniregex.compile("<.*?>").search("<a><b>").group() == "<a>"


def test_leftmost_not_longest() -> None:
    assert miniregex.compile("a|ab").search("ab").group() == "a"
