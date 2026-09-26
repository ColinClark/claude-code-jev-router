"""Differential fuzzing against re with random patterns and texts."""

import random
import re

import pytest
from _gen import gen_pattern, gen_text
from helpers import assert_same

from miniregex import RegexError, compile


@pytest.mark.parametrize("seed", range(20))
def test_random_patterns(seed):
    rng = random.Random(seed)
    for _ in range(400):
        pattern = gen_pattern(rng)
        for _ in range(5):
            assert_same(pattern, gen_text(rng))


JUNK = list("ab()[]|*+?{}^$.-,:\\12") + ["(?:", r"\d", r"\w", "{1,2}", "{,3}", r"\]"]


@pytest.mark.filterwarnings("ignore::FutureWarning")
@pytest.mark.parametrize("seed", range(5))
def test_random_junk_accepted_iff_re_accepts(seed):
    rng = random.Random(1000 + seed)
    for _ in range(2000):
        pattern = "".join(rng.choice(JUNK) for _ in range(rng.randint(1, 8)))
        try:
            re.compile(pattern)
        except re.error:
            with pytest.raises(RegexError):
                compile(pattern)
            continue
        try:
            compile(pattern)
        except RegexError as exc:
            # Only constructs outside the supported syntax may be rejected.
            assert "unsupported" in str(exc), (pattern, exc)
            continue
        for text in ["", "ab", "a-b]", "{1,2}", "ab\n", "(a|b)"]:
            assert_same(pattern, text)
