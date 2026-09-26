"""Random pattern/text generators shared by the fuzz tests."""

from __future__ import annotations

import random

ALPHABET = "abc\n-"
ESCAPES = [r"\d", r"\D", r"\w", r"\W", r"\s", r"\S", r"\.", r"\-", r"\n"]


def gen_set(rng: random.Random) -> str:
    parts = []
    if rng.random() < 0.2:
        parts.append("]")
    for _ in range(rng.randint(1, 3)):
        r = rng.random()
        if r < 0.3:
            lo, hi = sorted(rng.sample("abcd", 2))
            parts.append(f"{lo}-{hi}")
        elif r < 0.5:
            parts.append(rng.choice([r"\d", r"\w", r"\s", r"\W", r"\-", r"\]", r"\\"]))
        else:
            parts.append(rng.choice("abc1 "))
    if rng.random() < 0.15:
        parts.append("-")
    neg = "^" if rng.random() < 0.3 else ""
    return "[" + neg + "".join(parts) + "]"


UNBOUNDED = ["*", "+", "{1,}", "{2,}", "{,}"]
BOUNDED = ["?", "{2}", "{0,2}", "{,2}", "{1,3}", "{0}", "{1}"]


def gen_quant(rng: random.Random, budget: list[int]) -> str:
    # Nested unbounded repeats can take exponential time (in re as well), so
    # each pattern gets a small budget of them.
    if budget[0] > 0 and rng.random() < 0.5:
        budget[0] -= 1
        q = rng.choice(UNBOUNDED)
    else:
        q = rng.choice(BOUNDED)
    if rng.random() < 0.35:
        q += "?"
    return q


def gen_atom(rng: random.Random, depth: int, budget: list[int]) -> str:
    r = rng.random()
    if depth > 0 and r < 0.3:
        inner = gen_alt(rng, depth - 1, budget)
        return ("(?:" if rng.random() < 0.3 else "(") + inner + ")"
    if r < 0.55:
        return rng.choice("abc")
    if r < 0.63:
        return "."
    if r < 0.73:
        return gen_set(rng)
    if r < 0.8:
        return rng.choice(ESCAPES)
    if r < 0.86:
        return rng.choice("^$")
    return rng.choice("ab")


def gen_seq(rng: random.Random, depth: int, budget: list[int]) -> str:
    out = []
    for _ in range(rng.randint(0, 3)):
        atom = gen_atom(rng, depth, budget)
        if atom not in ("^", "$") and rng.random() < 0.4:
            atom += gen_quant(rng, budget)
        out.append(atom)
    return "".join(out)


def gen_alt(rng: random.Random, depth: int, budget: list[int]) -> str:
    branches = [gen_seq(rng, depth, budget)]
    while rng.random() < 0.3:
        branches.append(gen_seq(rng, depth, budget))
    return "|".join(branches)


def gen_pattern(rng: random.Random) -> str:
    return gen_alt(rng, 3, [3])


def gen_text(rng: random.Random) -> str:
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 8)))
