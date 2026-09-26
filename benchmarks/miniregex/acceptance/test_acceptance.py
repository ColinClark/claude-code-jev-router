"""Hidden acceptance tests for the miniregex benchmark, written only from benchmarks/miniregex/prompt.md.

The prompt defines correct behavior as "identical to Python's re", so every case is checked against `re`:
match / no match, the overall span, and every group's value and span, for fullmatch, match and search, plus
findall. Neither benchmark mode sees these tests.
"""

import random
import re
from pathlib import Path

import pytest
from miniregex import RegexError
from miniregex import compile as mcompile


def describe(m):
    if m is None:
        return None
    n = len(m.groups())
    return {
        "span": m.span(),
        "group": m.group(),
        "groups": m.groups(),
        "spans": [m.span(i) for i in range(1, n + 1)],
    }


def check(pattern, text):
    ref, mine = re.compile(pattern), mcompile(pattern)
    for method in ("fullmatch", "match", "search"):
        want = describe(getattr(ref, method)(text))
        got = describe(getattr(mine, method)(text))
        assert got == want, f"{method}({pattern!r}, {text!r})\n got: {got}\nwant: {want}"
    assert mine.findall(text) == ref.findall(text), f"findall({pattern!r}, {text!r})"


CASES = [
    # literals, dot, escapes, classes
    ("abc", ["abc", "xabcx", "ab", ""]),
    ("a.c", ["abc", "a\nc", "ac", "a.c"]),
    (r"a\.c", ["a.c", "abc"]),
    (r"\d+\s\w*", ["12 ab_9", "1  x", "a1 b", "7\tz"]),
    (r"\D\W\S", ["a b", "1-x", "a!b"]),
    (r"\\\*\+\?\(\)\[\]\{\}\|\^\$\-", ["\\*+?()[]{}|^$-"]),
    # sets
    ("[abc]+", ["cabbage", "xyz"]),
    ("[^abc]+", ["cabbage", "xyz"]),
    ("[a-c0-2]+", ["a1c2b3", "zz"]),
    ("[-a]+", ["-a-b"]),
    ("[a-]+", ["a--b"]),
    ("[]a]+", ["]a]b"]),
    ("[^]a]+", ["]a]bc"]),
    (r"[\d-]+", ["12-3a"]),
    (r"[\w.]+", ["a.b_c d"]),
    (r"[a\-z]+", ["a-z m"]),
    # anchors
    ("^ab", ["abab", "bab"]),
    ("ab$", ["abab", "ab\n", "ab\n\n", "abx"]),
    ("^$", ["", "\n", "a"]),
    ("^a|b$", ["ab", "cb", "ac"]),
    # quantifiers, greedy vs lazy, counted
    ("a*", ["", "aaa", "baaa", "aba"]),
    ("a+?", ["aaa"]),
    ("a*?b", ["aaab", "b"]),
    ("a??b", ["ab", "b"]),
    ("a{2}", ["a", "aaa", "aaaaa"]),
    ("a{2,}", ["a", "aaaaa"]),
    ("a{2,3}", ["aaaaaaa"]),
    ("a{2,3}?", ["aaaaaaa"]),
    ("a{,2}b", ["aaab", "b"]),
    ("x{0}y", ["xy", "y"]),
    # groups: participation, last iteration, backtracking into groups
    ("(a)|b", ["a", "b", "c"]),
    ("(a|b)*", ["abab", ""]),
    ("(a*)*", ["aaa", "b"]),
    ("(a*)+", ["aaa", "b"]),
    ("(a|ab)(c|bcd)(d*)", ["abcd", "abcdd"]),
    ("((a)|b)+", ["ab", "ba"]),
    ("(?:(a)|(b))+", ["ab", "ba", "aab"]),
    ("(a?)(a?)(a?)aaa", ["aaa", "aaaa"]),
    ("(.*)(\\d+)", ["abc123"]),
    ("(.*?)(\\d+)", ["abc123"]),
    ("(a+)(a+)", ["aaaa"]),
    ("(a+?)(a+)", ["aaaa"]),
    ("(?:ab|a)(bc|c)", ["abc"]),
    ("(x)?y", ["y", "xy"]),
    ("((x)(y)?)+", ["xyx", "xxy"]),
    # findall shapes
    ("a|", ["bab"]),
    ("(a)(b)?", ["aab ab"]),
    ("(?:a)(b)", ["ab ab"]),
]


@pytest.mark.parametrize(("pattern", "texts"), CASES, ids=[p for p, _ in CASES])
def test_matches_re(pattern, texts):
    for text in texts:
        check(pattern, text)


ALPHABET = "ab1 .\n"


def atom(rng):
    return rng.choice(["a", "b", "1", ".", r"\d", r"\w", r"\s", r"\.", "[ab]", "[^a]", "[a-b1]", "[-a]", " "])


def piece(rng, depth):
    roll = rng.random()
    if depth < 2 and roll < 0.25:
        body = alternation(rng, depth + 1)
        base = f"({body})" if rng.random() < 0.7 else f"(?:{body})"
    else:
        base = atom(rng)
    if rng.random() < 0.45:
        quant = rng.choice(["*", "+", "?", "{2}", "{1,}", "{1,2}", "{,2}", "{0,1}"])
        base += quant + ("?" if rng.random() < 0.3 else "")
    return base


def sequence(rng, depth):
    return "".join(piece(rng, depth) for _ in range(rng.randint(1, 3)))


def alternation(rng, depth):
    branches = [sequence(rng, depth) for _ in range(1 if rng.random() < 0.7 else 2)]
    return "|".join(branches)


def random_pattern(rng):
    pattern = alternation(rng, 0)
    if rng.random() < 0.15:
        pattern = "^" + pattern
    if rng.random() < 0.15:
        pattern += "$"
    return pattern


@pytest.mark.parametrize("batch", range(20))
def test_fuzz_against_re(batch):
    rng = random.Random(7000 + batch)
    checked = 0
    while checked < 40:
        pattern = random_pattern(rng)
        try:
            re.compile(pattern)
        except re.error:
            continue
        for _ in range(6):
            text = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 7)))
            check(pattern, text)
        checked += 1


@pytest.mark.parametrize("pattern", ["(", "a)", "[a", "*a", "a**", "a{2,1}", "(?:a", "a|*"])
def test_invalid_patterns_raise(pattern):
    with pytest.raises(RegexError):
        mcompile(pattern)


def test_implementation_does_not_use_re():
    import miniregex

    package = Path(miniregex.__file__).resolve().parent
    offenders = []
    for path in package.rglob("*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(("import re", "from re ", "import regex", "from regex ")) and (
                stripped in ("import re", "import regex") or stripped.startswith(("import re ", "from re "))
            ):
                offenders.append(f"{path.name}: {stripped}")
    assert offenders == []
