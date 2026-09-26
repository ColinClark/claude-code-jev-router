"""Randomized differential tests against the standard ``re`` module."""

from __future__ import annotations

import random
import re
import time

import pytest
from helpers import assert_same, random_pattern, random_text, re_compile

import miniregex

SEEDS = range(40)
PATTERNS_PER_SEED = 250
TEXTS_PER_PATTERN = 5


def _re_is_fast(pattern: str, texts: list[str]) -> bool:
    """Skip pathological (exponential) cases; they are slow in any backtracking engine."""
    compiled = re_compile(pattern)
    start = time.perf_counter()
    for text in texts:
        compiled.search(text)
        compiled.fullmatch(text)
        compiled.findall(text)
    return time.perf_counter() - start < 0.002


@pytest.mark.parametrize("seed", SEEDS)
def test_random_patterns_match_re(seed):
    rng = random.Random(seed)
    checked = 0
    for _ in range(PATTERNS_PER_SEED):
        pattern = random_pattern(rng)
        texts = [random_text(rng) for _ in range(TEXTS_PER_PATTERN)]
        if not _re_is_fast(pattern, texts):
            continue
        for text in texts:
            assert_same(pattern, text)
        checked += 1
    assert checked >= PATTERNS_PER_SEED // 2


SYNTAX_ALPHABET = list("ab.()[]{}*+?|^$-,\\") + ["1", "2", "d", "w", "s", "]", "^", "(?:"]


@pytest.mark.parametrize("seed", range(20))
def test_random_syntax_is_accepted_or_rejected_like_re(seed):
    """Random strings of metacharacters: reject exactly what ``re`` rejects."""
    rng = random.Random(1000 + seed)
    for _ in range(300):
        pattern = "".join(rng.choice(SYNTAX_ALPHABET) for _ in range(rng.randint(1, 8)))
        try:
            re_compile(pattern)
        except (re.error, OverflowError):
            with pytest.raises(miniregex.RegexError):
                miniregex.compile(pattern)
            continue
        try:
            miniregex.compile(pattern)
        except miniregex.RegexError as exc:
            # re accepts some features that miniregex deliberately does not support
            assert "not supported" in str(exc), (pattern, str(exc))
            continue
        texts = [random_text(rng, 6) for _ in range(3)]
        if _re_is_fast(pattern, texts):
            for text in texts:
                assert_same(pattern, text)
