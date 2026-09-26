"""Deterministic, seeded differential fuzzing against Python's ``re``."""

from __future__ import annotations

import random
import re
import warnings

import pytest
from fuzzlib import (
    SYNTAX_TEXTS,
    Gen,
    compare,
    syntax_pattern,
    uses_unsupported,
)

import miniregex

GRAMMAR_CHUNKS = 40
GRAMMAR_SEEDS_PER_CHUNK = 1000  # 40,000 patterns x 4 texts = 160,000 cases
TEXTS_PER_PATTERN = 4


@pytest.mark.parametrize("chunk", range(GRAMMAR_CHUNKS))
def test_grammar_fuzz(chunk: int) -> None:
    cases = 0
    first = chunk * GRAMMAR_SEEDS_PER_CHUNK
    for seed in range(first, first + GRAMMAR_SEEDS_PER_CHUNK):
        gen = Gen(seed)
        pattern = gen.bounded_pattern()
        re.compile(pattern)  # the generator only produces valid patterns
        for _ in range(TEXTS_PER_PATTERN):
            compare(pattern, gen.text())
            cases += 1
    assert cases == GRAMMAR_SEEDS_PER_CHUNK * TEXTS_PER_PATTERN


SYNTAX_CHUNKS = 10
SYNTAX_PER_CHUNK = 1000


@pytest.mark.parametrize("chunk", range(SYNTAX_CHUNKS))
def test_syntax_fuzz(chunk: int) -> None:
    """Token-soup patterns: validity must agree with re, and so must results."""
    rng = random.Random(1000 + chunk)
    for _ in range(SYNTAX_PER_CHUNK):
        pattern = syntax_pattern(rng)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                re.compile(pattern)
                re_ok = True
            except re.error:
                re_ok = False
        try:
            miniregex.compile(pattern)
            mini_ok = True
        except miniregex.RegexError:
            mini_ok = False
        if not re_ok:
            assert not mini_ok, f"miniregex accepted invalid pattern {pattern!r}"
            continue
        if not mini_ok:
            assert uses_unsupported(pattern), f"miniregex rejected valid pattern {pattern!r}"
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for text in SYNTAX_TEXTS:
                compare(pattern, text)
