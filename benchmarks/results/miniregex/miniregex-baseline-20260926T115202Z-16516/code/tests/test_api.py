"""Public API behaviour."""

from __future__ import annotations

import ast
import pathlib

import pytest

import miniregex
from miniregex import RegexError, compile


def test_exports() -> None:
    assert miniregex.compile is compile
    assert issubclass(RegexError, Exception)


def test_match_object() -> None:
    m = compile(r"(\w+)@(\w+)?(x)?").search("mail bob@ex now")
    assert m is not None
    assert m.group() == m.group(0) == "bob@ex"
    assert m.group(1) == "bob"
    assert m.group(1, 2) == ("bob", "ex")
    assert m.group(3) is None
    assert m[2] == "ex"
    assert m.groups() == ("bob", "ex", None)
    assert m.groups("") == ("bob", "ex", "")
    assert m.span() == (5, 11)
    assert m.span(1) == (5, 8)
    assert m.span(3) == (-1, -1)
    assert (m.start(), m.end()) == (5, 11)
    assert (m.start(2), m.end(2)) == (9, 11)
    assert m.start(3) == m.end(3) == -1
    assert m.string == "mail bob@ex now"
    assert "bob@ex" in repr(m)


def test_no_such_group() -> None:
    m = compile("(a)").match("a")
    assert m is not None
    for bad in (2, -1):
        with pytest.raises(IndexError):
            m.group(bad)
        with pytest.raises(IndexError):
            m.span(bad)


def test_match_is_anchored_at_start_only() -> None:
    p = compile("ab")
    assert p.match("abc") is not None
    assert p.match("cab") is None
    assert p.fullmatch("abc") is None
    assert p.fullmatch("ab") is not None
    assert p.search("cab").span() == (1, 3)


def test_fullmatch_backtracks_to_consume_everything() -> None:
    assert compile("a|ab").fullmatch("ab").group() == "ab"
    assert compile("a*?").fullmatch("aaa").span() == (0, 3)
    assert compile("(a+?)(a*?)").fullmatch("aaa").groups() == ("a", "aa")


def test_findall_shapes() -> None:
    assert compile(r"\d+").findall("a1b22c333") == ["1", "22", "333"]
    assert compile(r"(\d)\d*").findall("a1b22c333") == ["1", "2", "3"]
    assert compile(r"(\w)(\d)?").findall("a1b") == [("a", "1"), ("b", "")]
    assert compile("a*").findall("baac") == ["", "aa", "", ""]
    assert compile("a*|b").findall("ab") == ["a", "", "b", ""]
    assert compile("x").findall("") == []


def test_pattern_attributes() -> None:
    p = compile("(a)(?:b)(c)")
    assert p.pattern == "(a)(?:b)(c)"
    assert p.groups == 2


@pytest.mark.parametrize(
    "pattern",
    [
        "(",
        ")",
        "a)",
        "(a",
        "(?:a",
        "[",
        "[a",
        "[]",
        "[^]",
        "[a-",
        "[z-a]",
        r"[\d-z]",
        r"[a-\w]",
        "*",
        "+a",
        "?",
        "a**",
        "a*+b",
        "a{2}{3}",
        "a??+",
        "^*",
        "$+",
        "(?:^)?*",
        "a{3,2}",
        "{1}",
        "|*",
        "(*)",
        "\\",
        "a\\",
        r"\q",
        r"\1",
        "(?=a)",
        "(?P<n>a)",
        "(?i)a",
        r"\b",
        r"\A",
        r"\x41",
        "a{4294967295}",
    ],
)
def test_invalid_or_unsupported_patterns(pattern: str) -> None:
    with pytest.raises(RegexError):
        compile(pattern)


def test_regex_error_has_position() -> None:
    with pytest.raises(RegexError) as info:
        compile("ab)")
    assert info.value.pos == 2
    assert info.value.pattern == "ab)"


def test_long_inputs_do_not_hit_recursion_limit() -> None:
    text = "ab" * 20000
    m = compile("(?:(a)(b))*").fullmatch(text)
    assert m is not None
    assert m.span(1) == (len(text) - 2, len(text) - 1)
    assert compile("(a|b)*c").search(text + "c").span() == (0, len(text) + 1)
    assert compile(".*?c").search("x" * 20000 + "c") is not None


def test_implementation_does_not_use_regex_libraries() -> None:
    package = pathlib.Path(miniregex.__file__).parent
    forbidden = {"re", "regex", "sre_compile", "sre_parse", "_sre"}
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {(node.module or "").split(".")[0]} if node.level == 0 else set()
            else:
                continue
            assert not names & forbidden, f"{path.name} imports {names & forbidden}"
