"""Randomized differential testing against the re module (deterministic seeds)."""

import random

import pytest
from helpers import PatternGenerator, assert_same

import miniregex


@pytest.mark.parametrize("block", range(20))
def test_random_patterns_match_re(block):
    for seed in range(block * 150, (block + 1) * 150):
        gen = PatternGenerator(seed)
        pattern = gen.small_pattern()
        for _ in range(4):
            assert_same(pattern, gen.text())


@pytest.mark.parametrize("seed", range(10))
def test_random_long_texts(seed):
    rng = random.Random(1000 + seed)
    patterns = [r"(a|b)*c", r"(\w+)\s", r"[ab]+?c", r"(a*)(b*)c?", r"(?:x|(ab))+", r"\d{2,3}"]
    for pattern in patterns:
        text = "".join(rng.choice("ab c1x2\n") for _ in range(rng.randint(50, 200)))
        assert_same(pattern, text)


@pytest.mark.filterwarnings("ignore::FutureWarning")
def test_random_garbage_patterns_error_like_re():
    import re

    rng = random.Random(7)
    alphabet = "ab()[]{}|*+?^$.\\-,0123dws:"
    for _ in range(3000):
        pattern = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8)))
        try:
            expected = re.compile(pattern)
        except re.error:
            expected = None
        if expected is None:
            with pytest.raises(miniregex.RegexError):
                miniregex.compile(pattern)
            continue
        try:
            miniregex.compile(pattern)
        except miniregex.RegexError:
            # only syntax outside the supported subset may be rejected
            assert "(?" in pattern or "\\" in pattern or "+" in pattern, pattern
            continue
        for text in ["", "a", "ab", "(a)", "b{1}", "a-b"]:
            assert_same(pattern, text)
