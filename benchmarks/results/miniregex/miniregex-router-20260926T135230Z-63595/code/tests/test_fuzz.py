"""Seeded differential fuzzing of miniregex against the ``re`` module."""

from __future__ import annotations

import random

import pytest
from fuzzgen import LOOPY_ATOMS, PatternGen, junk_pattern, random_text
from helpers import assert_same, re_compile

import miniregex

SEEDS = range(8)
CASES_PER_SEED = 1000


def _compile_ours(pattern: str) -> tuple[bool, str]:
    try:
        miniregex.compile(pattern)
    except miniregex.RegexError as exc:
        return False, str(exc)
    return True, ""


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_structured(seed: int) -> None:
    rng = random.Random(seed)
    gen = PatternGen(rng)
    checked = 0
    for _ in range(CASES_PER_SEED):
        pattern = gen.pattern()
        expected = re_compile(pattern)
        accepted, _msg = _compile_ours(pattern)
        if expected is None:
            assert not accepted, f"re rejects {pattern!r} but miniregex accepts it"
            continue
        assert accepted, f"re accepts {pattern!r} but miniregex rejects it"
        assert_same(pattern, [random_text(rng) for _ in range(4)])
        checked += 1
    assert checked > CASES_PER_SEED // 2


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_loops_and_groups(seed: int) -> None:
    """Small alphabet, many groups and quantifiers: stresses empty iterations."""
    rng = random.Random(500 + seed)
    gen = PatternGen(rng, LOOPY_ATOMS)
    checked = 0
    for _ in range(CASES_PER_SEED):
        pattern = gen.pattern()
        expected = re_compile(pattern)
        accepted, _msg = _compile_ours(pattern)
        if expected is None:
            assert not accepted, f"re rejects {pattern!r} but miniregex accepts it"
            continue
        assert accepted, f"re accepts {pattern!r} but miniregex rejects it"
        texts = ["".join(rng.choice("aab") for _ in range(rng.randint(0, 6))) for _ in range(3)]
        assert_same(pattern, texts + [random_text(rng)])
        checked += 1
    assert checked > CASES_PER_SEED // 3


@pytest.mark.parametrize("seed", SEEDS)
def test_fuzz_error_parity(seed: int) -> None:
    rng = random.Random(1000 + seed)
    for _ in range(CASES_PER_SEED):
        pattern = junk_pattern(rng)
        expected = re_compile(pattern)
        accepted, msg = _compile_ours(pattern)
        if expected is None:
            assert not accepted, f"re rejects {pattern!r} but miniregex accepts it"
        elif not accepted:
            # Only syntax miniregex deliberately does not support may differ.
            assert "possessive" in msg or "unsupported" in msg, (pattern, msg)
        else:
            assert_same(pattern, [random_text(rng) for _ in range(3)])
