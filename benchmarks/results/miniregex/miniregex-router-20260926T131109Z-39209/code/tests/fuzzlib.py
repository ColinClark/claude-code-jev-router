"""Random pattern/text generation and comparison against ``re``."""

from __future__ import annotations

import random
import re

import miniregex

ALPHABET = "ab\n-"

_ATOMS = [
    "a", "b", "-", ".", r"\n", r"\-", r"\.", r"\w", r"\W", r"\s", r"\S", r"\d", r"\D",
    "[ab]", "[^a]", "[a-b]", "[-a]", "[a-]", "[^\\n]", "[\\s-]", "[]a]", "[^]a]", r"[\w]",
    "^", "$", r"\b", r"\B", r"\A", r"\Z",
]
_QUANTS = ["*", "+", "?", "{2}", "{1,2}", "{0,1}", "{,2}", "{2,}", "{0}", "{1,}", "{,}"]


class Gen:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def pattern(self, depth: int = 0) -> str:
        rng = self.rng
        n_alt = rng.choice([1, 1, 1, 2, 2, 3])
        alts = [self.seq(depth) for _ in range(n_alt)]
        return "|".join(alts)

    def bounded_pattern(self, max_len: int = 40) -> str:
        """A pattern short enough to keep backtracking cheap."""
        while True:
            pattern = self.pattern()
            if len(pattern) <= max_len:
                return pattern

    def seq(self, depth: int) -> str:
        rng = self.rng
        length = rng.choice([0, 1, 1, 2, 2, 3, 3, 4])
        return "".join(self.item(depth) for _ in range(length))

    def item(self, depth: int) -> str:
        rng = self.rng
        r = rng.random()
        if depth < 3 and r < 0.35:
            inner = self.pattern(depth + 1)
            base = rng.choice(["(%s)", "(%s)", "(?:%s)"]) % inner
        else:
            base = rng.choice(_ATOMS)
        if base in ("^", "$", r"\b", r"\B", r"\A", r"\Z"):
            return base
        if rng.random() < 0.4:
            q = rng.choice(_QUANTS)
            if rng.random() < 0.3:
                q += "?"
            base += q
        return base

    def text(self) -> str:
        rng = self.rng
        return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 7)))


def describe(m):
    if m is None:
        return None
    ngroups = len(m.groups())
    return (
        m.span(),
        m.group(),
        m.groups(),
        tuple(m.span(i) for i in range(ngroups + 1)),
    )


def compare(pattern: str, text: str) -> None:
    rx = re.compile(pattern)
    mx = miniregex.compile(pattern)
    assert mx.groups == rx.groups, pattern
    for meth in ("fullmatch", "match", "search"):
        expected = describe(getattr(rx, meth)(text))
        actual = describe(getattr(mx, meth)(text))
        assert actual == expected, (meth, pattern, text, expected, actual)
    assert mx.findall(text) == rx.findall(text), ("findall", pattern, text)
    expected_spans = [m.span() for m in rx.finditer(text)]
    actual_spans = [m.span() for m in mx.finditer(text)]
    assert actual_spans == expected_spans, ("finditer", pattern, text)


# Token soup used to fuzz the parser (valid and invalid patterns alike).
SYNTAX_TOKENS = list("ab()[]{}*+?|^$-,.:") + [
    "\\", "(?:", "1", "2", "0", r"\d", r"\w", r"\s", r"\b", r"\B", r"\x4", r"\x41", r"\n",
    r"\-", r"\]", "{1,2}", "{2}", "{,}", r"\q", r"\/", "[^", "a-b", r"\A", r"\Z", r"\01",
    r"\7", "\\u0041", "\\N{DIGIT ONE}", "é", "\\é",
]
SYNTAX_TEXTS = ["", "a", "ab", "ba-", "aab\n", "1a{", "A", "{,}", "b]-"]


def syntax_pattern(rng: random.Random) -> str:
    return "".join(rng.choice(SYNTAX_TOKENS) for _ in range(rng.randint(1, 8)))


def uses_unsupported(pattern: str) -> bool:
    """Constructs re accepts but miniregex deliberately rejects."""
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            if i + 1 < len(pattern) and pattern[i + 1] in "123456789":
                return True  # possible backreference
            i += 2
            continue
        if ch == "(" and pattern[i + 1 : i + 2] == "?" and pattern[i + 2 : i + 3] != ":":
            return True
        if ch in "*+?}" and pattern[i + 1 : i + 2] == "+":
            return True  # possessive quantifier
        i += 1
    return False
