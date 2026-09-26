"""Public API behaviour of Pattern and Match objects."""

from __future__ import annotations

import pytest

import miniregex
from miniregex import RegexError, compile


def test_exports() -> None:
    assert miniregex.compile is compile
    assert issubclass(RegexError, Exception)


def test_match_methods() -> None:
    p = compile(r"(\w+) (\w+)?(x)?")
    m = p.search("-- hello world")
    assert m is not None
    assert m.group() == "hello world"
    assert m.group(0) == "hello world"
    assert m.group(1) == "hello"
    assert m.group(1, 2) == ("hello", "world")
    assert m.groups() == ("hello", "world", None)
    assert m.groups("") == ("hello", "world", "")
    assert m.span() == (3, 14)
    assert m.span(1) == (3, 8)
    assert m.span(3) == (-1, -1)
    assert m.start(2) == 9
    assert m.end(2) == 14
    assert m.start(3) == -1
    assert m.end(3) == -1
    assert m.group(3) is None
    assert m[1] == "hello"


@pytest.mark.parametrize("bad", [4, -1, 100, "x", 1.5, None])
def test_invalid_group_index(bad: object) -> None:
    m = compile(r"(a)(b)?(c)?").match("a")
    assert m is not None
    with pytest.raises(IndexError):
        m.group(bad)
    with pytest.raises(IndexError):
        m.span(bad)
    with pytest.raises(IndexError):
        m.start(bad)
    with pytest.raises(IndexError):
        m.end(bad)


def test_match_is_anchored() -> None:
    p = compile("b")
    assert p.match("ab") is None
    assert p.search("ab") is not None
    assert p.fullmatch("b") is not None
    assert p.fullmatch("bb") is None


def test_fullmatch_backtracks_into_alternatives() -> None:
    m = compile("a|ab").fullmatch("ab")
    assert m is not None and m.span() == (0, 2)


def test_findall_shapes() -> None:
    assert compile("a").findall("aba") == ["a", "a"]
    assert compile("(a)b").findall("abab") == ["a", "a"]
    assert compile("(a)(b)?").findall("aba") == [("a", "b"), ("a", "")]
    assert compile("").findall("ab") == ["", "", ""]


def test_pattern_attributes() -> None:
    p = compile("(a)(?:b)(c)")
    assert p.pattern == "(a)(?:b)(c)"
    assert p.groups == 2
    assert [m.span() for m in p.finditer("abcabc")] == [(0, 3), (3, 6)]


def test_no_re_import_in_package() -> None:
    import pathlib

    root = pathlib.Path(miniregex.__file__).parent
    for path in root.glob("*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            assert stripped not in ("import re", "import regex")
            assert not stripped.startswith(("from re ", "import re ", "import re,"))
            assert not stripped.startswith(("from regex ", "import regex "))
