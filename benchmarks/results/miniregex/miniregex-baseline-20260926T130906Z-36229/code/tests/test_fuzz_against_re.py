"""Fuzz miniregex against the stdlib `re` module (test-only use of `re`)."""

import random
import re

import pytest

import miniregex as mr

PATTERNS = [
    r"a",
    r"ab",
    r"a.b",
    r"a*",
    r"a+",
    r"a?",
    r"a*?",
    r"a+?",
    r"a??",
    r"a{2}",
    r"a{2,}",
    r"a{,2}",
    r"a{1,3}",
    r"a{1,3}?",
    r"(a|b)",
    r"(a|b)*",
    r"(ab|a)(c|bc)",
    r"(a|ab)(c|bcd)(d*)",
    r"a|",
    r"(a)?b",
    r"(a|b)+",
    r"(?:ab)+c",
    r"[abc]+",
    r"[^abc]+",
    r"[a-c]+",
    r"[a-c0-9]+",
    r"[-a]+",
    r"[a-]+",
    r"[]a]+",
    r"\d+\w*\s?",
    r"^abc",
    r"abc$",
    r"^abc$",
    r"a{2,4}b{1,2}?c*",
    r"(a+)(b+)?(c+)?",
    r"(a(b(c)?)?)?d",
    r"(a|aa|aaa)+",
    r"(a*)*",
    r"(a?)*b",
    r".*",
    r".+?",
    r"[\d\s]+",
    r"\D+\W+\S+",
]

ALPHABET = "aabbccdd012 \t\n"


def _random_text(rng, max_len=8):
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, max_len)))


@pytest.mark.parametrize("pattern", PATTERNS)
def test_fuzz_pattern(pattern):
    rng = random.Random(hash(pattern) & 0xFFFFFFFF)
    re_pat = re.compile(pattern)
    mini_pat = mr.compile(pattern)

    for _ in range(200):
        text = _random_text(rng)

        re_full = re_pat.fullmatch(text)
        mini_full = mini_pat.fullmatch(text)
        assert (re_full is None) == (mini_full is None), (pattern, text, "fullmatch presence")
        if re_full is not None:
            assert mini_full.span() == re_full.span()
            assert mini_full.groups() == re_full.groups()
            for i in range(1, (re_pat.groups) + 1):
                assert mini_full.span(i) == re_full.span(i), (pattern, text, i)

        re_m = re_pat.match(text)
        mini_m = mini_pat.match(text)
        assert (re_m is None) == (mini_m is None), (pattern, text, "match presence")
        if re_m is not None:
            assert mini_m.span() == re_m.span()
            assert mini_m.groups() == re_m.groups()

        re_s = re_pat.search(text)
        mini_s = mini_pat.search(text)
        assert (re_s is None) == (mini_s is None), (pattern, text, "search presence")
        if re_s is not None:
            assert mini_s.span() == re_s.span(), (pattern, text, "search span")
            assert mini_s.groups() == re_s.groups(), (pattern, text, "search groups")

        assert mini_pat.findall(text) == re_pat.findall(text), (pattern, text, "findall")
