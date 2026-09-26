"""Random pattern/text generators for differential fuzzing against ``re``."""

from __future__ import annotations

import random

ATOMS = [
    "a",
    "b",
    "a",
    "b",
    "\n",
    "\\n",
    ".",
    "\\d",
    "\\D",
    "\\w",
    "\\W",
    "\\s",
    "\\S",
    "[ab]",
    "[^a]",
    "[a-b]",
    "[\\n1]",
    "[^\\w]",
    "[-a]",
    "[b-]",
    "[]a]",
    "[^]]",
    "1",
    "_",
    "\\.",
    "\\-",
    "[\\d_]",
    "\\x61",
    "\\141",
]
ASSERTIONS = ["^", "$", "\\b", "\\B", "\\A", "\\Z"]
QUANTS = ["*", "+", "?", "{2}", "{1,}", "{0,2}", "{,1}", "{1,3}", "{0}", "{2,2}", "{0,}"]
TEXT_ALPHABET = "aab\n1_ "

# A small atom set that stresses groups, loops and empty iterations.
LOOPY_ATOMS = ["a", "a", "b", "(?:a*)", "(?:a?)", "(?:b?)", "(?:)", "()", "."]


class PatternGen:
    def __init__(self, rng: random.Random, atoms: list[str] | None = None) -> None:
        self.rng = rng
        self.atoms = ATOMS if atoms is None else atoms
        self.groups = 0
        self.closed: list[int] = []

    def pattern(self, max_len: int = 48) -> str:
        """Return a random pattern of at most ``max_len`` characters.

        The size bound keeps catastrophic backtracking (in both engines) rare.
        """
        while True:
            self.groups = 0
            self.closed = []
            pattern = self.alternation(3)
            if len(pattern) <= max_len:
                return pattern

    def alternation(self, depth: int) -> str:
        rng = self.rng
        n = 1 if rng.random() < 0.65 else rng.randint(2, 3)
        return "|".join(self.sequence(depth) for _ in range(n))

    def sequence(self, depth: int) -> str:
        rng = self.rng
        n = rng.choice([0, 1, 1, 2, 2, 2, 3, 3, 4])
        return "".join(self.term(depth) for _ in range(n))

    def term(self, depth: int) -> str:
        rng = self.rng
        r = rng.random()
        if r < 0.08:
            return rng.choice(ASSERTIONS)
        if r < 0.11 and self.closed:
            return f"\\{rng.choice(self.closed)}"
        atom = self.atom(depth)
        if rng.random() < 0.45:
            q = rng.choice(QUANTS)
            if rng.random() < 0.3:
                q += "?"
            atom += q
        return atom

    def atom(self, depth: int) -> str:
        rng = self.rng
        if depth > 0 and rng.random() < 0.4:
            if rng.random() < 0.6:
                self.groups += 1
                gid = self.groups
                inner = self.alternation(depth - 1)
                self.closed.append(gid)
                return "(" + inner + ")"
            return "(?:" + self.alternation(depth - 1) + ")"
        return rng.choice(self.atoms)


def random_text(rng: random.Random, max_len: int = 7) -> str:
    return "".join(rng.choice(TEXT_ALPHABET) for _ in range(rng.randint(0, max_len)))


JUNK_TOKENS = [
    "a",
    "b",
    "(",
    ")",
    "(?:",
    "(?",
    "[",
    "]",
    "[^",
    "*",
    "+",
    "?",
    "{",
    "}",
    "{1}",
    "{2,1}",
    "{1,",
    ",",
    "1",
    "|",
    "^",
    "$",
    "-",
    "\\",
    "\\d",
    "\\q",
    "\\1",
    "\\2",
    "a-",
    "z-a",
    ".",
    "\\x",
    "\\x4",
    "\\u12",
    "\\0",
    "\\8",
    ":",
    "{,}",
    "{}",
]


def junk_pattern(rng: random.Random) -> str:
    return "".join(rng.choice(JUNK_TOKENS) for _ in range(rng.randint(1, 6)))
