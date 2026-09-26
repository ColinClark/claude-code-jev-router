import pathlib

import pytest

import miniregex
from miniregex import RegexError, compile


def test_public_api():
    assert miniregex.compile is compile
    assert issubclass(RegexError, Exception)
    p = compile("a(b)")
    assert isinstance(p, miniregex.Pattern)
    assert p.pattern == "a(b)"
    assert p.groups == 1


def test_no_match_returns_none():
    p = compile("abc")
    assert p.match("xabc") is None
    assert p.fullmatch("abcd") is None
    assert p.search("ab") is None
    assert p.findall("xyz") == []


def test_match_is_anchored_at_start_only():
    p = compile("ab")
    assert p.match("abc").span() == (0, 2)
    assert p.match("cab") is None
    assert p.search("cab").span() == (1, 3)


def test_fullmatch_backtracks_to_reach_end():
    m = compile("(a|ab)(c|bcd)?").fullmatch("abcd")
    assert m.groups() == ("a", "bcd")


def test_match_accessors():
    m = compile(r"(\w+)@(\w+)(x)?").search("mail: bob@example !")
    assert m.group() == "bob@example"
    assert m.group(0) == "bob@example"
    assert m.group(1) == "bob"
    assert m.group(2) == "example"
    assert m.group(3) is None
    assert m.group(1, 2) == ("bob", "example")
    assert m[1] == "bob"
    assert m.groups() == ("bob", "example", None)
    assert m.groups("") == ("bob", "example", "")
    assert m.span() == (6, 17)
    assert m.span(2) == (10, 17)
    assert m.span(3) == (-1, -1)
    assert m.start() == 6 and m.end() == 17
    assert m.start(1) == 6 and m.end(1) == 9
    assert m.start(3) == -1 and m.end(3) == -1
    assert m.string == "mail: bob@example !"
    assert "bob@example" in repr(m)


@pytest.mark.parametrize("bad", [-1, 4, 100, "1", None, 1.0])
def test_bad_group_index(bad):
    m = compile("(a)(b)(c)").match("abc")
    with pytest.raises(IndexError):
        m.group(bad)
    with pytest.raises(IndexError):
        m.span(bad)


def test_findall_shapes():
    assert compile(r"\d+").findall("a1b22c333") == ["1", "22", "333"]
    assert compile(r"(\d)\d*").findall("a1b22c333") == ["1", "2", "3"]
    assert compile(r"(\d)(x)?").findall("1x2") == [("1", "x"), ("2", "")]
    assert compile("").findall("ab") == ["", "", ""]
    assert compile("a*").findall("baac") == ["", "aa", "", ""]


def test_pattern_is_reusable():
    p = compile("(a+)")
    assert p.match("aaa").group(1) == "aaa"
    assert p.match("a").group(1) == "a"
    assert p.search("xa").span(1) == (1, 2)


def test_type_errors():
    with pytest.raises(TypeError):
        compile(b"a")
    with pytest.raises(TypeError):
        compile("a").match(b"a")


def test_long_text_does_not_overflow_the_stack():
    n = 20000
    assert compile("(ab)*").fullmatch("ab" * n).span(1) == (2 * n - 2, 2 * n)
    assert compile("(?:a|b)*c").match("ab" * n + "c").end() == 2 * n + 1
    assert compile("a*?b").search("a" * n + "b").span() == (0, n + 1)
    assert len(compile(r"\w").findall("x" * n)) == n


def test_implementation_does_not_use_re():
    import ast

    banned = {"re", "regex", "sre_compile", "sre_parse", "sre_constants", "_sre"}
    src = pathlib.Path(miniregex.__file__).parent
    for path in src.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in banned, f"{path.name} imports {name}"
