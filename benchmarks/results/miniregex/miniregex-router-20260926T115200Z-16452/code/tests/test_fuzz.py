"""Deterministic differential fuzzing against the standard library's re.

A seeded generator produces random patterns over the supported grammar
(literals, ``.``, anchors, sets, class escapes, all quantifier forms including
lazy ones and brace literals, nested capturing / non-capturing groups,
alternation with empty branches) and random ASCII texts.  For every pair the
results of fullmatch / match / search (presence, span, groups, group spans,
lastindex) and findall / finditer must be identical to re's.

Patterns that re rejects are kept: miniregex must reject them too.

Texts are ASCII so re's Unicode classes agree with miniregex's ASCII ones.
Possessive quantifiers (``*+`` ...) are outside the supported grammar and the
generator never produces them.

The seeds and counts below are fixed on purpose: the grammar can produce
patterns with catastrophic backtracking (re itself needs seconds of C-level
work on some of them, and miniregex mirrors that at Python speed), so changing
seeds may need a check that the run time stays reasonable.
"""

from __future__ import annotations

import random

import pytest
from _support import assert_same

ATOM_LITERALS = "ab"
SET_ATOMS = [
    "[ab]",
    "[^a]",
    "[a-b]",
    "[\\d]",
    "[]a]",
    "[a-]",
    "[-a]",
    "[^]a]",
    "[\\w]",
    "[\\S]",
    "[b-]",
    "[^b]",
    "[^\\d]",
    "[\\n]",
    "[a\\-b]",
    "[--a]",
    "[.]",
]
ESCAPE_ATOMS = [
    "\\d",
    "\\w",
    "\\s",
    "\\D",
    "\\W",
    "\\S",
    "\\.",
    "\\*",
    "\\n",
    "\\-",
    "\\(",
    "\\|",
    "\\$",
    "\\^",
]
QUANTIFIERS = [
    "*",
    "+",
    "?",
    "{2}",
    "{1,}",
    "{,2}",
    "{1,2}",
    "{0}",
    "{0,1}",
    "{2,3}",
    "{,}",
    "{0,}",
    "{3}",
    # brace literals (not quantifiers in re)
    "{",
    "{x}",
    "{1,x}",
    "{}",
    "{,x}",
    # invalid: min greater than max
    "{2,1}",
]
TEXT_EXTRAS = "aab\n1_ ."


def gen_pattern(rng: random.Random, depth: int = 0) -> str:
    def atom() -> str:
        r = rng.random()
        if r < 0.36:
            return rng.choice(ATOM_LITERALS)
        if r < 0.43:
            return "."
        if r < 0.48:
            return rng.choice(["^", "$"])
        if r < 0.58:
            return rng.choice(SET_ATOMS)
        if r < 0.65:
            return rng.choice(ESCAPE_ATOMS)
        if depth < 3:
            opener = "(" if rng.random() < 0.6 else "(?:"
            return opener + gen_pattern(rng, depth + 1) + ")"
        return "a"

    def quantifier() -> str:
        if rng.random() < 0.5:
            return ""
        q = rng.choice(QUANTIFIERS)
        if rng.random() < 0.3:
            q += "?"
        return q

    def sequence() -> str:
        n = rng.choice([0, 1, 1, 2, 2, 3])
        return "".join(atom() + quantifier() for _ in range(n))

    nalts = rng.choice([1, 1, 1, 2, 2, 3])
    return "|".join(sequence() for _ in range(nalts))


def gen_text(rng: random.Random) -> str:
    n = rng.randint(0, 8)
    return "".join(
        rng.choice(TEXT_EXTRAS) if rng.random() < 0.15 else rng.choice(ATOM_LITERALS)
        for _ in range(n)
    )


PATTERNS_PER_SEED = 400
TEXTS_PER_PATTERN = 3
SEEDS = list(range(10))  # 10 * 400 * 3 = 12000 pattern/text pairs


@pytest.mark.parametrize("seed", SEEDS)
def test_random_patterns_agree_with_re(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(PATTERNS_PER_SEED):
        pattern = gen_pattern(rng)
        for _ in range(TEXTS_PER_PATTERN):
            assert_same(pattern, gen_text(rng))


def test_generator_is_deterministic() -> None:
    a = [gen_pattern(random.Random(1)) for _ in range(3)]
    b = [gen_pattern(random.Random(1)) for _ in range(3)]
    assert a == b


@pytest.mark.parametrize("seed", [100, 101, 102])
def test_targeted_empty_loop_and_nested_repeat_fuzz(seed: int) -> None:
    """Focus on nested repeats of possibly-empty groups and alternations."""
    rng = random.Random(seed)
    inner_atoms = [
        "a",
        "b",
        "a?",
        "a*",
        "a*?",
        "a??",
        "(a)",
        "(a?)",
        "(a*)",
        "(|a)",
        "(a|)",
        "()",
        "(?:)",
        "(a|b)",
        "(?:(a)|b)",
        "(a|(b))",
        "[ab]?",
    ]
    quants = [
        "*",
        "+",
        "?",
        "*?",
        "+?",
        "??",
        "{2}",
        "{1,}",
        "{,2}",
        "{2,3}?",
        "{0}",
        "{1,2}?",
        "{2,}?",
    ]
    for _ in range(300):
        parts = []
        for _ in range(rng.choice([1, 2, 3])):
            body = "".join(rng.choice(inner_atoms) for _ in range(rng.choice([1, 1, 2])))
            group = ("(" if rng.random() < 0.7 else "(?:") + body + ")"
            parts.append(group + rng.choice(quants))
            if rng.random() < 0.2:
                parts.append(rng.choice(["a", "b", "$", "(b)"]))
        pattern = "".join(parts)
        if rng.random() < 0.15:
            pattern = "(" + pattern + ")" + rng.choice(quants)
        for _ in range(3):
            assert_same(pattern, gen_text(rng))
