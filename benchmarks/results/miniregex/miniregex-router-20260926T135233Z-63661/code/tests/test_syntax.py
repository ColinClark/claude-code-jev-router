import pytest

from miniregex import RegexError
from miniregex import compile as mcompile

from ._compare import assert_same

TEXTS = ["", "a", "abc", "aaa", "a.b", "xyz\n", "a\nb", "12 ab_C\t-", "]^-[", "{}()|$*+?\\"]


def _cases(pairs):
    return [pytest.param(p, t, id=f"{p!r}|{t!r}") for p, ts in pairs for t in ts]


LITERALS = [
    ("abc", ["abc", "xabcx", "ab", ""]),
    ("a.c", ["abc", "a\nc", "ac", "a.c"]),
    (".", ["\n", "x", "\n\n", ""]),
    (".+", ["ab\ncd", "\n"]),
    (r"\.", ["a.b", "ab"]),
    (r"\\", ["a\\b", "ab"]),
    (r"\*\+\?", ["*+?", "x*+?y"]),
    (r"\(\)", ["()", "(x)"]),
    (r"\[\]", ["[]", "x[]"]),
    (r"\{\}", ["{}", "{1}"]),
    (r"\|", ["a|b", "ab"]),
    (r"\^\$", ["^$", "x^$y"]),
    (r"a\-b", ["a-b", "ab"]),
]

CLASSES = [
    (r"\d+", ["abc123def", "x", "٣4"]),
    (r"\D+", ["12ab34", "123"]),
    (r"\w+", ["  hello_world1 !", "!!", "éß"]),
    (r"\W+", ["ab  !? cd", "abc"]),
    (r"\s+", ["a \t\n\r\x0b\x0cb", "ab"]),
    (r"\S+", ["  ab  ", "   "]),
    (r"[\d]+", ["ab12c"]),
    (r"[\D]+", ["12ab"]),
    (r"[\w-]+", ["  foo-bar_1 !"]),
    (r"[\W]+", ["ab!?c"]),
    (r"[\s,]+", ["a, \tb"]),
    (r"[\S]+", ["  xy "]),
    (r"[^\d\s]+", ["12 ab 3c"]),
]

SETS = [
    ("[a-c]+", ["xxabcdd", "d"]),
    ("[a-cx-z0-2]+", ["--az1b3"]),
    ("[^a-c]+", ["abcdefabc", "abc"]),
    ("[-a]+", ["b-a-c"]),
    ("[a-]+", ["b-a-c"]),
    ("[^-a]+", ["-a-bc"]),
    ("[]a]+", ["x]a]y"]),
    ("[^]a]+", ["]]xyz]"]),
    (r"[\]\[]+", ["a[]b"]),
    (r"[\.\\]+", ["a.\\b"]),
    (r"[\-x]+", ["a-x-b"]),
    (r"[\^a]+", ["b^a"]),
    ("[^a]", ["\n", "a"]),
    ("[.]", ["a", "."]),
]

ANCHORS = [
    ("^a", ["a", "ba", "ab"]),
    ("a$", ["a", "a\n", "a\n\n", "ab", "ba"]),
    ("^$", ["", "\n", "\n\n", "a"]),
    ("^a$", ["a", "a\n", "a\n\n", "\na"]),
    ("$", ["abc", "abc\n"]),
    ("a|^b", ["cb", "bc"]),
    ("x*$", ["axx\n", "axx"]),
]

QUANTS = [
    ("a*", ["", "aaa", "baaa"]),
    ("a*?", ["aaa"]),
    ("a+", ["baaa", "b"]),
    ("a+?", ["aaa"]),
    ("a?", ["a", ""]),
    ("a??", ["a"]),
    ("a{2}", ["a", "aaa"]),
    ("a{2}?", ["aaa"]),
    ("a{2,}", ["a", "aaaaa"]),
    ("a{2,}?", ["aaaaa"]),
    ("a{1,3}", ["aaaaa", ""]),
    ("a{1,3}?", ["aaaaa"]),
    ("a{,2}", ["aaaaa", "b"]),
    ("a{,2}?", ["aaaaa"]),
    ("a{0}", ["aaa"]),
    (r"<.*>", ["<a><b>"]),
    (r"<.*?>", ["<a><b>"]),
    (r"(a*)(a*)", ["aaaa"]),
    (r"(a*?)(a*)", ["aaaa"]),
    (r"(a+)(a+)", ["aaaa"]),
    (r"(a+?)(a+)", ["aaaa"]),
    (r"(a?)(a?)a", ["aa"]),
    (r"(a??)(a?)a", ["aa"]),
    (r"(a{1,3})(a{1,3})", ["aaaa"]),
    (r"(a{1,3}?)(a{1,3})", ["aaaa"]),
    (r"(a{2,})(a*)", ["aaaaa"]),
    (r"(a{2,}?)(a*)", ["aaaaa"]),
    (r"(a{,2})(a*)", ["aaa"]),
    (r"(a{,2}?)(a*)", ["aaa"]),
    (r"(ab)*c", ["ababc", "c"]),
    (r"(ab)*?c", ["ababc"]),
    (r"(?:ab){2}", ["ababab"]),
    (r"(?:ab|a){1,3}?b", ["abab"]),
    (r"x{,}", ["x{,}"]),
    (r"a{", ["a{"]),
    (r"a{x}", ["a{x}"]),
]

GROUPS = [
    ("a|b|c", ["xcx", "d"]),
    ("ab|cd", ["xcd", "ab"]),
    ("a|ab", ["ab"]),
    ("(a)|(b)", ["b", "a", "c"]),
    ("(a|b)(c|d)", ["bd"]),
    ("((a)|(b))+", ["ab", "ba", "aab"]),
    ("(a|(b))+", ["ab", "ba"]),
    ("(a)*", ["aaa", ""]),
    ("(\\w)+", ["xyz"]),
    ("(?:(a)|(b))*", ["abab", "aba"]),
    ("(?:(a)|b)*", ["ab"]),
    ("((a)(b)?)+", ["aba", "abab"]),
    ("(a(b(c)))", ["abc"]),
    ("(?:a(b))(c)", ["abc"]),
    ("(?:a|b)(c)", ["bc"]),
    ("()", ["x"]),
    ("(a|)+b", ["aab"]),
    ("x(?:)y", ["xy"]),
    ("(a|b)*?c", ["abc"]),
]

FINDALL = [
    (r"\d+", ["a1b22c333", ""]),
    (r"(\d)\w", ["1a 2b 3"]),
    (r"(\d)(\w)", ["1a 2b 3"]),
    (r"(a)(b)?", ["aab"]),
    ("a*", ["baaac", ""]),
    ("a*?", ["aa"]),
    ("(a*)", ["bab"]),
    ("", ["abc"]),
    ("x?", ["axxb"]),
    ("(a)|b", ["ab"]),
    ("|a", ["aa"]),
    ("$", ["a\n"]),
    (r"\s*",["a b  c"]),
]

ALL = LITERALS + CLASSES + SETS + ANCHORS + QUANTS + GROUPS + FINDALL


@pytest.mark.parametrize("pattern,text", _cases(LITERALS))
def test_literals(pattern, text):
    assert_same(pattern, text)


@pytest.mark.parametrize("pattern,text", _cases(CLASSES))
def test_classes(pattern, text):
    assert_same(pattern, text)


@pytest.mark.parametrize("pattern,text", _cases(SETS))
def test_sets(pattern, text):
    assert_same(pattern, text)


@pytest.mark.parametrize("pattern,text", _cases(ANCHORS))
def test_anchors(pattern, text):
    assert_same(pattern, text)


@pytest.mark.parametrize("pattern,text", _cases(QUANTS))
def test_quantifiers(pattern, text):
    assert_same(pattern, text)


@pytest.mark.parametrize("pattern,text", _cases(GROUPS))
def test_groups_alternation(pattern, text):
    assert_same(pattern, text)


@pytest.mark.parametrize("pattern,text", _cases(FINDALL))
def test_findall(pattern, text):
    assert_same(pattern, text)


@pytest.mark.parametrize("pattern", [p for p, _ in ALL])
def test_common_texts(pattern):
    for t in TEXTS:
        assert_same(pattern, t)


def test_greedy_lazy_differ():
    assert mcompile("<.*>").search("<a><b>").group() == "<a><b>"
    assert mcompile("<.*?>").search("<a><b>").group() == "<a>"
    assert mcompile("(a+?)(a*)").fullmatch("aaa").groups() == ("a", "aa")


def test_last_iteration_wins():
    m = mcompile("(?:(a)|(b))+").fullmatch("ab")
    assert m.groups() == ("a", "b")
    m = mcompile("(\\d)+").fullmatch("123")
    assert m.group(1) == "3" and m.span(1) == (2, 3)


def test_match_api():
    m = mcompile("(a)(x)?(b)").search("zab")
    assert m.group() == "ab" and m.group(0) == "ab"
    assert m.groups() == ("a", None, "b")
    assert m.span() == (1, 3) and m.span(2) == (-1, -1) and m.span(3) == (2, 3)
    assert m.start() == 1 and m.end() == 3
    assert m.start(2) == -1 and m.end(2) == -1
    assert m.start(1) == 1 and m.end(1) == 2
    for bad in (4, -1):
        with pytest.raises(IndexError):
            m.group(bad)
        with pytest.raises(IndexError):
            m.span(bad)
        with pytest.raises(IndexError):
            m.start(bad)
        with pytest.raises(IndexError):
            m.end(bad)
    assert mcompile("a").search("a").groups() == ()


def test_match_vs_search():
    p = mcompile("b")
    assert p.match("ab") is None
    assert p.search("ab").span() == (1, 2)
    assert p.fullmatch("bb") is None


@pytest.mark.parametrize(
    "pattern",
    [
        "(a", "a)", "((a)", "(?:a", ")",
        "*", "+a", "?", "a**", "a|*", "(*)", "{2}", "^*",
        "[abc", "[", "[^", "[]", "[a-",
        "a{3,2}", r"\q", r"\y", "a\\",
        "(?P<x>a)", r"(a)\1", "(?=a)", "(?!a)", "(?<=a)b", "(?i)a",
        r"\b", r"\B", r"\A", r"\Z", "a*+", "a++",
        "[z-a]",
    ],
)
def test_invalid(pattern):
    with pytest.raises(RegexError):
        mcompile(pattern)
