"""Generate random small patterns from a grammar and fuzz them against `re`."""

import random
import re

import pytest

import miniregex as mr

LITERALS = "ab"
CLASSES = [".", r"\d", r"\w", r"\s", "[ab]", "[^ab]", "[a-b]"]
QUANT_SUFFIXES = ["*", "+", "?", "{1,2}", "{0,2}", "{2}", "*?", "+?", "??"]
ALPHABET = "aabb01 \t\n"


def gen_atom(rng, depth):
    choice = rng.random()
    if depth <= 0 or choice < 0.35:
        return rng.choice(LITERALS)
    if choice < 0.55:
        return rng.choice(CLASSES)
    if choice < 0.75:
        inner = gen_concat(rng, depth - 1)
        return f"(?:{inner})"
    if choice < 0.9:
        inner = gen_concat(rng, depth - 1)
        return f"({inner})"
    branches = [gen_concat(rng, depth - 1) for _ in range(rng.randint(2, 3))]
    return "(" + "|".join(branches) + ")"


def gen_piece(rng, depth):
    atom = gen_atom(rng, depth)
    if rng.random() < 0.4:
        atom += rng.choice(QUANT_SUFFIXES)
    return atom


def gen_concat(rng, depth):
    return "".join(gen_piece(rng, depth) for _ in range(rng.randint(1, 3)))


def gen_pattern(rng, depth=3):
    return gen_concat(rng, depth)


def _random_text(rng, max_len=6):
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, max_len)))


def _compare(pattern, rng):
    try:
        re_pat = re.compile(pattern)
    except re.error:
        return None  # not something we're trying to reproduce error-for-error
    try:
        mini_pat = mr.compile(pattern)
    except mr.RegexError as exc:
        pytest.fail(f"miniregex rejected a pattern re accepted: {pattern!r}: {exc}")

    for _ in range(20):
        text = _random_text(rng)

        re_full = re_pat.fullmatch(text)
        mini_full = mini_pat.fullmatch(text)
        assert (re_full is None) == (mini_full is None), (pattern, text, "fullmatch")
        if re_full is not None:
            assert mini_full.span() == re_full.span(), (pattern, text, "fullmatch span")
            assert mini_full.groups() == re_full.groups(), (pattern, text, "fullmatch groups")

        re_s = re_pat.search(text)
        mini_s = mini_pat.search(text)
        assert (re_s is None) == (mini_s is None), (pattern, text, "search")
        if re_s is not None:
            assert mini_s.span() == re_s.span(), (pattern, text, "search span")
            assert mini_s.groups() == re_s.groups(), (pattern, text, "search groups")

        assert mini_pat.findall(text) == re_pat.findall(text), (pattern, text, "findall")


@pytest.mark.parametrize("seed", range(200))
def test_random_pattern(seed):
    rng = random.Random(seed)
    pattern = gen_pattern(rng)
    _compare(pattern, rng)
