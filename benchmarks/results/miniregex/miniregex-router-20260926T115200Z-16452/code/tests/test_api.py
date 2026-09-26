"""Public API behaviour: compile, Pattern, Match, findall shapes, errors."""

from __future__ import annotations

import pathlib
import re

import pytest

import miniregex
from miniregex import Match, Pattern, RegexError, compile

SRC_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "miniregex"


def test_public_names() -> None:
    assert callable(compile)
    assert issubclass(RegexError, Exception)
    assert isinstance(compile("a"), Pattern)
    assert isinstance(compile("a").match("a"), Match)
    assert "compile" in miniregex.__all__ and "RegexError" in miniregex.__all__


def test_no_regex_library_imported_in_src() -> None:
    """A5: the implementation must not import re, sre_*, _sre or regex."""
    forbidden = ("re", "sre_parse", "sre_compile", "sre_constants", "_sre", "regex")
    for path in SRC_DIR.rglob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            for name in forbidden:
                assert not stripped.startswith(f"import {name}"), f"{path}:{lineno}: {line}"
                assert not stripped.startswith(f"from {name} "), f"{path}:{lineno}: {line}"
                assert not stripped.startswith(f"from {name}."), f"{path}:{lineno}: {line}"


def test_pattern_attributes() -> None:
    p = compile(r"(a)(?:b)(c)?")
    assert p.pattern == r"(a)(?:b)(c)?"
    assert p.groups == 2
    assert "(a)(?:b)(c)?" in repr(p)


def test_compile_type_errors() -> None:
    with pytest.raises(TypeError):
        compile(b"a")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        compile("a").match(b"a")  # type: ignore[arg-type]


def test_invalid_pattern_raises_regex_error() -> None:
    with pytest.raises(RegexError):
        compile("(")
    with pytest.raises(RegexError):
        compile("*")


def test_match_is_anchored_at_start_and_search_is_not() -> None:
    p = compile("b+")
    assert p.match("abb") is None
    m = p.search("abb")
    assert m is not None
    assert m.span() == (1, 3)
    assert m.group() == "bb"
    assert p.fullmatch("bb") is not None
    assert p.fullmatch("bba") is None
    assert p.match("bba").span() == (0, 2)


def test_fullmatch_backtracks_to_consume_everything() -> None:
    assert compile("a|ab").fullmatch("ab").span() == (0, 2)
    assert compile("a*?").fullmatch("aaa").span() == (0, 3)
    assert compile("(a|ab)(c|bcd)(d*)").fullmatch("abcd").groups() == ("a", "bcd", "")


def test_match_accessors() -> None:
    m = compile(r"(a+)(b)?(c)").match("aac")
    assert m is not None
    assert m.group() == "aac"
    assert m.group(0) == "aac"
    assert m.group(1) == "aa"
    assert m.group(2) is None
    assert m.group(3) == "c"
    assert m.group(1, 3) == ("aa", "c")
    assert m.group(0, 2) == ("aac", None)
    assert m[1] == "aa"
    assert m[2] is None
    assert m.groups() == ("aa", None, "c")
    assert m.groups(default="") == ("aa", "", "c")
    assert m.span() == (0, 3)
    assert m.span(1) == (0, 2)
    assert m.span(2) == (-1, -1)
    assert m.span(3) == (2, 3)
    assert (m.start(), m.end()) == (0, 3)
    assert (m.start(1), m.end(1)) == (0, 2)
    assert (m.start(2), m.end(2)) == (-1, -1)
    assert m.string == "aac"
    assert m.re.pattern == r"(a+)(b)?(c)"
    assert m.regs == ((0, 3), (0, 2), (-1, -1), (2, 3))
    assert m.lastindex == 3
    assert m.lastgroup is None
    assert "span=(0, 3)" in repr(m) and "match='aac'" in repr(m)


def test_lastindex_matches_re() -> None:
    for pattern, text in [
        ("(a)(b)?", "a"),
        ("(a)|(b)", "b"),
        ("((a))", "a"),
        ("a", "a"),
        ("(a)*", ""),
    ]:
        ref = re.match(pattern, text)
        mini = compile(pattern).match(text)
        assert mini is not None and ref is not None
        assert mini.lastindex == ref.lastindex, pattern


@pytest.mark.parametrize("bad", [-1, 2, 3, 100, "name", "1", None, 1.5, (1,)])
def test_invalid_group_index_raises_index_error(bad) -> None:
    m = compile("(a)").match("a")
    assert m is not None
    with pytest.raises(IndexError):
        m.group(bad)
    with pytest.raises(IndexError):
        m.span(bad)
    with pytest.raises(IndexError):
        m.start(bad)
    with pytest.raises(IndexError):
        m.end(bad)
    with pytest.raises(IndexError):
        m[bad]
    # re raises IndexError for these too
    ref = re.match("(a)", "a")
    with pytest.raises(IndexError):
        ref.group(bad)


def test_findall_shapes() -> None:
    assert compile("a+").findall("aa b aaa") == ["aa", "aaa"]
    assert compile("(a)b").findall("ab ab") == ["a", "a"]
    assert compile("(a)(b)").findall("ab ab") == [("a", "b"), ("a", "b")]
    # non-participating groups become ''
    assert compile("(a)|(b)").findall("ab") == [("a", ""), ("", "b")]
    assert compile("(a)|b").findall("ab") == ["a", ""]
    assert compile("x").findall("abc") == []


def test_findall_empty_match_advancing_rules() -> None:
    # Matches re in Python 3.7+: an empty match may directly follow a non-empty one.
    assert compile("a*").findall("baaab") == ["", "aaa", "", ""]
    assert compile("").findall("abc") == ["", "", "", ""]
    assert compile("a*?").findall("aa") == ["", "a", "", "a", ""]
    assert compile("x*").findall("axbx") == ["", "x", "", "x", ""]
    assert compile("$").findall("a\n") == ["", ""]
    assert [m.span() for m in compile("a*").finditer("baaab")] == [(0, 0), (1, 4), (4, 4), (5, 5)]


def test_finditer_yields_match_objects() -> None:
    matches = list(compile("(a)(b)?").finditer("aab"))
    assert [m.groups() for m in matches] == [("a", None), ("a", "b")]
    assert [m.span() for m in matches] == [(0, 1), (1, 3)]


def test_module_level_convenience_functions() -> None:
    assert miniregex.match("a", "ab").span() == (0, 1)
    assert miniregex.fullmatch("a", "ab") is None
    assert miniregex.search("b", "ab").span() == (1, 2)
    assert miniregex.findall("a", "aba") == ["a", "a"]


def test_empty_pattern_and_empty_text() -> None:
    p = compile("")
    assert p.fullmatch("").span() == (0, 0)
    assert p.match("abc").span() == (0, 0)
    assert p.search("").span() == (0, 0)
    assert compile("a").search("") is None
    assert compile("a?").fullmatch("").span() == (0, 0)
