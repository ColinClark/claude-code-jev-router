"""Shared helpers: compare miniregex against the standard ``re`` module."""

from __future__ import annotations

import random
import re
import warnings

import miniregex


def describe(m):
    """Everything observable about a match (or None)."""
    if m is None:
        return None
    ngroups = len(m.groups())
    return (
        m.group(),
        m.span(),
        m.groups(),
        tuple(m.span(i) for i in range(ngroups + 1)),
        tuple(m.start(i) for i in range(ngroups + 1)),
        tuple(m.end(i) for i in range(ngroups + 1)),
    )


def re_compile(pattern: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return re.compile(pattern)


def assert_same(pattern: str, text: str) -> None:
    expected = re_compile(pattern)
    actual = miniregex.compile(pattern)
    assert actual.groups == expected.groups, pattern
    for method in ("fullmatch", "match", "search"):
        exp = describe(getattr(expected, method)(text))
        got = describe(getattr(actual, method)(text))
        assert got == exp, f"{method}({pattern!r}, {text!r}): expected {exp}, got {got}"
    exp_all = expected.findall(text)
    got_all = actual.findall(text)
    assert got_all == exp_all, f"findall({pattern!r}, {text!r}): expected {exp_all}, got {got_all}"


# --- random pattern generator -------------------------------------------------------

ATOMS = ["a", "b", "c", ".", r"\d", r"\w", r"\s", r"\D", r"\W", r"\S", r"\.", "1", " "]
SETS = [
    "[ab]", "[^a]", "[a-c]", "[^a-b1]", r"[\d]", r"[\w-]", "[-a]", "[a-]", "[]a]",
    "[^]b]", r"[\s\d]", r"[^\w]", r"[.\]]", "[b-c1-2]",
]
QUANTS = [
    "*", "+", "?", "*?", "+?", "??", "{2}", "{1,2}", "{0,1}", "{2,}", "{,2}", "{0}",
    "{1,3}?", "{2,}?", "{,1}?", "{0,0}",
]


def random_pattern(rng: random.Random, depth: int = 0) -> str:
    """Build a random valid pattern from the supported syntax."""
    n_alts = rng.choice([1, 1, 1, 2, 3])
    alts = []
    for _ in range(n_alts):
        items = []
        for _ in range(rng.randint(0, 3)):
            r = rng.random()
            if r < 0.4:
                item = rng.choice(ATOMS)
            elif r < 0.55:
                item = rng.choice(SETS)
            elif r < 0.62:
                items.append(rng.choice(["^", "$"]))
                continue
            elif depth < 2:
                inner = random_pattern(rng, depth + 1)
                item = ("(?:" if rng.random() < 0.3 else "(") + inner + ")"
            else:
                item = rng.choice(ATOMS)
            if rng.random() < 0.45:
                item += rng.choice(QUANTS)
            items.append(item)
        alts.append("".join(items))
    return "|".join(alts)


def random_text(rng: random.Random, max_len: int = 8) -> str:
    return "".join(rng.choice("aabbc1 .\n_") for _ in range(rng.randint(0, max_len)))
