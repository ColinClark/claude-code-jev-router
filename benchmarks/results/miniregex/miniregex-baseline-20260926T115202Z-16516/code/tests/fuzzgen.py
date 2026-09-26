"""Random pattern/text generators shared by the fuzz tests."""

from __future__ import annotations

import random
import re
import warnings

import miniregex

TEXT_ALPHABET = "aabbc-x1 _\n"

_ATOMS = [
    "a",
    "b",
    "c",
    "x",
    "-",
    "1",
    " ",
    ".",
    r"\d",
    r"\D",
    r"\w",
    r"\W",
    r"\s",
    r"\S",
    r"\.",
    r"\-",
    r"\\",
    r"\n",
    "[ab]",
    "[^a]",
    "[a-c]",
    "[^b-x]",
    r"[\d_]",
    "[-a]",
    "[a-]",
    "[]a]",
    r"[\w\-]",
    r"[^\s]",
    "[.]",
    "[bc1]",
]
_QUANTIFIERS = [
    "*",
    "+",
    "?",
    "*?",
    "+?",
    "??",
    "{2}",
    "{1,2}",
    "{0,1}",
    "{,2}",
    "{2,}",
    "{0}",
    "{1,3}?",
    "{,1}?",
    "{2,}?",
    "{0,}",
]


def random_pattern(rng: random.Random, depth: int = 0) -> str:
    """Build a random, usually valid, pattern from the supported syntax."""
    parts = []
    for _ in range(rng.randint(0 if depth else 1, 4)):
        roll = rng.random()
        if roll < 0.2 and depth < 2:
            inner = random_pattern(rng, depth + 1)
            if rng.random() < 0.4:
                inner += "|" + random_pattern(rng, depth + 1)
            atom = ("(" if rng.random() < 0.6 else "(?:") + inner + ")"
        elif roll < 0.25:
            atom = rng.choice(["^", "$"])
        else:
            atom = rng.choice(_ATOMS)
        if atom not in ("^", "$") and rng.random() < 0.4:
            atom += rng.choice(_QUANTIFIERS)
        parts.append(atom)
    pattern = "".join(parts)
    if depth == 0 and rng.random() < 0.3:
        pattern += "|" + random_pattern(rng, 1)
    return pattern


def random_text(rng: random.Random, max_len: int = 8) -> str:
    return "".join(rng.choice(TEXT_ALPHABET) for _ in range(rng.randint(0, max_len)))


def describe(m) -> object:
    """Everything observable about a match (or None)."""
    if m is None:
        return None
    n = len(m.groups())
    return (
        m.span(),
        m.group(),
        m.groups(),
        [m.span(i) for i in range(n + 1)],
        [(m.start(i), m.end(i)) for i in range(n + 1)],
    )


def compile_both(pattern: str):
    """Return (re_pattern, miniregex_pattern), or (None, None) if re rejects the pattern."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            expected = re.compile(pattern)
        except (re.error, OverflowError):
            return None, None
    return expected, miniregex.compile(pattern)


def assert_same(pattern: str, text: str, expected=None, actual=None) -> None:
    if expected is None:
        expected, actual = compile_both(pattern)
        assert expected is not None, pattern
    for method in ("fullmatch", "match", "search"):
        want = describe(getattr(expected, method)(text))
        got = describe(getattr(actual, method)(text))
        assert got == want, f"{method}({pattern!r}, {text!r}): got {got}, want {want}"
    want = expected.findall(text)
    got = actual.findall(text)
    assert got == want, f"findall({pattern!r}, {text!r}): got {got}, want {want}"
