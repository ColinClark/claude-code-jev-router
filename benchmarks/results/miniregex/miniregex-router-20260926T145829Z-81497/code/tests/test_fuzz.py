"""Differential fuzzing against Python's re module."""

import random

import pytest
from helpers import assert_same

TEXT_ALPHABET = "aab b-c\n1_x."


def random_text(rng, max_len=8):
    return "".join(rng.choice(TEXT_ALPHABET) for _ in range(rng.randint(0, max_len)))


def texts_for(rng, count=12):
    texts = {"", "a", "ab", "aaa", "a\n", "abab", "ba-1_"}
    while len(texts) < count:
        texts.add(random_text(rng))
    return sorted(texts)


# --- structured generator: always produces supported syntax -----------------

ATOMS = ["a", "b", "c", ".", "\\d", "\\w", "\\s", "\\D", "\\W", "\\S", "\\.", "-", "x", "\\n"]
SETS = ["[ab]", "[^a]", "[a-c]", "[-a]", "[a-]", "[]a]", "[^]b]", "[\\d_]", "[\\W\\n]", "[.b]"]
QUANTS = ["*", "+", "?", "*?", "+?", "??", "{2}", "{1,2}", "{0,}", "{,2}", "{2,}?", "{0,1}?", "{0}"]


def gen_regex(rng, depth=0):
    choice = rng.random()
    if depth > 3 or choice < 0.35:
        r = rng.random()
        if r < 0.65:
            return rng.choice(ATOMS)
        if r < 0.85:
            return rng.choice(SETS)
        return rng.choice(["^", "$"])
    if choice < 0.55:
        return "".join(gen_regex(rng, depth + 1) for _ in range(rng.randint(2, 3)))
    if choice < 0.7:
        return "|".join(gen_regex(rng, depth + 1) for _ in range(rng.randint(2, 3)))
    if choice < 0.85:
        inner = gen_regex(rng, depth + 1) if rng.random() < 0.9 else ""
        return rng.choice(["(", "(?:"]) + inner + ")"
    body = gen_regex(rng, depth + 1)
    if body in ("^", "$") or body[-1:] in "*+?}" and not body.endswith("\\?"):
        body = "(" + body + ")"
    return body + rng.choice(QUANTS)


@pytest.mark.parametrize("seed", range(40))
def test_fuzz_structured(seed):
    rng = random.Random(seed)
    for _ in range(60):
        pattern = gen_regex(rng)
        assert_same(pattern, texts_for(rng))


# --- token soup: exercises error handling and odd corners --------------------

TOKENS = [
    "a", "b", ".", "\\d", "\\w", "\\s", "(", "(?:", ")", "|", "^", "$", "[", "]", "[^", "-",
    "{", "}", ",", "1", "2", "\\-", "\\[", "\\]", "\\{", "\\}", "\\|", "\\^", "\\$",
]
QUANT_TOKENS = ["*", "+", "?", "*?", "+?", "{1}", "{1,2}", "{,1}", "{2,1}", "{0,}"]


def gen_soup(rng):
    out = []
    prev_quant = False
    for _ in range(rng.randint(1, 9)):
        if rng.random() < 0.3:
            tok = rng.choice(QUANT_TOKENS)
            if prev_quant and tok.startswith("+"):
                tok = "?"
            prev_quant = True
        else:
            tok = rng.choice(TOKENS)
            prev_quant = False
        out.append(tok)
    return "".join(out)


@pytest.mark.parametrize("seed", range(25))
def test_fuzz_soup(seed):
    rng = random.Random(1000 + seed)
    for _ in range(120):
        pattern = gen_soup(rng)
        assert_same(pattern, texts_for(rng, 8))


# --- nested repetition / capture stress -----------------------------------

GROUPY = [
    "(a|ab)(c|bcd)(d*)",
    "(a*)*",
    "(a*)+",
    "(a|b)*",
    "(a|)*b",
    "((a)|b)*",
    "(?:(a)|b)*",
    "(?:(a)|(b))*",
    "(?:(a)|(b))+?c",
    "((a)|(b))*?b",
    "(a*?)*?b",
    "(a?)*?$",
    "(?:a|(b))*a",
    "((a*)b)*",
    "(()|a)*",
    "(a(b)?)+",
    "(a(b)?)+?$",
    "(?:(a)|b|(c))*",
    "(?:()|a)*b",
    "(a)?(a)?(a)?a",
    "(?:(a)(b)?|(a))*",
    "((a)|(ab))*c",
    "(?:x*(a)|x*(b))*",
    "(a{0,2}?){2,3}",
    "(a|b){2,}?a",
    "(?:(a)|ab)*?b",
    "(?:)*",
    "()*",
    "(?:a*)*b",
    "(|a)+b",
    "(a|b|)+?$",
]


@pytest.mark.parametrize("pattern", GROUPY)
def test_group_semantics(pattern):
    rng = random.Random(pattern)
    texts = texts_for(rng, 10) + ["abab", "aab", "abcd", "abcbcd", "aaab", "bbb", "abac", "xaxb"]
    assert_same(pattern, texts)
