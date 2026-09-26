"""miniregex: a backtracking regular-expression engine in pure Python.

Results are intended to be identical to Python's ``re`` module (no flags) for
the supported syntax.  The ``re`` module is not used anywhere in this package.
"""

from __future__ import annotations

from ._compiler import compile_ast
from ._parser import RegexError, parse
from ._vm import run

__all__ = ["compile", "RegexError", "Pattern", "Match"]


class Match:
    """The result of a successful match (mirrors ``re.Match``)."""

    __slots__ = ("_regs", "string", "re")

    def __init__(self, pattern: Pattern, string: str, regs: list[int]):
        self.re = pattern
        self.string = string
        ngroups = pattern.groups
        spans = []
        for g in range(ngroups + 1):
            s, e = regs[2 * g], regs[2 * g + 1]
            if s < 0 or e < 0:
                spans.append((-1, -1))
            else:
                spans.append((s, e))
        self._regs = tuple(spans)

    def _index(self, group) -> int:
        if isinstance(group, bool) or not isinstance(group, int):
            try:
                group = group.__index__()
            except (AttributeError, TypeError):
                raise IndexError("no such group") from None
        if not 0 <= group < len(self._regs):
            raise IndexError("no such group")
        return group

    def _value(self, index: int, default=None):
        s, e = self._regs[index]
        if s < 0:
            return default
        return self.string[s:e]

    def group(self, *groups):
        if not groups:
            return self._value(0)
        if len(groups) == 1:
            return self._value(self._index(groups[0]))
        return tuple(self._value(self._index(g)) for g in groups)

    def __getitem__(self, group):
        return self._value(self._index(group))

    def groups(self, default=None):
        return tuple(self._value(i, default) for i in range(1, len(self._regs)))

    def span(self, group=0) -> tuple[int, int]:
        return self._regs[self._index(group)]

    def start(self, group=0) -> int:
        return self._regs[self._index(group)][0]

    def end(self, group=0) -> int:
        return self._regs[self._index(group)][1]

    @property
    def regs(self):
        return self._regs

    @property
    def pos(self) -> int:
        return 0

    @property
    def endpos(self) -> int:
        return len(self.string)

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self._regs[0]!r}, match={self.group()!r}>"


class Pattern:
    """A compiled regular expression (mirrors ``re.Pattern``)."""

    __slots__ = ("pattern", "groups", "_prog")

    def __init__(self, pattern: str):
        ast, groups = parse(pattern)
        self.pattern = pattern
        self.groups = groups
        self._prog = compile_ast(ast, groups)

    def _search(self, text: str, start: int, must_advance: bool) -> Match | None:
        prog = self._prog
        n = len(text)
        pos = start
        while pos <= n:
            regs = run(prog, text, pos, False, must_advance)
            if regs is not None:
                return Match(self, text, regs)
            must_advance = False
            pos += 1
        return None

    def fullmatch(self, text: str) -> Match | None:
        _check_str(text)
        regs = run(self._prog, text, 0, True, False)
        return None if regs is None else Match(self, text, regs)

    def match(self, text: str) -> Match | None:
        _check_str(text)
        regs = run(self._prog, text, 0, False, False)
        return None if regs is None else Match(self, text, regs)

    def search(self, text: str) -> Match | None:
        _check_str(text)
        return self._search(text, 0, False)

    def finditer(self, text: str):
        _check_str(text)
        pos = 0
        must_advance = False
        n = len(text)
        while pos <= n:
            m = self._search(text, pos, must_advance)
            if m is None:
                return
            yield m
            s, e = m.span()
            must_advance = s == e
            pos = e

    def findall(self, text: str) -> list:
        out = []
        for m in self.finditer(text):
            if self.groups == 0:
                out.append(m.group())
            elif self.groups == 1:
                out.append(m._value(1, ""))
            else:
                out.append(m.groups(""))
        return out

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"


def _check_str(text) -> None:
    if not isinstance(text, str):
        raise TypeError("expected string")


def compile(pattern: str) -> Pattern:  # noqa: A001 - mirrors re.compile
    """Compile ``pattern`` into a :class:`Pattern`; raises :class:`RegexError`."""
    if isinstance(pattern, Pattern):
        return pattern
    return Pattern(pattern)
