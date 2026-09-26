"""Per-feature unit tests. Every expectation is also cross-checked against re."""

import re

import pytest

from miniregex import compile


def same_as_re(pattern, text):
    """Assert match/search/fullmatch/findall agree with re, then return re's match."""
    rp = re.compile(pattern)
    mp = compile(pattern)
    for op in ("match", "search", "fullmatch"):
        a = getattr(rp, op)(text)
        b = getattr(mp, op)(text)
        if a is None:
            assert b is None, (op, pattern, text)
        else:
            assert b is not None, (op, pattern, text)
            assert b.span() == a.span(), (op, pattern, text)
            assert b.groups() == a.groups(), (op, pattern, text)
            for i in range(1, rp.groups + 1):
                assert b.span(i) == a.span(i), (op, pattern, text, i)
    assert mp.findall(text) == rp.findall(text), (pattern, text)
    return mp.match(text)


# -- literals, dot, escapes -------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "text", "expected"),
    [
        ("abc", "abc", (0, 3)),
        ("abc", "abd", None),
        ("", "", (0, 0)),
        ("", "abc", (0, 0)),
        (".", "a", (0, 1)),
        (".", "\n", None),
        ("a.c", "abc", (0, 3)),
        ("a.c", "a\nc", None),
        (r"\.", ".", (0, 1)),
        (r"\.", "a", None),
        (r"\\", "\\", (0, 1)),
        (r"\*\+\?\(\)\[\]\{\}\|\^\$\-", "*+?()[]{}|^$-", (0, 13)),
        (r"\n\t", "\n\t", (0, 2)),
        (r"\r\f\v\a", "\r\f\v\a", (0, 4)),
        ("a\nb", "a\nb", (0, 3)),
    ],
)
def test_literals_and_escapes(pattern, text, expected):
    m = same_as_re(pattern, text)
    assert (None if m is None else m.span()) == expected


@pytest.mark.parametrize(
    ("cls", "yes", "no"),
    [
        (r"\d", "0123456789", "a_ \n"),
        (r"\D", "a_ \n", "0123456789"),
        (r"\w", "azAZ09_", " \n-."),
        (r"\W", " \n-.", "azAZ09_"),
        (r"\s", " \t\n\r\f\v", "a0_"),
        (r"\S", "a0_", " \t\n\r\f\v"),
    ],
)
def test_character_classes(cls, yes, no):
    p = compile(cls)
    for ch in yes:
        assert p.fullmatch(ch) is not None, (cls, ch)
        assert re.fullmatch(cls, ch) is not None
    for ch in no:
        assert p.fullmatch(ch) is None, (cls, ch)
        assert re.fullmatch(cls, ch) is None


# -- sets --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "yes", "no"),
    [
        ("[abc]", "abc", "dA"),
        ("[^abc]", "dA\n", "abc"),
        ("[a-c]", "abc", "dA"),
        ("[a-cx-z]", "abcxyz", "dw"),
        ("[a-]", "a-", "b"),
        ("[-a]", "a-", "b"),
        ("[]a]", "]a", "b"),
        ("[^]a]", "b", "]a"),
        ("[]-a]", "]^_`a", "b"),
        ("[--/]", "-./", "0a"),
        ("[a-b-c]", "abc-", "d"),
        (r"[\d]", "5", "a"),
        (r"[\dx]", "5x", "a"),
        (r"[^\d]", "a", "5"),
        (r"[\w\s]", "a_ ", "-"),
        (r"[\S]", "a", " "),
        (r"[\]]", "]", "a"),
        (r"[\[]", "[", "a"),
        (r"[\\]", "\\", "a"),
        (r"[\^]", "^", "a"),
        (r"[a\-c]", "a-c", "b"),
        (r"[.]", ".", "a"),
        (r"[$^]", "$^", "a"),
        (r"[\n]", "\n", "n"),
        ("[a-a]", "a", "b"),
    ],
)
def test_sets(pattern, yes, no):
    p = compile(pattern)
    for ch in yes:
        assert re.fullmatch(pattern, ch) is not None, (pattern, ch)
        assert p.fullmatch(ch) is not None, (pattern, ch)
    for ch in no:
        assert re.fullmatch(pattern, ch) is None, (pattern, ch)
        assert p.fullmatch(ch) is None, (pattern, ch)


# -- anchors -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "text"),
    [
        ("^a", "a"),
        ("^a", "ba"),
        ("a$", "a"),
        ("a$", "a\n"),
        ("a$", "a\n\n"),
        ("a$", "ab"),
        ("^$", ""),
        ("^$", "\n"),
        ("^$", "\n\n"),
        ("$", "a\n"),
        ("^", "abc"),
        ("a^b", "ab"),
        ("a$b", "a\nb"),
        ("^a|b$", "b"),
        ("(^a|b)+", "abab"),
        ("(?:$)+", "a"),
        ("(?:^)*b", "b"),
    ],
)
def test_anchors(pattern, text):
    same_as_re(pattern, text)


def test_dollar_before_trailing_newline_only():
    assert compile("a$").search("a\n").span() == (0, 1)
    assert compile("$").findall("a\n") == ["", ""]
    assert compile("a$").search("a\nb") is None


# -- quantifiers -------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "text"),
    [
        ("a*", "aaa"),
        ("a*", "baaa"),
        ("a+", "aaa"),
        ("a+", "b"),
        ("a?", "aa"),
        ("a?b", "b"),
        ("a{2}", "aaa"),
        ("a{2,}", "aaaa"),
        ("a{2,3}", "aaaa"),
        ("a{,3}", "aaaa"),
        ("a{,}", "aaaa"),
        ("a{0}", "aaa"),
        ("a{0}b", "b"),
        ("a*?", "aaa"),
        ("a+?", "aaa"),
        ("a??", "aa"),
        ("a{2,3}?", "aaaa"),
        ("a{,3}?", "aaaa"),
        ("a{2,}?", "aaaa"),
        ("a*?b", "aaab"),
        ("a*b", "aaab"),
        ("a*?$", "aaa"),
        ("a{2,3}?a", "aaaa"),
        (".*", "ab\ncd"),
        (".*?\n", "ab\ncd"),
        ("[ab]{2,3}", "abab"),
        (r"\d+", "12ab34"),
        ("(ab)*", "ababab"),
        ("(ab)+?", "ababab"),
        ("(ab){2}", "ababab"),
        ("(?:ab){1,2}?b", "ababb"),
        ("x{", "x{"),
        ("x{x}", "x{x}"),
        ("x{}", "x{}"),
        ("x{1,2", "x{1,2"),
    ],
)
def test_quantifiers(pattern, text):
    same_as_re(pattern, text)


def test_greedy_vs_lazy_spans():
    assert compile("a+").match("aaa").span() == (0, 3)
    assert compile("a+?").match("aaa").span() == (0, 1)
    assert compile("a{2,3}").match("aaaa").span() == (0, 3)
    assert compile("a{2,3}?").match("aaaa").span() == (0, 2)
    assert compile("<.+>").match("<a><b>").span() == (0, 6)
    assert compile("<.+?>").match("<a><b>").span() == (0, 3)


# -- alternation and groups ----------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "text"),
    [
        ("a|b", "b"),
        ("a|ab", "ab"),
        ("ab|a", "ab"),
        ("a||b", "b"),
        ("a||b", ""),
        ("|a", "a"),
        ("(a|ab)(c|bcd)(d*)", "abcd"),
        ("(a|b)*c", "abbac"),
        ("(?:a|b)*c", "abbac"),
        ("((a)|(b))+", "ab"),
        ("(a)(b)(c)", "abc"),
        ("((a)(b))", "ab"),
        ("(a)?(b)?", "b"),
        ("(?:(a)|(b))*", "ab"),
        ("(a|b|c)+", "cab"),
        ("()", "x"),
        ("(|a)", "a"),
        ("(a|)", "a"),
        ("(?:)", "x"),
        ("(?:a)", "a"),
        ("x(a|b)?y", "xy"),
    ],
)
def test_alternation_and_groups(pattern, text):
    same_as_re(pattern, text)


def test_leftmost_first_alternation():
    # Unlike POSIX leftmost-longest, the first alternative that leads to an
    # overall match wins.
    assert compile("a|ab").match("ab").span() == (0, 1)
    assert compile("(a|ab)(c|bcd)(d*)").match("abcd").groups() == ("a", "bcd", "")


def test_group_numbering_is_by_open_paren():
    m = compile("((a)(b))((c))").match("abc")
    assert m.groups() == ("ab", "a", "b", "c", "c")
    assert compile("((a)(b))((c))").groups == 5
