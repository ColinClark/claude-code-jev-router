"""Random pattern and text generators for differential testing against ``re``."""

from __future__ import annotations

import random

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
    r"\-",
    r"\.",
    "[ab]",
    "[^a]",
    "[a-c]",
    "[-a]",
    "[b-]",
    "[]a]",
    r"[\s\d]",
    "[^\n]",
    r"[^\w-]",
    "1",
    " ",
    "^",
    "$",
    "{",
    "}",
    "]",
]
BOUNDED = ["?", "{2}", "{0,2}", "{,2}", "{1,2}", "{0}", "{1}"]
UNBOUNDED = ["*", "+", "{1,}", "{2,}", "{,}"]
TEXT_ALPHABET = "ab1 \n-c"


def random_pattern(
    rng: random.Random, depth: int = 0, unbounded_ok: bool = True, max_depth: int = 3
) -> str:
    """A random valid pattern.

    Unbounded quantifiers are not nested inside other unbounded quantifiers, which keeps
    worst-case backtracking (exponential in ``re`` too) cheap enough for the tests.
    """
    n_alts = 1 if depth >= max_depth or rng.random() < 0.7 else rng.randint(2, 3)
    alts = []
    for _ in range(n_alts):
        parts = []
        for _ in range(rng.randint(0, 3)):
            quant = ""
            if rng.random() < 0.4:
                choices = BOUNDED + UNBOUNDED if unbounded_ok else BOUNDED
                quant = rng.choice(choices)
                if rng.random() < 0.35:
                    quant += "?"
            if rng.random() < 0.3 and depth < max_depth:
                inner_unbounded = unbounded_ok and quant.rstrip("?") not in UNBOUNDED
                inner = random_pattern(rng, depth + 1, inner_unbounded, max_depth)
                atom = f"({inner})" if rng.random() < 0.6 else f"(?:{inner})"
            else:
                atom = rng.choice(ATOMS)
                if atom in ("^", "$"):
                    quant = ""
                elif atom == "{" and quant:
                    atom = r"\{"
            parts.append(atom + quant)
        alts.append("".join(parts))
    return "|".join(alts)


def random_text(rng: random.Random, max_len: int = 8) -> str:
    return "".join(rng.choice(TEXT_ALPHABET) for _ in range(rng.randint(0, max_len)))
