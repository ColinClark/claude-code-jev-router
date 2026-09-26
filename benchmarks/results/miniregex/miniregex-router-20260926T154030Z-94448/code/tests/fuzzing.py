"""Random pattern/text generation and comparison against ``re``."""

from __future__ import annotations

import random
import re
import time

import miniregex

ALPHABET = "abc"
TEXT_ALPHABET = "abc\n -1_"

ATOMS = [
    "a",
    "b",
    "c",
    ".",
    r"\d",
    r"\w",
    r"\s",
    r"\W",
    r"\D",
    r"\S",
    "[ab]",
    "[^a]",
    "[a-c]",
    "[^b-c\\n]",
    "[-a]",
    "[a-]",
    "[]a]",
    r"[\d_]",
    r"\-",
    r"\.",
    "^",
    "$",
    "",
]

QUANTIFIERS = ["*", "+", "?", "{2}", "{1,}", "{0,2}", "{,2}", "{1,3}", "{0}", "{,}"]


def random_pattern(rng: random.Random, depth: int = 0) -> str:
    """Build a random pattern from supported constructs."""
    parts = []
    for _ in range(rng.randint(1, 3)):
        roll = rng.random()
        if roll < 0.3 and depth < 2:
            inner = random_pattern(rng, depth + 1)
            if rng.random() < 0.3:
                inner += "|" + random_pattern(rng, depth + 1)
            opener = "(" if rng.random() < 0.6 else "(?:"
            atom = opener + inner + ")"
        else:
            atom = rng.choice(ATOMS)
            if atom in ("^", "$", ""):
                parts.append(atom)
                continue
        if rng.random() < 0.5:
            atom += rng.choice(QUANTIFIERS)
            if rng.random() < 0.35:
                atom += "?"
        parts.append(atom)
    pattern = "".join(parts)
    if depth == 0 and rng.random() < 0.2:
        pattern += "|" + random_pattern(rng, depth + 1)
    return pattern


def random_text(rng: random.Random) -> str:
    alphabet = TEXT_ALPHABET if rng.random() < 0.5 else ALPHABET
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 8)))


def too_slow_for_re(pattern: str, text: str, limit: float) -> bool:
    """True if ``re`` needs more than ``limit`` seconds on ``text``.

    Backtracking cost grows quickly with the text length, so prefixes are
    timed one by one and the check stops before an exponential case explodes.
    """
    try:
        compiled = re.compile(pattern)
    except re.error:
        return False
    for n in range(len(text) + 1):
        prefix = text[:n]
        start = time.perf_counter()
        compiled.match(prefix)
        compiled.fullmatch(prefix)
        compiled.search(prefix)
        compiled.findall(prefix)
        if time.perf_counter() - start > limit:
            return True
    return False


def describe(m):
    if m is None:
        return None
    n = len(m.groups())
    return (m.span(), m.group(), m.groups(), [m.span(i) for i in range(1, n + 1)])


def compare(pattern: str, text: str) -> list[str]:
    """Return a list of human-readable mismatches between re and miniregex."""
    problems = []
    try:
        expected = re.compile(pattern)
    except re.error:
        try:
            miniregex.compile(pattern)
        except miniregex.RegexError:
            return []
        return [f"{pattern!r}: re rejects it but miniregex accepts it"]
    try:
        actual = miniregex.compile(pattern)
    except miniregex.RegexError as exc:
        return [f"{pattern!r}: miniregex rejects it ({exc}) but re accepts it"]
    for method in ("match", "fullmatch", "search"):
        want = describe(getattr(expected, method)(text))
        got = describe(getattr(actual, method)(text))
        if want != got:
            problems.append(f"{method}({pattern!r}, {text!r}): re={want} mini={got}")
    want = expected.findall(text)
    got = actual.findall(text)
    if want != got:
        problems.append(f"findall({pattern!r}, {text!r}): re={want} mini={got}")
    return problems
