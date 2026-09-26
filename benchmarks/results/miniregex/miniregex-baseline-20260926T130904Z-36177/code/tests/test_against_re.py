"""Compare miniregex results against the stdlib `re` module (no flags).

`re` is only used here, in tests, as an oracle -- never inside the
implementation.
"""

import random
import re

import pytest

import miniregex as mr


def _compare(pattern, text):
    try:
        py_pat = re.compile(pattern)
    except re.error:
        # Not every string `re` rejects is one we also reject (and vice
        # versa isn't required either), so only compare when both compile.
        try:
            mr.compile(pattern)
        except mr.RegexError:
            return
        return
    try:
        mine_pat = mr.compile(pattern)
    except mr.RegexError as exc:
        pytest.fail(f"miniregex rejected valid pattern {pattern!r}: {exc}")

    for py_m, mine_m in (
        (py_pat.fullmatch(text), mine_pat.fullmatch(text)),
        (py_pat.match(text), mine_pat.match(text)),
        (py_pat.search(text), mine_pat.search(text)),
    ):
        if py_m is None:
            assert mine_m is None, (pattern, text, "expected None")
            continue
        assert mine_m is not None, (pattern, text, "expected a match")
        assert py_m.span() == mine_m.span(), (pattern, text, "span")
        ng = py_pat.groups
        for i in range(ng + 1):
            assert py_m.span(i) == mine_m.span(i), (pattern, text, "group span", i)
            assert py_m.group(i) == mine_m.group(i), (pattern, text, "group value", i)

    assert py_pat.findall(text) == mine_pat.findall(text), (pattern, text, "findall")


LITERAL_PATTERNS = [
    "abc",
    "a.c",
    "a.c.",
    "^abc$",
    "^abc",
    "abc$",
    r"a\.c",
    r"a\\c",
    r"\d+",
    r"\D+",
    r"\w+",
    r"\W+",
    r"\s+",
    r"\S+",
    r"[abc]+",
    r"[a-z]+",
    r"[^a-z]+",
    r"[a-zA-Z0-9_]+",
    r"[\d\s]+",
    r"[]a]+",
    r"[^]]+",
    r"[a-]+",
    r"[-a]+",
    "a*",
    "a+",
    "a?",
    "a*?",
    "a+?",
    "a??",
    "a{2}",
    "a{2,4}",
    "a{2,}",
    "a{,4}",
    "a{2,4}?",
    "cat|dog|bird",
    "(cat|dog)s?",
    "(a|b)*c",
    "(ab)+",
    "(a)(b)(c)",
    "(a)(b)?(c)",
    "(?:ab)+c",
    "(a?)*b",
    "(a*)*",
    "(a*)+",
    "(a+)*",
    "(a|)*",
    "(a?){3}",
    "(a*)(a*)",
    r"\w+@\w+\.\w+",
    r"^\s*(\w+)\s*=\s*(\w+)\s*$",
    r"(\d{1,3}\.){3}\d{1,3}",
    r"<(\w+)>.*?</>",
    r"a{0,0}",
    r"(a|ab)(c|bcd)(d*)",
    r"(a|ab)*",
    r"[^\d]+",
    r"[\D]+",
]

TEXTS = [
    "",
    "a",
    "abc",
    "abcabc",
    "aaaa",
    "AbC123_",
    "the cat sat on the dog",
    "user@host.com",
    "  key = value  ",
    "192.168.0.1",
    "aababcabcd",
    "a\nb",
    "abc\n",
    "]]a]a]",
    "---a---",
]


@pytest.mark.parametrize("pattern", LITERAL_PATTERNS)
@pytest.mark.parametrize("text", TEXTS)
def test_matrix(pattern, text):
    _compare(pattern, text)


ALPHABET = "aabb01 -_.\n"
ATOMS = [
    "a",
    "b",
    ".",
    r"\d",
    r"\w",
    r"\s",
    "[ab]",
    "[^ab]",
    "[a-b0-9]",
    "(a|b)",
    "(?:a|b)",
]
QUANTS = ["", "*", "+", "?", "{1,2}", "*?", "+?", "{0,2}"]


def _random_pattern(rng):
    n = rng.randint(1, 4)
    parts = []
    for _ in range(n):
        atom = rng.choice(ATOMS)
        quant = rng.choice(QUANTS)
        parts.append(atom + quant)
    body = "".join(parts)
    if rng.random() < 0.2:
        body = f"({body})"
    if rng.random() < 0.15:
        body = "^" + body
    if rng.random() < 0.15:
        body = body + "$"
    if rng.random() < 0.2:
        alt = "".join(rng.choice(ATOMS) + rng.choice(QUANTS) for _ in range(rng.randint(1, 2)))
        body = body + "|" + alt
    return body


def _random_text(rng):
    n = rng.randint(0, 8)
    return "".join(rng.choice(ALPHABET) for _ in range(n))


@pytest.mark.parametrize("seed", range(300))
def test_fuzz_against_re(seed):
    rng = random.Random(seed)
    pattern = _random_pattern(rng)
    text = _random_text(rng)
    _compare(pattern, text)
