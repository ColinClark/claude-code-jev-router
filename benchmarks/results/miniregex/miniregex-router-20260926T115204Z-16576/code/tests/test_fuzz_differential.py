"""Differential fuzzing against CPython's ``re``.

Random patterns are drawn from a grammar covering every supported construct
(literals, ``.``, sets, classes, anchors, capturing and non-capturing groups,
alternation with empty branches, all quantifier forms incl. lazy and ``{n,m}``)
and matched against random texts over ``"ab\\n "``.

For each pattern that ``re`` accepts we compare, for match/search/fullmatch:
the overall span, every group value and every group span; plus ``findall``.
Patterns that ``re`` rejects must also be rejected by miniregex.

Nesting of quantifiers is bounded so that pathological exponential cases
(which are exponential for ``re`` as well) do not dominate the runtime.
"""

import random
import re

import pytest

import miniregex

ATOMS = [
    "a",
    "b",
    "a",
    "b",
    ".",
    "[ab]",
    "[^a]",
    "[a-b]",
    "[^\\s]",
    "[\\d\\w]",
    "[]a]",
    "[^]b]",
    "[a-]",
    "\\w",
    "\\W",
    "\\s",
    "\\S",
    "\\d",
    "\\D",
    "^",
    "$",
    "\\n",
    " ",
    "\\.",
    "(?:)",
    "()",
]
QUANTIFIERS = ["*", "+", "?", "{2}", "{1,2}", "{,2}", "{0,}", "{2,3}", "{0}", "{1}", "{,}", "{0,1}"]
TEXT_ALPHABET = "ab\n "


def gen_pattern(rng: random.Random, depth: int, quant_budget: int) -> str:
    """Random pattern; ``quant_budget`` bounds the nesting depth of quantifiers."""
    r = rng.random()
    quantify = quant_budget > 0 and rng.random() < 0.55
    inner_budget = quant_budget - 1 if quantify else quant_budget
    if depth == 0 or r < 0.3:
        base = rng.choice(ATOMS)
    elif r < 0.55:
        alts = [gen_pattern(rng, depth - 1, inner_budget) for _ in range(rng.randint(1, 3))]
        base = "(" + "|".join(alts) + ")"
    elif r < 0.7:
        alts = [gen_pattern(rng, depth - 1, inner_budget) for _ in range(rng.randint(1, 3))]
        base = "(?:" + "|".join(alts) + ")"
    elif r < 0.78:
        left = rng.choice(["", gen_pattern(rng, depth - 1, inner_budget)])
        right = rng.choice(["", gen_pattern(rng, depth - 1, inner_budget)])
        base = "(" + left + "|" + right + ")"
    else:
        return gen_pattern(rng, depth - 1, quant_budget) + gen_pattern(rng, depth - 1, quant_budget)
    if quantify:
        base += rng.choice(QUANTIFIERS)
        if rng.random() < 0.4:
            base += "?"
    return base


def gen_text(rng: random.Random, max_len: int = 6) -> str:
    return "".join(rng.choice(TEXT_ALPHABET) for _ in range(rng.randint(0, max_len)))


def describe(m, ngroups):
    if m is None:
        return None
    return (m.span(), m.groups(), tuple(m.span(i) for i in range(1, ngroups + 1)))


def compare(pattern: str, texts: list[str]) -> str | None:
    """Return a description of the first divergence from re, or None."""
    try:
        rp = re.compile(pattern)
    except re.error:
        try:
            miniregex.compile(pattern)
        except miniregex.RegexError:
            return None
        return f"re rejects {pattern!r} but miniregex accepted it"
    mp = miniregex.compile(pattern)
    if mp.groups != rp.groups:
        return f"group count differs for {pattern!r}: {mp.groups} != {rp.groups}"
    for text in texts:
        for op in ("match", "search", "fullmatch"):
            expected = describe(getattr(rp, op)(text), rp.groups)
            actual = describe(getattr(mp, op)(text), rp.groups)
            if expected != actual:
                return f"{op}({pattern!r}, {text!r}): re={expected} miniregex={actual}"
        expected = rp.findall(text)
        actual = mp.findall(text)
        if expected != actual:
            return f"findall({pattern!r}, {text!r}): re={expected} miniregex={actual}"
    return None


@pytest.mark.parametrize("seed", range(12))
def test_structured_fuzz(seed):
    rng = random.Random(1000 + seed)
    failures = []
    accepted = 0
    for _ in range(300):
        pattern = gen_pattern(rng, depth=3, quant_budget=2)
        texts = [gen_text(rng) for _ in range(3)]
        problem = compare(pattern, texts)
        if problem is not None:
            failures.append(problem)
        try:
            re.compile(pattern)
            accepted += 1
        except re.error:
            pass
    assert not failures, "\n".join(failures[:10])
    assert accepted > 200, "grammar is producing too many invalid patterns"


def test_rejected_patterns_are_generated_and_mirrored():
    """Some generated patterns are invalid (e.g. `^*`); both engines must reject them."""
    rng = random.Random(42)
    rejected = 0
    for _ in range(1500):
        pattern = gen_pattern(rng, depth=3, quant_budget=2)
        try:
            re.compile(pattern)
        except re.error:
            rejected += 1
            with pytest.raises(miniregex.RegexError):
                miniregex.compile(pattern)
    assert rejected > 20


@pytest.mark.filterwarnings("ignore::FutureWarning")  # re warns about e.g. "[[" in soup
@pytest.mark.parametrize("seed", range(4))
def test_junk_string_parity(seed):
    """Random character soup: accept/reject parity, and identical results when valid.

    miniregex may reject constructs it does not implement (lookarounds, named
    groups, possessive quantifiers, unsupported escapes); everything else must
    agree with re exactly.
    """
    rng = random.Random(500 + seed)
    soup = "ab()[]{}|*+?^$\\-,.0123:"
    texts = ["", "a", "ab", "a\n", ":1,0", "ba0"]
    failures = []
    for _ in range(3000):
        pattern = "".join(rng.choice(soup) for _ in range(rng.randint(0, 7)))
        try:
            re.compile(pattern)
            re_ok = True
        except (re.error, OverflowError):
            re_ok = False
        try:
            miniregex.compile(pattern)
            mr_ok = True
            reason = ""
        except miniregex.RegexError as exc:
            mr_ok = False
            reason = str(exc)
        if mr_ok and not re_ok:
            failures.append(f"re rejects {pattern!r} but miniregex accepted it")
        elif re_ok and not mr_ok:
            allowed = ("unsupported group", "bad escape", "possessive")
            if not any(key in reason for key in allowed):
                failures.append(f"re accepts {pattern!r} but miniregex raised: {reason}")
        elif re_ok and mr_ok:
            problem = compare(pattern, texts)
            if problem is not None:
                failures.append(problem)
    assert not failures, "\n".join(failures[:10])
