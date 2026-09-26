"""Shared helpers: compare miniregex against the re module."""

import random
import re

import miniregex


def snapshot(m, ngroups):
    """Everything observable about a match, for comparison."""
    if m is None:
        return None
    return (
        m.group(),
        m.span(),
        m.groups(),
        tuple(m.span(g) for g in range(ngroups + 1)),
        tuple(m.start(g) for g in range(ngroups + 1)),
        tuple(m.end(g) for g in range(ngroups + 1)),
    )


def assert_same(pattern, text):
    expected = re.compile(pattern)
    actual = miniregex.compile(pattern)
    assert actual.groups == expected.groups, pattern
    n = expected.groups
    for method in ("fullmatch", "match", "search"):
        want = snapshot(getattr(expected, method)(text), n)
        got = snapshot(getattr(actual, method)(text), n)
        assert got == want, f"{method}({pattern!r}, {text!r}): got {got}, want {want}"
    want = expected.findall(text)
    got = actual.findall(text)
    assert got == want, f"findall({pattern!r}, {text!r}): got {got}, want {want}"


class PatternGenerator:
    """Random patterns built from the supported grammar."""

    ATOMS = ["a", "b", "c", ".", r"\d", r"\w", r"\s", r"\W", r"\.", "-", "1", " "]
    SETS = ["[ab]", "[^a]", "[a-c]", "[-a]", "[a-]", "[]a]", r"[\d\s]", "[^]b]", r"[\w-]", "[.]"]
    QUANTS = ["*", "+", "?", "{2}", "{1,}", "{0,2}", "{,2}", "{1,3}", "{0}", "{2,2}"]

    def __init__(self, seed):
        self.rng = random.Random(seed)

    def small_pattern(self, max_len=40):
        """A random pattern short enough to keep backtracking cheap."""
        while True:
            p = self.pattern()
            if len(p) <= max_len:
                return p

    def pattern(self, depth=0):
        rng = self.rng
        n = rng.randint(1, 3)
        branches = [self.seq(depth) for _ in range(n if rng.random() < 0.35 else 1)]
        return "|".join(branches)

    def seq(self, depth):
        rng = self.rng
        return "".join(self.item(depth) for _ in range(rng.randint(0, 4)))

    def item(self, depth):
        rng = self.rng
        r = rng.random()
        if r < 0.08:
            return rng.choice(["^", "$"])
        if r < 0.45 or depth >= 3:
            atom = rng.choice(self.ATOMS) if rng.random() < 0.75 else rng.choice(self.SETS)
        else:
            inner = self.pattern(depth + 1)
            atom = f"({inner})" if rng.random() < 0.7 else f"(?:{inner})"
        if rng.random() < 0.45:
            atom += rng.choice(self.QUANTS)
            if rng.random() < 0.3:
                atom += "?"
        return atom

    def text(self):
        rng = self.rng
        return "".join(rng.choice("aabbc1 -.\n") for _ in range(rng.randint(0, 8)))
