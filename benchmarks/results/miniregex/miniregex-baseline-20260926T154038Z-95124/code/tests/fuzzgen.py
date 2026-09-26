"""Random pattern/text generators shared by the fuzz tests."""

from __future__ import annotations

import random
import re
import warnings

import miniregex

ALPHABET = "ab\n -_1"

_ATOMS = [
    "a",
    "b",
    ".",
    r"\d",
    r"\D",
    r"\w",
    r"\W",
    r"\s",
    r"\S",
    r"\.",
    r"\-",
    "[ab]",
    "[^a]",
    "[a-c]",
    "[-a]",
    "[b-]",
    "[]a]",
    r"[\d_]",
    r"[^\s]",
    r"[\w-]",
    "1",
    "-",
    " ",
]

_QUANTS = ["*", "+", "?", "{2}", "{1,}", "{0,2}", "{,2}", "{1,3}", "{0}", "{,}"]


def random_pattern(rng: random.Random, depth: int = 0) -> str:
    """Build a syntactically valid pattern from the supported subset."""
    roll = rng.random()
    if depth > 3 or roll < 0.35:
        node = rng.choice(_ATOMS)
    elif roll < 0.55:
        node = "".join(random_pattern(rng, depth + 1) for _ in range(rng.randint(1, 3)))
    elif roll < 0.7:
        node = "|".join(random_pattern(rng, depth + 1) for _ in range(rng.randint(2, 3)))
    elif roll < 0.85:
        open_ = rng.choice(["(", "(?:"])
        inner = "" if rng.random() < 0.1 else random_pattern(rng, depth + 1)
        node = open_ + inner + ")"
    elif roll < 0.92:
        node = rng.choice(["^", "$"])
        return node
    else:
        node = "(" + random_pattern(rng, depth + 1) + ")"
    if rng.random() < 0.4 and not node.endswith(tuple(_QUANTS)):
        if len(node) > 1 and not (node.startswith(("(", "[")) or node.startswith("\\")):
            node = "(?:" + node + ")"
        node += rng.choice(_QUANTS)
        if rng.random() < 0.3:
            node += "?"
    return node


def random_text(rng: random.Random, max_len: int = 8) -> str:
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, max_len)))


def describe(m):
    """Normalise a match object (from re or miniregex) into comparable data."""
    if m is None:
        return None
    ngroups = len(m.groups())
    return (
        m.group(0),
        m.span(),
        m.groups(),
        tuple(m.span(i) for i in range(ngroups + 1)),
        tuple(m.start(i) for i in range(ngroups + 1)),
        tuple(m.end(i) for i in range(ngroups + 1)),
    )


def compare(pattern: str, texts) -> None:
    """Assert miniregex behaves exactly like re for ``pattern`` on every text."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            expected = re.compile(pattern)
        except (re.error, OverflowError):
            expected = None
    if expected is None:
        try:
            miniregex.compile(pattern)
        except miniregex.RegexError:
            return
        raise AssertionError(f"miniregex accepted invalid pattern {pattern!r}")
    ours = miniregex.compile(pattern)
    assert ours.groups == expected.groups, pattern
    for text in texts:
        ctx = f"pattern={pattern!r} text={text!r}"
        assert describe(ours.fullmatch(text)) == describe(expected.fullmatch(text)), ctx
        assert describe(ours.match(text)) == describe(expected.match(text)), ctx
        assert describe(ours.search(text)) == describe(expected.search(text)), ctx
        assert ours.findall(text) == expected.findall(text), ctx
