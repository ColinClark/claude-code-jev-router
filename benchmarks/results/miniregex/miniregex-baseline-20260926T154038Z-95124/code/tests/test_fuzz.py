"""Differential fuzzing against Python's re module."""

import random
import re

import pytest
from fuzzgen import compare, random_pattern, random_text

_TOKENS = list("ab()|*+?{}[]^$.-,0123") + [
    "(?:",
    "{2}",
    "{1,2}",
    "{,2}",
    "[^",
    r"\d",
    r"\w",
    r"\s",
    r"\W",
    r"\.",
    r"\\",
    r"\n",
    r"\]",
    r"\-",
]


@pytest.mark.parametrize("chunk", range(20))
def test_structured_fuzz(chunk):
    for seed in range(chunk * 250, (chunk + 1) * 250):
        rng = random.Random(seed)
        pattern = random_pattern(rng)
        compare(pattern, [random_text(rng) for _ in range(6)])


@pytest.mark.parametrize("chunk", range(10))
def test_token_fuzz(chunk):
    """Random token soup: exercises parse errors and literal fallbacks too."""
    for seed in range(chunk * 500, (chunk + 1) * 500):
        rng = random.Random(seed)
        pattern = "".join(rng.choice(_TOKENS) for _ in range(rng.randint(1, 10)))
        # Possessive quantifiers are valid in re but outside the supported subset.
        if re.search(r"[*+?}]\+", pattern):
            continue
        compare(pattern, [random_text(rng) for _ in range(5)])
