"""Public ``Pattern`` and ``Match`` objects and the ``compile`` entry point."""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from .matcher import Context, build, count_nodes
from .parser import parse

_limit_lock = threading.Lock()


@contextmanager
def _recursion_budget(needed: int) -> Iterator[None]:
    """Temporarily raise the recursion limit so deep backtracking can proceed.

    The matcher recurses once per consumed element, so long subjects need more
    than the default 1000 frames. The previous limit is restored afterwards
    (unless someone else changed it in the meantime).
    """
    with _limit_lock:
        old = sys.getrecursionlimit()
        target = max(old, needed)
        if target != old:
            sys.setrecursionlimit(target)
    try:
        yield
    finally:
        with _limit_lock:
            if target != old and sys.getrecursionlimit() == target:
                sys.setrecursionlimit(old)


class Match:
    """Result of a successful match; API mirrors ``re.Match``."""

    __slots__ = ("_text", "_marks", "_ngroups", "re", "string", "pos", "endpos")

    def __init__(self, pattern: Pattern, text: str, start: int, end: int, marks: list[int]):
        marks = list(marks)
        marks[0] = start
        marks[1] = end
        self._marks = marks
        self._text = text
        self._ngroups = pattern.groups
        self.re = pattern
        self.string = text
        self.pos = 0
        self.endpos = len(text)

    def _index(self, n: int) -> int:
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= self._ngroups:
            raise IndexError("no such group")
        return n

    def span(self, n: int = 0) -> tuple[int, int]:
        n = self._index(n)
        s, e = self._marks[2 * n], self._marks[2 * n + 1]
        if s < 0 or e < 0:
            return (-1, -1)
        return (s, e)

    def start(self, n: int = 0) -> int:
        return self.span(n)[0]

    def end(self, n: int = 0) -> int:
        return self.span(n)[1]

    def _group(self, n: int) -> str | None:
        s, e = self.span(n)
        if s < 0:
            return None
        return self._text[s:e]

    def group(self, *args: int) -> str | None | tuple[str | None, ...]:
        if not args:
            return self._group(0)
        if len(args) == 1:
            return self._group(args[0])
        return tuple(self._group(n) for n in args)

    def __getitem__(self, n: int) -> str | None:
        return self._group(n)

    def groups(self, default: str | None = None) -> tuple[str | None, ...]:
        out = []
        for n in range(1, self._ngroups + 1):
            g = self._group(n)
            out.append(default if g is None else g)
        return tuple(out)

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self._group(0)!r}>"


class Pattern:
    """A compiled regular expression; API mirrors a subset of ``re.Pattern``."""

    __slots__ = ("pattern", "groups", "_fn", "_size")

    def __init__(self, pattern: str) -> None:
        ast, ngroups = parse(pattern)
        self.pattern = pattern
        self.groups = ngroups
        self._fn = build(ast)
        self._size = count_nodes(ast)

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"

    def _budget(self, text: str) -> int:
        return sys.getrecursionlimit() + (len(text) + 1) * (4 * self._size + 8) + 1000

    def _try(self, ctx: Context, start: int, require_end: bool, forbid_empty: bool) -> bool:
        n = ctx.n

        def final(j: int) -> bool:
            if require_end and j != n:
                return False
            if forbid_empty and j == start:
                return False
            ctx.end = j
            return True

        return self._fn(ctx, start, final)

    def _search_from(
        self, text: str, pos: int, *, anchored: bool, full: bool, must_advance: bool = False
    ) -> Match | None:
        if not isinstance(text, str):
            raise TypeError("expected a str")
        ctx = Context(text, self.groups)
        last = pos if anchored else len(text)
        start = pos
        while start <= last:
            if self._try(ctx, start, full, must_advance and start == pos):
                return Match(self, text, start, ctx.end, ctx.marks)
            start += 1
        return None

    def _run(self, text: str, **kw: bool) -> Match | None:
        with _recursion_budget(self._budget(text)):
            return self._search_from(text, 0, **kw)

    def fullmatch(self, text: str) -> Match | None:
        return self._run(text, anchored=True, full=True)

    def match(self, text: str) -> Match | None:
        return self._run(text, anchored=True, full=False)

    def search(self, text: str) -> Match | None:
        return self._run(text, anchored=False, full=False)

    def finditer(self, text: str) -> Iterator[Match]:
        """Yield successive non-overlapping matches, like ``re.finditer``."""
        return iter(self._find_all_matches(text))

    def _find_all_matches(self, text: str) -> list[Match]:
        results: list[Match] = []
        with _recursion_budget(self._budget(text)):
            pos = 0
            must_advance = False
            while pos <= len(text):
                m = self._search_from(
                    text, pos, anchored=False, full=False, must_advance=must_advance
                )
                if m is None:
                    break
                results.append(m)
                s, e = m.span()
                pos = e
                must_advance = s == e
        return results

    def findall(self, text: str) -> list[str | tuple[str, ...]]:
        """Like ``re.findall``: strings for 0/1 groups, tuples for 2+ groups.

        Non-participating groups are reported as ``''``.
        """
        out: list[str | tuple[str, ...]] = []
        for m in self._find_all_matches(text):
            if self.groups == 0:
                out.append(m._group(0) or "")
            elif self.groups == 1:
                out.append(m._group(1) or "")
            else:
                out.append(tuple(g or "" for g in m.groups()))
        return out


def compile(pattern: str) -> Pattern:
    """Compile ``pattern`` into a :class:`Pattern`. Raises ``RegexError`` if invalid."""
    return Pattern(pattern)
