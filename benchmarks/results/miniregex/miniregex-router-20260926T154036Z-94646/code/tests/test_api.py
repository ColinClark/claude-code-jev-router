import pytest

from miniregex import RegexError, compile


def test_fullmatch_match_search_basic():
    p = compile(r"a(b+)c")
    assert p.fullmatch("abbc").group(1) == "bb"
    assert p.fullmatch("abbcx") is None
    assert p.match("abbcx").span() == (0, 4)
    assert p.match("xabbc") is None
    assert p.search("xxabcx").span() == (2, 5)
    assert p.search("xyz") is None


def test_match_accessors():
    m = compile(r"(\d+)-(x)?(\w+)").search("id: 42-abc!")
    assert m.group() == m.group(0) == m[0] == "42-abc"
    assert m.group(1, 3) == ("42", "abc")
    assert m.groups() == ("42", None, "abc")
    assert m.groups("") == ("42", "", "abc")
    assert m.span(1) == (4, 6)
    assert m.span(2) == (-1, -1)
    assert m.start(2) == -1 and m.end(2) == -1
    assert m.start() == 4 and m.end() == 10
    assert m.start(3) == 7 and m.end(3) == 10


def test_group_index_errors():
    m = compile(r"(a)").match("a")
    with pytest.raises(IndexError):
        m.group(2)
    with pytest.raises(IndexError):
        m.span(-1)


def test_findall_shapes():
    assert compile(r"\d+").findall("a1b22c333") == ["1", "22", "333"]
    assert compile(r"(\d)\d*").findall("a1b22c333") == ["1", "2", "3"]
    assert compile(r"(\w)(\d)?").findall("a1b") == [("a", "1"), ("b", "")]
    assert compile(r"x*").findall("axxb") == ["", "xx", "", ""]
    assert compile(r"q").findall("abc") == []


def test_pattern_attributes():
    p = compile(r"(a)(?:b)(c)")
    assert p.groups == 2
    assert p.pattern == r"(a)(?:b)(c)"


def test_last_iteration_group_value():
    m = compile(r"(?:(\w)-)+").match("a-b-c-")
    assert m.group(1) == "c"
    assert m.span(1) == (4, 5)


def test_dollar_before_final_newline():
    assert compile(r"a$").search("a\n").span() == (0, 1)
    assert compile(r"a$").search("a\n\n") is None
    assert compile(r"$").findall("a\n") == ["", ""]


def test_dot_excludes_newline():
    assert compile(r".").fullmatch("\n") is None
    assert compile(r"[^a]").fullmatch("\n") is not None


def test_long_input_does_not_overflow():
    text = "ab" * 20000
    assert compile(r"(?:ab)*").fullmatch(text) is not None
    assert compile(r"(a|b)*c").search(text[:3000]) is None
    assert compile(r".*").match(text).end() == len(text)


@pytest.mark.parametrize(
    "pattern",
    [
        "(",
        ")",
        "a)",
        "(?:a",
        "[",
        "[]",
        "[a",
        "[z-a]",
        r"[a-\d]",
        r"[\w-z]",
        "*",
        "a**",
        "a*?*",
        "^*",
        "$+",
        "|?",
        "(*)",
        "{1}",
        "a{2,1}",
        "a{1}{2}",
        "\\",
        r"\q",
        r"[\q]",
        "(?P<x>a)",
    ],
)
def test_invalid_patterns(pattern):
    with pytest.raises(RegexError):
        compile(pattern)


def test_regex_error_is_value_error():
    assert issubclass(RegexError, ValueError)
