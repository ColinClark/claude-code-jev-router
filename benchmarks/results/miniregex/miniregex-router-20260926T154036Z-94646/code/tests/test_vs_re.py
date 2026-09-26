"""Compare miniregex against re on hand-picked patterns and on random fuzzing."""

import random

import pytest

TEXTS = ["", "a", "b", "ab", "aab", "abb", "abab", "aaa", "ba", "a\n", "\n", "a-b", "abc", "x1_ y"]

PATTERNS = [
    # literals, dot, escapes
    "a",
    "ab",
    "abc",
    ".",
    "a.b",
    r"a\.b",
    r"\\",
    r"\*\+\?",
    r"\(\)\[\]\{\}",
    r"\|\^\$\-",
    r"\/",
    r"\n",
    r"\t",
    # classes
    r"\d",
    r"\D",
    r"\w+",
    r"\W",
    r"\s",
    r"\S+",
    r"\d\w\s",
    # sets
    "[ab]",
    "[^ab]",
    "[a-c]+",
    "[-a]",
    "[a-]",
    "[]a]",
    "[^]a]",
    "[]-a]",
    r"[\d-]",
    r"[\w\s]+",
    r"[\]]",
    r"[\\]",
    r"[.*+]",
    "[a-c-e]",
    "[--a]",
    r"[^\W_]",
    r"[\b]",
    "[$^]",
    # anchors
    "^",
    "$",
    "^a",
    "a$",
    "^$",
    "^a*$",
    "(^a|b$)",
    "a|^b",
    "$a",
    "a^",
    # quantifiers
    "a*",
    "a+",
    "a?",
    "a*?",
    "a+?",
    "a??",
    "a{2}",
    "a{1,}",
    "a{1,2}",
    "a{,2}",
    "a{2}?",
    "a{0}",
    "a{,}",
    "a{}",
    "a{",
    "a{x}",
    "a{1,x}",
    "{",
    "}",
    "a{1",
    "x{,2}?",
    "(?:ab){1,2}",
    # alternation and groups
    "a|b",
    "a|",
    "|a",
    "|",
    "a||b",
    "(a)",
    "(a)|b",
    "(a|b)+",
    "(a)(b)?",
    "(?:a|b)*c",
    "()",
    "()*",
    "(?:)*",
    "(a*)*",
    "(a|)*",
    "(a|)+?",
    "(a*)+b",
    "((a)|b)+",
    "(?:(a)|b)*",
    "(a?){2,}",
    "(a|ab)(c|bcd)?",
    "((a)(b)?)*",
    "(a*?)*?b",
    "(?:a*|b)*",
    "((a*)*|b)*",
]


@pytest.mark.parametrize("pattern", PATTERNS)
def test_known_patterns(same, pattern):
    same(pattern, TEXTS)


# -- random fuzzing -------------------------------------------------------------

ALPHABET = "ab-\n"
ATOMS = [
    "a",
    "b",
    ".",
    r"\d",
    r"\w",
    r"\s",
    r"\W",
    "-",
    r"\-",
    "[ab]",
    "[^a]",
    "[a-]",
    "[]a]",
    r"[\w-]",
    "^",
    "$",
    "\n",
    r"\n",
    "x",
]
QUANTS = ["*", "+", "?", "*?", "+?", "??", "{2}", "{0,1}", "{1,}", "{,2}", "{1,2}?", "{0}", "{,}"]


def gen_pattern(rng, depth=0):
    parts = []
    for _ in range(rng.randint(0, 3)):
        r = rng.random()
        if r < 0.25 and depth < 3:
            inner = gen_pattern(rng, depth + 1)
            if rng.random() < 0.4:
                inner += "|" + gen_pattern(rng, depth + 1)
            atom = ("(?:" if rng.random() < 0.3 else "(") + inner + ")"
        else:
            atom = rng.choice(ATOMS)
        if rng.random() < 0.4:
            atom += rng.choice(QUANTS)
        parts.append(atom)
    pattern = "".join(parts)
    if rng.random() < 0.15:
        pattern += "|" + gen_pattern(rng, depth + 1)
    return pattern


def gen_text(rng):
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 7)))


@pytest.mark.parametrize("seed", range(40))
def test_fuzz_against_re(same, seed):
    rng = random.Random(seed)
    for _ in range(100):
        pattern = gen_pattern(rng)
        same(pattern, [gen_text(rng) for _ in range(6)])


RAW_CHARS = "ab()[]{}|*+?^$.\\-,:12"


@pytest.mark.parametrize("seed", range(10))
def test_fuzz_raw_syntax(same, seed):
    """Random character soup: exercises parse errors and odd-but-valid syntax."""
    rng = random.Random(1000 + seed)
    for _ in range(300):
        pattern = "".join(rng.choice(RAW_CHARS) for _ in range(rng.randint(1, 8)))
        if "(?" in pattern and "(?:" not in pattern:
            continue  # other group extensions are outside the supported syntax
        if "\\" in pattern and any(f"\\{d}" in pattern for d in "12b"):
            continue  # backreferences and \b are unsupported
        if any(q + "+" in pattern for q in "*+?}"):
            continue  # possessive quantifiers are unsupported
        same(pattern, [gen_text(rng) for _ in range(3)] + ["ab", "a{1}", "(a)"])
