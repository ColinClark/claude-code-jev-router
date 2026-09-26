"""Public ``Pattern`` and ``Match`` objects."""

from __future__ import annotations

import operator
import sys
from collections.abc import Iterator
from typing import Any

from ._compiler import Compiler, State
from ._parser import parse

# Deep patterns/texts recurse once per matched element; allow for that.
_MAX_RECURSION = 5_000_000


class Match:
    """Result of a successful match, modelled on ``re.Match``."""

    __slots__ = ("_regs", "string", "re", "pos", "endpos")

    def __init__(self, pattern: Pattern, string: str, regs: tuple[tuple[int, int], ...]) -> None:
        self.re = pattern
        self.string = string
        self._regs = regs
        self.pos = 0
        self.endpos = len(string)

    def _index(self, group: Any) -> int:
        try:
            index = operator.index(group)
        except TypeError:
            raise IndexError("no such group") from None
        if index < 0 or index >= len(self._regs):
            raise IndexError("no such group")
        return index

    def _get(self, group: Any, default: Any = None) -> Any:
        start, end = self._regs[self._index(group)]
        if start < 0:
            return default
        return self.string[start:end]

    def group(self, *groups: Any) -> Any:
        if not groups:
            return self._get(0)
        if len(groups) == 1:
            return self._get(groups[0])
        return tuple(self._get(g) for g in groups)

    def __getitem__(self, group: Any) -> Any:
        return self._get(group)

    def groups(self, default: Any = None) -> tuple[Any, ...]:
        return tuple(self._get(i, default) for i in range(1, len(self._regs)))

    def groupdict(self, default: Any = None) -> dict[str, Any]:
        return {}

    def span(self, group: Any = 0) -> tuple[int, int]:
        return self._regs[self._index(group)]

    def start(self, group: Any = 0) -> int:
        return self._regs[self._index(group)][0]

    def end(self, group: Any = 0) -> int:
        return self._regs[self._index(group)][1]

    @property
    def regs(self) -> tuple[tuple[int, int], ...]:
        return self._regs

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self.group()!r}>"


class Pattern:
    """A compiled regular expression, modelled on ``re.Pattern``."""

    def __init__(self, pattern: str) -> None:
        if not isinstance(pattern, str):
            raise TypeError(f"pattern must be a str, not {type(pattern).__name__}")
        seq, ngroups = parse(pattern)
        compiler = Compiler(ngroups)
        self._code = compiler.compile(seq)
        self._size = compiler.size
        self.pattern = pattern
        self.groups = ngroups
        self.flags = 0
        self.groupindex: dict[str, int] = {}

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"

    # -- engine driver -------------------------------------------------------

    def _run(self, fn: Any, text: str) -> Any:
        if not isinstance(text, str):
            raise TypeError(f"expected string, got {type(text).__name__}")
        need = min(_MAX_RECURSION, (len(text) + 2) * (self._size + 4) * 2 + 1000)
        old = sys.getrecursionlimit()
        if need <= old:
            return fn(text)
        sys.setrecursionlimit(need)
        try:
            return fn(text)
        finally:
            sys.setrecursionlimit(old)

    def _regs(self, s: State, start: int) -> tuple[tuple[int, int], ...]:
        regs = [(start, s.endpos)]
        marks = s.marks
        lastmark = s.lastmark
        for i in range(self.groups):
            j = 2 * i
            if j + 1 <= lastmark and marks[j] >= 0 and marks[j + 1] >= 0:
                regs.append((marks[j], marks[j + 1]))
            else:
                regs.append((-1, -1))
        return tuple(regs)

    def _match_at(self, s: State, pos: int) -> bool:
        s.reset(pos)
        return self._code(s, pos)

    def _search_from(self, s: State, start: int) -> int:
        """Search starting at ``start``; return the match start or -1."""
        code = self._code
        end = s.end
        pos = start
        while pos <= end:
            s.reset(pos)
            if code(s, pos):
                return pos
            s.must_advance = False
            pos += 1
        return -1

    # -- public API ----------------------------------------------------------

    def match(self, string: str) -> Match | None:
        def run(text: str) -> Match | None:
            s = State(text, 2 * self.groups)
            if self._match_at(s, 0):
                return Match(self, text, self._regs(s, 0))
            return None

        return self._run(run, string)

    def fullmatch(self, string: str) -> Match | None:
        def run(text: str) -> Match | None:
            s = State(text, 2 * self.groups)
            s.match_all = True
            if self._match_at(s, 0):
                return Match(self, text, self._regs(s, 0))
            return None

        return self._run(run, string)

    def search(self, string: str) -> Match | None:
        def run(text: str) -> Match | None:
            s = State(text, 2 * self.groups)
            start = self._search_from(s, 0)
            if start < 0:
                return None
            return Match(self, text, self._regs(s, start))

        return self._run(run, string)

    def _iter_regs(self, text: str) -> Iterator[tuple[tuple[int, int], ...]]:
        s = State(text, 2 * self.groups)
        pos = 0
        must_advance = False
        while pos <= s.end:
            s.must_advance = must_advance
            start = self._search_from(s, pos)
            if start < 0:
                return
            regs = self._regs(s, start)
            yield regs
            must_advance = s.endpos == start
            pos = s.endpos

    def findall(self, string: str) -> list[Any]:
        def run(text: str) -> list[Any]:
            out: list[Any] = []
            ngroups = self.groups
            for regs in self._iter_regs(text):
                if ngroups == 0:
                    a, b = regs[0]
                    out.append(text[a:b])
                else:
                    values = tuple(text[a:b] if a >= 0 else "" for a, b in regs[1:])
                    out.append(values[0] if ngroups == 1 else values)
            return out

        return self._run(run, string)

    def finditer(self, string: str) -> Iterator[Match]:
        def run(text: str) -> list[Match]:
            return [Match(self, text, regs) for regs in self._iter_regs(text)]

        return iter(self._run(run, string))


def compile(pattern: str) -> Pattern:  # noqa: A001 - mirrors re.compile
    """Compile ``pattern`` into a :class:`Pattern`; raise ``RegexError`` if invalid."""
    return Pattern(pattern)
