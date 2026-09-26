"""Hand-picked patterns compared against ``re`` (every method, every group)."""

from __future__ import annotations

import pytest
from fuzzgen import assert_same

CASES = [
    # literals, dot, escapes
    ("abc", ["abc", "xabcx", "ab", ""]),
    ("a.c", ["abc", "a\nc", "ac", "a.c"]),
    (r"a\.c", ["a.c", "abc"]),
    (r"\\\*\+\?\(\)\[\]\{\}\|\^\$\-", ["\\*+?()[]{}|^$-"]),
    (r"\d+\D\w\W\s\S", ["12a_ !x", "1a_ !", "99-x y."]),
    (r"\n\t", ["\n\t", "a\n\tb"]),
    # character sets
    ("[abc]+", ["xxcabz", ""]),
    ("[^abc]+", ["abxyzc", "abc"]),
    ("[a-cx-z]+", ["abyzq", "dq"]),
    ("[-a]+", ["-a-b"]),
    ("[a-]+", ["-a-b"]),
    ("[]a]+", ["]a]b"]),
    ("[^]a]+", ["]a]bc"]),
    (r"[\d\s]+", ["a1 2\tb"]),
    (r"[^\w]+", ["ab!@ c"]),
    (r"[\]\-\\]+", ["a]-\\b"]),
    ("[.]", ["a.", "ab"]),
    ("[--/]+", ["a-./b"]),
    # anchors
    ("^ab", ["ab", "cab"]),
    ("ab$", ["ab", "ab\n", "ab\n\n", "abc"]),
    ("^$", ["", "\n", "a"]),
    ("$", ["abc\n", ""]),
    ("a|^b", ["cb", "bc"]),
    ("(?:^)*a", ["a", "ba"]),
    # quantifiers
    ("a*", ["", "aaa", "baaa"]),
    ("a+", ["baaab", "b"]),
    ("a?b", ["ab", "b", "aab"]),
    ("a{2}", ["a", "aaa"]),
    ("a{2,}", ["a", "aaaaa"]),
    ("a{1,3}", ["aaaaa"]),
    ("a{,2}", ["aaa"]),
    ("a{,}", ["aaa"]),
    ("a{0}b", ["ab", "b"]),
    ("a*?b", ["aaab"]),
    ("a+?", ["aaa"]),
    ("a??b", ["ab"]),
    ("a{2,3}?", ["aaaa"]),
    ("a{2,}?", ["aaaa"]),
    ("a{,3}?b", ["aab"]),
    ("<.*>", ["<a><b>"]),
    ("<.*?>", ["<a><b>"]),
    # literal braces
    ("a{", ["a{"]),
    ("a{}", ["a{}"]),
    ("a{1", ["a{1"]),
    ("a{1,2", ["a{1,2"]),
    ("a{x}", ["a{x}"]),
    ("{", ["{"]),
    ("x{ 1}", ["x{ 1}"]),
    ("}", ["}"]),
    ("]", ["]"]),
    # alternation and groups
    ("cat|dog", ["hotdog", "cat"]),
    ("a|ab", ["ab"]),
    ("ab|a", ["ab"]),
    ("|a", ["a"]),
    ("a||b", ["b"]),
    ("(a)(b)?", ["a", "ab"]),
    ("(a)|(b)", ["b", "a"]),
    ("(?:ab)+", ["ababa"]),
    ("((a)(b))", ["ab"]),
    ("(a(b(c)))", ["abc"]),
    ("()", ["", "x"]),
    ("(|a)+", ["aa"]),
    ("(a|b)*c", ["abac", "abab"]),
    # groups inside repetitions keep the last iteration
    ("(a|b)*", ["abba"]),
    ("(a)*", ["aaa", ""]),
    ("(?:(a)|b)*", ["ab", "ba"]),
    ("(?:(a)|(b))+", ["ab", "ba", "aab"]),
    ("(a*)*", ["aaa", "b"]),
    ("(a*)+", ["aaa", "b"]),
    ("(a*?)*", ["aa"]),
    ("(a|)*", ["aa"]),
    ("(|a)*", ["aa"]),
    ("(a?)*?b", ["aab"]),
    ("(a*)*b", ["aab"]),
    ("(a{0,2}){2,}", ["aaaaa"]),
    ("(?:(a)|b|)*c", ["abc", "bac"]),
    ("(a)*?b", ["aab"]),
    ("((a)|b)+", ["ab", "ba"]),
    ("(x)?(?:(a)|(b))*", ["xab", "ab"]),
    ("(?:a(b)?)+", ["aba", "aab"]),
    ("(.)*x", ["abcx"]),
    ("(a+|b+)*c", ["aabbac"]),
    ("(a|ab)(c|bcd)(d*)", ["abcd"]),
    ("((a)|b)*?c", ["abac"]),
    ("(a*)(b)?(b+)?", ["aabbb"]),
    ("(?:(a)|(a))*b", ["aab"]),
    # backtracking into groups
    ("(a+)(a+)", ["aaaa"]),
    ("(a+?)(a+)", ["aaaa"]),
    ("(.*)(\\d+)", ["abc123"]),
    ("(.*?)(\\d+)", ["abc123"]),
    ("^(\\w+)\\s*=\\s*(\\w*)$", ["key = value", "key=", "k = v\n"]),
]


@pytest.mark.parametrize(
    ("pattern", "text"),
    [(p, t) for p, texts in CASES for t in texts],
)
def test_matches_re(pattern: str, text: str) -> None:
    assert_same(pattern, text)
