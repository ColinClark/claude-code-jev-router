"""Seeded random differential test against re.

The generator avoids nesting unbounded quantifiers over bodies that can
match empty or overlap heavily by limiting depth and string length, which
keeps both backtracking engines fast.
"""

import random

from ._compare import assert_same

ALPHABET = "ab-c1 \n"
ATOMS = ["a", "b", "c", ".", r"\d", r"\w", r"\s", r"\D", r"\W", r"\S", r"\-", r"\.",
         "[ab]", "[^a]", "[a-c]", r"[\d-]", "[-b]", "[]a]", "[^]b]", r"[\s1]"]
QUANTS = ["*", "+", "?", "{2}", "{1,2}", "{2,}", "{,2}", "{0,1}"]


def gen(rng, depth):
    parts = []
    for _ in range(rng.randint(1, 3)):
        r = rng.random()
        if depth > 0 and r < 0.3:
            inner = gen(rng, depth - 1)
            if rng.random() < 0.3:
                inner += "|" + gen(rng, depth - 1)
            atom = ("(" if rng.random() < 0.6 else "(?:") + inner + ")"
        elif r < 0.35:
            atom = rng.choice(["^", "$"])
            parts.append(atom)
            continue
        else:
            atom = rng.choice(ATOMS)
        if rng.random() < 0.45:
            atom += rng.choice(QUANTS)
            if rng.random() < 0.4:
                atom += "?"
        parts.append(atom)
    s = "".join(parts)
    if rng.random() < 0.15:
        s += "|" + "".join(rng.choice(ATOMS) for _ in range(rng.randint(0, 2)))
    return s


def test_fuzz():
    rng = random.Random(12345)
    count = 0
    for _ in range(1500):
        pattern = gen(rng, 2)
        for _ in range(4):
            text = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 8)))
            assert_same(pattern, text)
            count += 1
    assert count == 6000
