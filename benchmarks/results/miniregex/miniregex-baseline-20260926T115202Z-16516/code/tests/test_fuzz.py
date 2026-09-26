"""Differential fuzzing against ``re`` with fixed seeds (deterministic)."""

from __future__ import annotations

import random
import re
import warnings

import pytest
from fuzzgen import assert_same, compile_both, random_pattern, random_text

import miniregex


@pytest.mark.parametrize("seed", range(20))
def test_random_patterns_match_re(seed: int) -> None:
    rng = random.Random(seed)
    checked = 0
    for _ in range(300):
        pattern = random_pattern(rng)
        expected, actual = compile_both(pattern)
        assert expected is not None, pattern
        for _ in range(5):
            assert_same(pattern, random_text(rng), expected, actual)
            checked += 1
    assert checked == 1500


_SOUP = "ab()[]{}|*+?^$.\\-,:0123dwsn"
# Valid re syntax that miniregex intentionally does not support.
_UNSUPPORTED = re.compile(r"\\[0-9b]|\(\?[^:]|\?\+|[*+?}]\+")


@pytest.mark.parametrize("seed", range(10))
def test_random_syntax_is_accepted_or_rejected_like_re(seed: int) -> None:
    rng = random.Random(1000 + seed)
    for _ in range(3000):
        pattern = "".join(rng.choice(_SOUP) for _ in range(rng.randint(0, 7)))
        if _UNSUPPORTED.search(pattern):
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                re.compile(pattern)
                valid = True
            except re.error:
                valid = False
        if valid:
            miniregex.compile(pattern)
            for _ in range(2):
                assert_same(pattern, random_text(rng, 6))
        else:
            with pytest.raises(miniregex.RegexError):
                miniregex.compile(pattern)
