import pytest

import miniregex
from miniregex import RegexError, compile


def test_public_api():
    assert miniregex.compile is compile
    assert issubclass(RegexError, Exception)
    p = compile("a")
    assert isinstance(p, miniregex.Pattern)
    assert p.pattern == "a"


def test_fullmatch_match_search():
    p = compile(r"b+")
    assert p.fullmatch("bbb").span() == (0, 3)
    assert p.fullmatch("bba") is None
    assert p.match("bba").group() == "bb"
    assert p.match("abb") is None
    m = p.search("aabbbc")
    assert m.group() == "bbb"
    assert m.span() == (2, 5)
    assert (m.start(), m.end()) == (2, 5)
    assert p.search("aaa") is None


def test_fullmatch_backtracks_to_consume_all():
    assert compile("a|ab").fullmatch("ab").group() == "ab"
    assert compile("a|ab").match("ab").group() == "a"
    assert compile("a*?").fullmatch("aaa").group() == "aaa"


def test_groups_and_spans():
    m = compile(r"(\w+)@(\w+)(\.com)?").search("x bob@example y")
    assert m.group() == "bob@example"
    assert m.group(0) == "bob@example"
    assert m.group(1) == "bob"
    assert m.group(2) == "example"
    assert m.group(3) is None
    assert m.group(1, 2) == ("bob", "example")
    assert m.groups() == ("bob", "example", None)
    assert m.groups("") == ("bob", "example", "")
    assert m.span(1) == (2, 5)
    assert m.span(3) == (-1, -1)
    assert m.start(3) == -1 and m.end(3) == -1
    assert m[2] == "example"


def test_last_iteration_wins():
    m = compile(r"(?:(\d)|([a-z]))+").fullmatch("1a2b3")
    assert m.groups() == ("3", "b")
    assert m.span(1) == (4, 5)
    assert m.span(2) == (3, 4)


def test_no_such_group():
    m = compile("(a)").match("a")
    with pytest.raises(IndexError):
        m.group(2)
    with pytest.raises(IndexError):
        m.span(-1)


def test_findall_shapes():
    assert compile(r"\d+").findall("a1b22c333") == ["1", "22", "333"]
    assert compile(r"(\d)\d*").findall("a1b22c333") == ["1", "2", "3"]
    assert compile(r"(\d)(x)?").findall("1x2") == [("1", "x"), ("2", "")]
    assert compile(r"a*").findall("baac") == ["", "aa", "", ""]
    assert compile(r"a*?").findall("aa") == ["", "a", "", "a", ""]
    assert compile(r"x").findall("") == []


def test_finditer():
    spans = [m.span() for m in compile(r"\w+").finditer("ab cd  e")]
    assert spans == [(0, 2), (3, 5), (7, 8)]


def test_dollar_before_final_newline():
    assert compile("a$").search("a\n").span() == (0, 1)
    assert compile("a$").search("a\n\n") is None
    assert compile("^$").findall("\n") == [""]
    assert compile("$").findall("a\n") == ["", ""]


def test_dot_excludes_newline():
    assert compile(".").fullmatch("\n") is None
    assert compile("[^a]").fullmatch("\n") is not None


def test_long_input_does_not_overflow():
    text = "ab" * 5000
    assert compile("(?:ab)*").fullmatch(text).end() == len(text)
    assert compile("(ab)+$").search(text).group(1) == "ab"
    assert compile("a*").match("a" * 100_000).end() == 100_000


def test_type_errors():
    with pytest.raises(TypeError):
        compile(b"a")
    with pytest.raises(TypeError):
        compile("a").search(b"a")


def test_implementation_does_not_use_re():
    import ast
    from pathlib import Path

    for path in Path(miniregex.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in {"re", "regex", "sre_compile", "sre_parse"}, path
