"""miniregex: a small regular-expression engine in pure Python.

Supports a subset of Python's ``re`` syntax with identical matching results::

    >>> from miniregex import compile
    >>> m = compile(r"(\\w+)@(\\w+)").search("mail bob@example now")
    >>> m.group(0), m.groups(), m.span(2)
    ('bob@example', ('bob', 'example'), (9, 16))
"""

from __future__ import annotations

from ._engine import Program, compile_ast, run
from ._parser import RegexError, parse

__all__ = ["compile", "RegexError", "Pattern", "Match"]


class Match:
    """The result of a successful match, mirroring ``re.Match``."""

    __slots__ = ("string", "re", "_regs")

    def __init__(self, pattern: Pattern, string: str, regs: list[int]):
        self.re = pattern
        self.string = string
        self._regs = regs

    def _index(self, n) -> int:
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= self.re.groups:
            raise IndexError("no such group")
        return n

    def span(self, n: int = 0) -> tuple[int, int]:
        n = self._index(n)
        start, end = self._regs[2 * n], self._regs[2 * n + 1]
        if start < 0 or end < 0:
            return (-1, -1)
        return (start, end)

    def start(self, n: int = 0) -> int:
        return self.span(n)[0]

    def end(self, n: int = 0) -> int:
        return self.span(n)[1]

    def _group(self, n) -> str | None:
        start, end = self.span(n)
        if start < 0:
            return None
        return self.string[start:end]

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
            default if value is None else value
            for value in (self._group(i) for i in range(1, self.re.groups + 1))
        )

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self.group()!r}>"


class Pattern:
    """A compiled pattern, mirroring the matching methods of ``re.Pattern``."""

    __slots__ = ("pattern", "groups", "_prog")

    def __init__(self, pattern: str, prog: Program):
        self.pattern = pattern
        self.groups = prog.ngroups
        self._prog = prog

    def _search(self, text: str, pos: int, must_advance: bool) -> Match | None:
        for start in range(pos, len(text) + 1):
            regs = run(self._prog, text, start, False, must_advance and start == pos)
            if regs is not None:
                return Match(self, text, regs)
        return None

    def match(self, text: str) -> Match | None:
        regs = run(self._prog, text, 0, False, False)
        return None if regs is None else Match(self, text, regs)

    def fullmatch(self, text: str) -> Match | None:
        regs = run(self._prog, text, 0, True, False)
        return None if regs is None else Match(self, text, regs)

    def search(self, text: str) -> Match | None:
        return self._search(text, 0, False)

    def finditer(self, text: str):
        pos = 0
        must_advance = False
        while pos <= len(text):
            m = self._search(text, pos, must_advance)
            if m is None:
                return
            yield m
            start, end = m.span()
            must_advance = start == end
            pos = end

    def findall(self, text: str) -> list:
        result = []
        for m in self.finditer(text):
            if self.groups == 0:
                result.append(m.group(0))
            elif self.groups == 1:
                result.append(m.groups("")[0])
            else:
                result.append(m.groups(""))
        return result

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"


def compile(pattern: str) -> Pattern:  # noqa: A001 - mirrors re.compile
    """Compile ``pattern``; raises RegexError if it is invalid or unsupported."""
    ast, ngroups = parse(pattern)
    return Pattern(pattern, compile_ast(ast, ngroups))
