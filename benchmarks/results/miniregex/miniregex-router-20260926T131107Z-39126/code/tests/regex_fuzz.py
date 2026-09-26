"""Random pattern/text generators and a differential checker against ``re``."""

from __future__ import annotations

import random
import re
import time
import warnings

import miniregex

ATOM_CHARS = ["a", "b", "a", "b", "c", r"\n", "\n", r"\.", "."]
SET_BODIES = [
    "ab", "^a", "^ab", "a-c", "^\n", r"\n", "b-", "-a", "]a", "^]", r"\d", r"\w", r"\s",
    r"\Wa", r"^\S", r"\D", "a\n", r"\]", r"\-a", r"a\-", r"^\w", "a-b\n", r"\^",
]
CLASSES = [r"\d", r"\D", r"\w", r"\W", r"\s", r"\S"]
QUANTS = ["*", "+", "?", "{2}", "{0}", "{1,}", "{0,2}", "{,2}", "{1,2}", "{2,3}", "{,}", "{0,1}"]
TEXT_ALPHABETS = ["ab", "ab\n", "abc", "ab\n1 ", "aab"]


def gen_quant(rng: random.Random) -> str:
    q = rng.choice(QUANTS)
    if rng.random() < 0.35:
        q += "?"
    return q


def gen_atom(rng: random.Random, depth: int, max_depth: int) -> tuple[str, bool]:
    """Return (atom, quantifiable)."""
    r = rng.random()
    if depth < max_depth and r < 0.30:
        inner = gen_alt(rng, depth + 1, max_depth)
        kind = rng.random()
        if kind < 0.65:
            return "(" + inner + ")", True
        return "(?:" + inner + ")", True
    if r < 0.60:
        return rng.choice(ATOM_CHARS), True
    if r < 0.72:
        return "[" + rng.choice(SET_BODIES) + "]", True
    if r < 0.80:
        return rng.choice(CLASSES), True
    if r < 0.88:
        return rng.choice(["^", "$"]), False
    if r < 0.93:
        return rng.choice(["()", "(?:)", "(|a)", "(a|)"]), True
    return ".", True


def gen_concat(rng: random.Random, depth: int, max_depth: int) -> str:
    n = rng.choice([0, 1, 1, 2, 2, 3, 4])
    parts = []
    for _ in range(n):
        atom, quantifiable = gen_atom(rng, depth, max_depth)
        if quantifiable and rng.random() < 0.45:
            atom += gen_quant(rng)
        parts.append(atom)
    return "".join(parts)


def gen_alt(rng: random.Random, depth: int, max_depth: int) -> str:
    n = rng.choice([1, 1, 1, 2, 2, 3])
    return "|".join(gen_concat(rng, depth, max_depth) for _ in range(n))


def gen_pattern(rng: random.Random, max_depth: int = 3) -> str:
    return gen_alt(rng, 0, max_depth)


def gen_text(rng: random.Random, max_len: int = 8) -> str:
    alphabet = rng.choice(TEXT_ALPHABETS)
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, max_len)))


def describe(m) -> object:
    if m is None:
        return None
    n = m.re.groups
    return (
        [m.span(g) for g in range(n + 1)],
        [m.group(g) for g in range(n + 1)],
        m.groups(),
        (m.start(), m.end()),
    )


def compile_both(pattern: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        expected = re.compile(pattern)
    actual = miniregex.compile(pattern)
    assert actual.groups == expected.groups, pattern
    return expected, actual


# Randomly generated patterns can backtrack catastrophically.  miniregex is an
# interpreter written in Python (roughly 50x slower than _sre), so cases on
# which ``re`` itself needs more than this many seconds are skipped.
RE_TIME_BUDGET = 0.002


def re_is_fast(expected, text: str) -> bool:
    t0 = time.perf_counter()
    expected.fullmatch(text)
    expected.findall(text)
    return time.perf_counter() - t0 < RE_TIME_BUDGET


def check(pattern: str, text: str, expected=None, actual=None) -> None:
    if expected is None:
        expected, actual = compile_both(pattern)
    for method in ("fullmatch", "match", "search"):
        want = describe(getattr(expected, method)(text))
        got = describe(getattr(actual, method)(text))
        assert got == want, (method, pattern, text, got, want)
    want_all = expected.findall(text)
    got_all = actual.findall(text)
    assert got_all == want_all, ("findall", pattern, text, got_all, want_all)
    want_iter = [describe(m) for m in expected.finditer(text)]
    got_iter = [describe(m) for m in actual.finditer(text)]
    assert got_iter == want_iter, ("finditer", pattern, text, got_iter, want_iter)


def run_fuzz(seed: int, iterations: int, texts_per_pattern: int = 6, max_depth: int = 3) -> int:
    rng = random.Random(seed)
    checked = 0
    for _ in range(iterations):
        pattern = gen_pattern(rng, max_depth)
        try:
            expected, actual = compile_both(pattern)
        except re.error:
            try:
                miniregex.compile(pattern)
            except miniregex.RegexError:
                continue
            raise AssertionError(f"re rejects {pattern!r} but miniregex accepts it") from None
        for _ in range(texts_per_pattern):
            text = gen_text(rng)
            if re_is_fast(expected, text):
                check(pattern, text, expected, actual)
                checked += 1
    return checked


# --- syntax soup: error vs. non-error agreement -----------------------------

SOUP = list("ab()[]{}*+?|^$.-,:^0123\\") + ["\\d", "\\w", "\\.", "(?:", "{1,2}", "[^"]
UNSUPPORTED_MARKERS = ("(?", "*+", "++", "?+", "}+")


def _uses_unsupported(pattern: str) -> bool:
    if any(m in pattern for m in UNSUPPORTED_MARKERS):
        return True
    # escapes that re accepts but miniregex intentionally does not support
    i = 0
    while i < len(pattern) - 1:
        if pattern[i] == "\\":
            if pattern[i + 1].isalnum() and pattern[i + 1] not in "dDwWsSntrfva":
                return True
            i += 2
        else:
            i += 1
    return False


def run_soup(seed: int, iterations: int) -> int:
    rng = random.Random(seed)
    accepted = 0
    for _ in range(iterations):
        pattern = "".join(rng.choice(SOUP) for _ in range(rng.randint(1, 8)))
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                expected = re.compile(pattern)
        except (re.error, OverflowError, RecursionError):
            expected = None
        try:
            actual = miniregex.compile(pattern)
        except miniregex.RegexError:
            actual = None
        if expected is None:
            assert actual is None, f"re rejects {pattern!r} but miniregex accepts it"
            continue
        if actual is None:
            assert _uses_unsupported(pattern), f"miniregex rejects valid {pattern!r}"
            continue
        accepted += 1
        for _ in range(3):
            text = gen_text(rng, 6)
            if re_is_fast(expected, text):
                check(pattern, text, expected, actual)
    return accepted
