"""miniregex: a small regular-expression engine in pure Python.

Results match Python's ``re`` module (no flags) for the supported syntax.
"""

from __future__ import annotations

from ._engine import Program, compile_tree, run
from ._parser import RegexError, parse

__all__ = ["compile", "Pattern", "Match", "RegexError"]

_cache: dict[str, Pattern] = {}
_MAXCACHE = 256


def compile(pattern: str) -> Pattern:  # noqa: A001 - mirrors re.compile
    """Compile ``pattern`` into a :class:`Pattern`; raise :class:`RegexError` if invalid."""
    cached = _cache.get(pattern) if isinstance(pattern, str) else None
    if cached is not None:
        return cached
    tree, ngroups = parse(pattern)
    compiled = Pattern(pattern, compile_tree(tree, ngroups))
    if len(_cache) >= _MAXCACHE:
        _cache.clear()
    _cache[pattern] = compiled
    return compiled


class Pattern:
    """A compiled regular expression."""

    __slots__ = ("pattern", "groups", "_prog")

    def __init__(self, pattern: str, prog: Program):
        self.pattern = pattern
        self.groups = prog.ngroups
        self._prog = prog

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"

    def _make(self, text: str, start: int, result) -> Match | None:
        if result is None:
            return None
        end, marks = result
        return Match(self, text, start, end, marks)

    def fullmatch(self, text: str) -> Match | None:
        return self._make(text, 0, run(self._prog, text, 0, True, False))

    def match(self, text: str) -> Match | None:
        return self._make(text, 0, run(self._prog, text, 0, False, False))

    def _search(self, text: str, start: int, must_advance: bool) -> Match | None:
        prog = self._prog
        for pos in range(start, len(text) + 1):
            result = run(prog, text, pos, False, must_advance and pos == start)
            if result is not None:
                return self._make(text, pos, result)
        return None

    def search(self, text: str) -> Match | None:
        return self._search(text, 0, False)

    def finditer(self, text: str):
        """Yield successive non-overlapping matches, like ``re.finditer``."""
        pos = 0
        must_advance = False
        while pos <= len(text):
            m = self._search(text, pos, must_advance)
            if m is None:
                return
            yield m
            must_advance = m.end() == m.start()
            pos = m.end()

    def findall(self, text: str) -> list:
        """Return all non-overlapping matches, shaped like ``re.findall``."""
        out = []
        for m in self.finditer(text):
            if self.groups == 0:
                out.append(m.group(0))
            elif self.groups == 1:
                out.append(m.group(1) or "")
            else:
                out.append(m.groups(""))
        return out


class Match:
    """The result of a successful match."""

    __slots__ = ("re", "string", "_spans")

    def __init__(self, pattern: Pattern, text: str, start: int, end: int, marks: list[int]):
        self.re = pattern
        self.string = text
        spans = [(start, end)]
        for g in range(pattern.groups):
            a, b = marks[2 * g], marks[2 * g + 1]
            spans.append((a, b) if a >= 0 and b >= 0 else (-1, -1))
        self._spans = spans

    def _index(self, n) -> int:
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n < len(self._spans):
            raise IndexError("no such group")
        return n

    def _value(self, n, default=None):
        a, b = self._spans[self._index(n)]
        if a < 0:
            return default
        return self.string[a:b]

    def group(self, *groups):
        if not groups:
            return self._value(0)
        if len(groups) == 1:
            return self._value(groups[0])
        return tuple(self._value(g) for g in groups)

    def __getitem__(self, n):
        return self._value(n)

    def groups(self, default=None) -> tuple:
        return tuple(self._value(g, default) for g in range(1, len(self._spans)))

    def span(self, n: int = 0) -> tuple[int, int]:
        return self._spans[self._index(n)]

    def start(self, n: int = 0) -> int:
        return self.span(n)[0]

    def end(self, n: int = 0) -> int:
        return self.span(n)[1]

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()}, match={self.group()!r}>"
