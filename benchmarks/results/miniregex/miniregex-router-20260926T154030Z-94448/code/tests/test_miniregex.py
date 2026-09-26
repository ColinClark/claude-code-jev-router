import ast
import pathlib
import random
import re

import pytest
from fuzzing import compare, random_pattern, random_text, too_slow_for_re

import miniregex
from miniregex import RegexError

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "miniregex"


def assert_same(pattern: str, *texts: str) -> None:
    problems = []
    for text in texts:
        problems += compare(pattern, text)
    assert not problems, "\n".join(problems)


# --- API ---------------------------------------------------------------------


def test_public_api():
    p = miniregex.compile(r"(\w+)@(\w+)\.com")
    m = p.search("mail: joe@example.com!")
    assert m is not None
    assert m.group() == "joe@example.com"
    assert m.group(0) == "joe@example.com"
    assert m.group(1) == "joe"
    assert m.group(2) == "example"
    assert m.group(1, 2) == ("joe", "example")
    assert m.groups() == ("joe", "example")
    assert m.span() == (6, 21)
    assert m.span(2) == (10, 17)
    assert m.start(1) == 6
    assert m.end(1) == 9
    assert m.start() == 6 and m.end() == 21
    assert p.groups == 2
    assert p.pattern == r"(\w+)@(\w+)\.com"


def test_match_is_anchored_at_start():
    p = miniregex.compile("b")
    assert p.match("abc") is None
    assert p.search("abc").span() == (1, 2)
    assert p.match("bc").span() == (0, 1)


def test_fullmatch_backtracks_to_reach_end():
    p = miniregex.compile("a|ab")
    assert p.match("ab").group() == "a"
    assert p.fullmatch("ab").group() == "ab"
    assert p.fullmatch("abc") is None


def test_unmatched_group_is_none():
    m = miniregex.compile("(a)|(b)").match("b")
    assert m.groups() == (None, "b")
    assert m.group(1) is None
    assert m.span(1) == (-1, -1)
    assert m.start(1) == -1 and m.end(1) == -1
    assert m.groups("x") == ("x", "b")


def test_bad_group_index():
    m = miniregex.compile("(a)").match("a")
    with pytest.raises(IndexError):
        m.group(2)
    with pytest.raises(IndexError):
        m.span(-1)


def test_findall_shapes():
    assert miniregex.compile(r"\d+").findall("a1b22c333") == ["1", "22", "333"]
    assert miniregex.compile(r"(\d)\d*").findall("a1b22c333") == ["1", "2", "3"]
    assert miniregex.compile(r"(\w)(\d)?").findall("a1b") == [("a", "1"), ("b", "")]
    assert miniregex.compile("x*").findall("axxb") == ["", "xx", "", ""]
    assert miniregex.compile("").findall("ab") == ["", "", ""]


def test_regex_error_is_value_error():
    assert issubclass(RegexError, ValueError)


def test_long_inputs_do_not_hit_recursion_limit():
    text = "ab" * 20000
    assert miniregex.compile("(ab)*").fullmatch(text).span(1) == (39998, 40000)
    assert miniregex.compile("(?:a|b)*c").search(text + "c").span() == (0, 40001)
    assert miniregex.compile("x+").search("y" * 5000 + "xxx").span() == (5000, 5003)


def test_implementation_does_not_use_re():
    for path in SRC.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in {"re", "regex", "sre_compile", "sre_parse", "_sre"}, path


# --- syntax, compared against re ----------------------------------------------

TEXTS = ["", "a", "ab", "abc", "aaa", "abab", "a.b", "a\nb", "a\n", "\n", "xyz", "a1 b2_", "{}[]", "a-b"]

PATTERNS = [
    # literals and escapes
    "abc",
    r"a\.b",
    r"\\",
    r"\*\+\?",
    r"\(\)\[\]\{\}",
    r"\|\^\$\-",
    r"a\nb",
    r"\t\x41B",
    "]",
    "}",
    "a{",
    "a{}",
    "a{x}",
    "a{1,x}",
    "a{ 1}",
    # dot and classes
    ".",
    "a.b",
    r"\d",
    r"\D+",
    r"\w+",
    r"\W",
    r"\s",
    r"\S+",
    # sets
    "[abc]",
    "[a-c]+",
    "[^a]",
    "[^a-b]+",
    "[-a]",
    "[a-]",
    "[]a]",
    "[^]a]",
    "[]]",
    r"[\]]",
    r"[\d.]+",
    r"[\w-]+",
    r"[^\s]",
    r"[\D]",
    r"[\-]",
    r"[a\-z]",
    r"[\\]",
    "[.]",
    "[$^]",
    "[a-b-c]",
    r"[\n]",
    r"[\x61-\x63]",
    # anchors
    "^a",
    "a$",
    "^$",
    "$",
    "^",
    "a^",
    "$a",
    r"b$\n?",
    r"a\n$",
    r"\Aa",
    r"b\Z",
    "(^a|b$)",
    # quantifiers
    "a*",
    "a+",
    "a?",
    "a*?",
    "a+?",
    "a??",
    "a{2}",
    "a{2,}",
    "a{1,2}",
    "a{,2}",
    "a{0}",
    "a{,}",
    "a{2}?",
    "a{1,}?",
    "a{,2}?",
    "(ab)+",
    "(ab)*?b",
    "(a|b){2,3}",
    "(a|b){2,3}?",
    # alternation and groups
    "a|b",
    "a|ab|abc",
    "|a",
    "a|",
    "(a)(b)?",
    "(a|b)*",
    "((a)|b)+",
    "(?:a|b)+",
    "(?:)",
    "()",
    "(a*)*",
    "(a*)+",
    "(a|)*",
    "(|a)*",
    "(a?){2,}",
    "(a*?)*?b",
    "(?:(a)|b)*",
    "(?:(a)|(b))*",
    "((a)|b)*?c",
    "(a|ab)(c|bcd)?",
    "(.*)(b)",
    "(.*?)(b)",
    r"(\w+)\s(\w+)",
    "(a)|(b)|(c)",
    "((a|b)c|a)*",
    "(?:(a+)|(b+))*",
    "(a|b)*?$",
    "((a)*)*",
    "(()|a)+",
    "(a|b|)+?b",
    "(^|a)+",
    "($|a)*",
    "(a(b)?)+",
]


@pytest.mark.parametrize("pattern", PATTERNS)
def test_matches_re(pattern):
    assert_same(pattern, *TEXTS)


# --- errors -------------------------------------------------------------------

INVALID = [
    "(",
    "(a",
    ")",
    "a)",
    "[",
    "[a",
    "[]",
    "[^]",
    "[b-a]",
    r"[\d-z]",
    r"[a-\w]",
    "*",
    "+a",
    "?",
    "a**",
    "a*+*",
    "a+*",
    "a???",
    "a{2}{3}",
    "{1}",
    "(*)",
    "(|*)",
    "^*",
    "$+",
    "a{3,2}",
    "\\",
    r"a\q",
    r"\xZ1",
]


@pytest.mark.parametrize("pattern", INVALID)
def test_invalid_patterns(pattern):
    with pytest.raises(re.error):
        re.compile(pattern)
    with pytest.raises(RegexError):
        miniregex.compile(pattern)


@pytest.mark.parametrize("pattern", ["(?P<x>a)", "(?=a)", r"(a)\1", r"\b"])
def test_unsupported_syntax_raises(pattern):
    with pytest.raises(RegexError):
        miniregex.compile(pattern)


# --- fuzzing against re ---------------------------------------------------------


# Random patterns occasionally backtrack exponentially (in re as well). Cases
# that already take re this long would take the pure-Python engine seconds.
PATHOLOGICAL_RE_SECONDS = 0.0005


@pytest.mark.parametrize("seed", range(20))
def test_fuzz_against_re(seed):
    rng = random.Random(seed)
    problems = []
    checked = 0
    for _ in range(300):
        pattern = random_pattern(rng)
        for _ in range(4):
            text = random_text(rng)
            if too_slow_for_re(pattern, text, PATHOLOGICAL_RE_SECONDS):
                continue
            checked += 1
            problems += compare(pattern, text)
    assert checked > 1100
    assert not problems, "\n".join(problems[:20])
