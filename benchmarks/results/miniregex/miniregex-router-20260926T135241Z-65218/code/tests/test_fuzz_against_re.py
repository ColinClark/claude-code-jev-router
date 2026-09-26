import random
import re

import pytest

from miniregex import compile

ATOMS = ["a", "b", ".", r"\d", r"\w", r"\s", "[ab]", "[^a]", "(a)", "(a|b)", "(?:ab)", "(b*)", "()"]
QUANTS = ["", "", "*", "+", "?", "*?", "+?", "??", "{2}", "{1,2}", "{1,}", "{,2}", "{1,2}?"]
TEXTS = ["", "a", "ab", "aab", "abab", "ba1 _b", "xyz", "aaa\n", "b a b", "1a2b3"]


def gen(rng):
    parts = [rng.choice(ATOMS) + rng.choice(QUANTS) for _ in range(rng.randint(1, 3))]
    p = "".join(parts)
    if rng.random() < 0.3:
        p = p + "|" + rng.choice(ATOMS)
    if rng.random() < 0.2:
        p = "^" + p
    if rng.random() < 0.2:
        p = p + "$"
    return p


rng = random.Random(1234)
CASES = [(gen(rng), t) for _ in range(150) for t in [rng.choice(TEXTS)]]


def summ(m, n):
    if m is None:
        return None
    return [m.span(i) for i in range(n + 1)] + [m.group(i) for i in range(n + 1)]


@pytest.mark.parametrize("p,t", CASES)
def test_agree(p, t):
    r = re.compile(p)
    mine = compile(p)
    n = r.groups
    for f in ("search", "match", "fullmatch"):
        assert summ(getattr(mine, f)(t), n) == summ(getattr(r, f)(t), n), f
    assert mine.findall(t) == r.findall(t)
