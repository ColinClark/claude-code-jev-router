"""Public ``Pattern`` / ``Match`` objects and ``compile``."""

from __future__ import annotations

import sys
from contextlib import contextmanager

from ._matcher import build
from ._parser import RegexError, parse

__all__ = ["Match", "Pattern", "RegexError", "compile"]

# The matcher recurses roughly a few frames per consumed character in the worst
# case. Pure-Python calls don't consume the C stack on 3.12+, so a generous
# limit is safe.
_FRAMES_PER_CHAR = 8
_BASE_FRAMES = 2000


@contextmanager
def _recursion_room(text_len: int):
    needed = _BASE_FRAMES + _FRAMES_PER_CHAR * text_len
    old = sys.getrecursionlimit()
    if needed > old:
        sys.setrecursionlimit(needed)
    try:
        yield
    finally:
        if needed > old:
            sys.setrecursionlimit(old)


class Match:
    """Result of a successful match; mirrors the core of ``re.Match``."""

    __slots__ = ("_spans", "string", "re", "pos", "endpos")

    def __init__(self, pattern: Pattern, string: str, spans: list, pos: int, endpos: int):
        self.re = pattern
        self.string = string
        self._spans = spans  # index 0 is the whole match
        self.pos = pos
        self.endpos = endpos

    def _index(self, n) -> int:
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n < len(self._spans):
            raise IndexError("no such group")
        return n

    def _group(self, n):
        span = self._spans[self._index(n)]
        if span is None:
            return None
        return self.string[span[0] : span[1]]

    def group(self, *args):
        if not args:
            return self._group(0)
        if len(args) == 1:
            return self._group(args[0])
        return tuple(self._group(n) for n in args)

    def __getitem__(self, n):
        return self._group(n)

    def groups(self, default=None) -> tuple:
        return tuple(
            default if span is None else self.string[span[0] : span[1]] for span in self._spans[1:]
        )

    def span(self, n: int = 0) -> tuple[int, int]:
        span = self._spans[self._index(n)]
        return (-1, -1) if span is None else span

    def start(self, n: int = 0) -> int:
        return self.span(n)[0]

    def end(self, n: int = 0) -> int:
        return self.span(n)[1]

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self.group()!r}>"


class Pattern:
    """A compiled pattern; mirrors the core of ``re.Pattern``."""

    def __init__(self, pattern: str):
        ast, ngroups = parse(pattern)
        self.pattern = pattern
        self.groups = ngroups
        self._matcher = build(ast)

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"

    def _match_at(self, s: str, start: int, full: bool, must_advance: bool) -> Match | None:
        caps: list = [None] * (self.groups + 1)
        n = len(s)
        result: list = []

        def accept(j: int) -> bool:
            if full and j != n:
                return False
            if must_advance and j == start:
                return False
            caps[0] = (start, j)
            result.append(list(caps))
            return True

        if self._matcher(s, start, caps, accept):
            return Match(self, s, result[0], 0, n)
        return None

    def _search(self, s: str, pos: int, must_advance: bool = False) -> Match | None:
        with _recursion_room(len(s)):
            for start in range(pos, len(s) + 1):
                m = self._match_at(s, start, False, must_advance and start == pos)
                if m is not None:
                    return m
        return None

    def match(self, string: str) -> Match | None:
        with _recursion_room(len(string)):
            return self._match_at(string, 0, False, False)

    def fullmatch(self, string: str) -> Match | None:
        with _recursion_room(len(string)):
            return self._match_at(string, 0, True, False)

    def search(self, string: str) -> Match | None:
        return self._search(string, 0)

    def finditer(self, string: str):
        pos = 0
        must_advance = False
        while pos <= len(string):
            m = self._search(string, pos, must_advance)
            if m is None:
                return
            yield m
            start, end = m.span()
            must_advance = start == end
            pos = end

    def findall(self, string: str) -> list:
        out: list = []
        for m in self.finditer(string):
            if self.groups == 0:
                out.append(m.group())
            elif self.groups == 1:
                out.append(m.groups("")[0])
            else:
                out.append(m.groups(""))
        return out


def compile(pattern: str) -> Pattern:  # noqa: A001 - mirrors re.compile
    """Compile ``pattern`` into a :class:`Pattern`; raises :class:`RegexError`."""
    if isinstance(pattern, Pattern):
        return pattern
    return Pattern(pattern)
