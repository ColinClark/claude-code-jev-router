"""Randomised differential testing against ``re`` (seeded, so failures are reproducible)."""

import random
import re

import pytest
from compare import assert_same
from fuzzgen import random_pattern, random_text

import miniregex


@pytest.mark.parametrize("seed", range(20))
def test_random_patterns_match_re(seed):
    rng = random.Random(seed)
    for _ in range(250):
        pattern = random_pattern(rng, max_depth=2)
        re.compile(pattern)  # the generator only produces valid patterns
        for _ in range(4):
            assert_same(pattern, random_text(rng))


@pytest.mark.parametrize("seed", range(5))
def test_random_deeper_patterns_match_re(seed):
    rng = random.Random(1000 + seed)
    for _ in range(100):
        pattern = random_pattern(rng, max_depth=3)
        for _ in range(3):
            assert_same(pattern, random_text(rng, max_len=6))


SYNTAX_PIECES = list("ab()|*+?{}[]^$.-\\,:0123dwsDWS") + [
    "(?:",
    "{1,2}",
    "{,1}",
    "{2,}",
    r"\d",
    "[^",
    "*?",
    "a",
    "\n",
]
UNSUPPORTED = re.compile(r"\\[bBAZ0-9xuUNgpP]|[*+?}]\+|\(\?[^:]")


@pytest.mark.parametrize("seed", range(10))
def test_random_syntax_is_accepted_or_rejected_like_re(seed):
    """Random strings of syntax characters: same validity and same matches as ``re``."""
    rng = random.Random(seed)
    checked = 0
    while checked < 1500:
        pattern = "".join(rng.choice(SYNTAX_PIECES) for _ in range(rng.randint(0, 9)))
        if UNSUPPORTED.search(pattern):
            continue
        checked += 1
        try:
            with_re = re.compile(pattern)
        except re.error:
            with pytest.raises(miniregex.RegexError):
                miniregex.compile(pattern)
            continue
        assert miniregex.compile(pattern).groups == with_re.groups
        for text in ["", "a", "ab", "{1,2}", "a\n", "aab]", "1-2", "b\\a"]:
            assert_same(pattern, text)
