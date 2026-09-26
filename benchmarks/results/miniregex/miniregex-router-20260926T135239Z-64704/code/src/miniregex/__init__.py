"""miniregex: a small regular-expression engine in pure Python.

Supports a subset of Python's ``re`` syntax with identical matching semantics::

    >>> from miniregex import compile
    >>> m = compile(r"(\\w+)@(\\w+)").search("mail bob@example now")
    >>> m.group(0), m.groups(), m.span(2)
    ('bob@example', ('bob', 'example'), (9, 16))
"""

from __future__ import annotations

from ._engine import compile_ast, execute
from ._parser import RegexError, parse

__all__ = ["Match", "Pattern", "RegexError", "compile"]


class Match:
    """The result of a successful match; API modelled on ``re.Match``."""

    __slots__ = ("re", "string", "_spans")

    def __init__(self, pattern: Pattern, string: str, spans: tuple[tuple[int, int], ...]):
        self.re = pattern
        self.string = string
        self._spans = spans

    def _index(self, group) -> int:
        if isinstance(group, int) and not isinstance(group, bool):
            if 0 <= group < len(self._spans):
                return group
        raise IndexError("no such group")

    def span(self, group: int = 0) -> tuple[int, int]:
        return self._spans[self._index(group)]

    def start(self, group: int = 0) -> int:
        return self.span(group)[0]

    def end(self, group: int = 0) -> int:
        return self.span(group)[1]

    def _value(self, group, default=None):
        start, end = self._spans[self._index(group)]
        if start < 0:
            return default
        return self.string[start:end]

    def group(self, *groups):
        if not groups:
            return self._value(0)
        if len(groups) == 1:
            return self._value(groups[0])
        return tuple(self._value(g) for g in groups)

    def __getitem__(self, group):
        return self._value(group)

    def groups(self, default=None) -> tuple:
        return tuple(self._value(i, default) for i in range(1, len(self._spans)))

    @property
    def pos(self) -> int:
        return 0

    @property
    def endpos(self) -> int:
        return len(self.string)

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self.group()!r}>"


class Pattern:
    """A compiled pattern; API modelled on ``re.Pattern``."""

    __slots__ = ("pattern", "groups", "_prog")

    def __init__(self, pattern: str):
        if not isinstance(pattern, str):
            raise TypeError("pattern must be a str")
        ast, ngroups = parse(pattern)
        self.pattern = pattern
        self.groups = ngroups
        self._prog = compile_ast(ast, ngroups)

    def _match_at(self, text: str, start: int, fullmatch=False, must_advance=False):
        result = execute(self._prog, text, start, fullmatch, must_advance)
        if result is None:
            return None
        regs, end = result
        spans = [(start, end)]
        for i in range(1, self.groups + 1):
            s, e = regs[2 * i], regs[2 * i + 1]
            spans.append((s, e) if s is not None and e is not None else (-1, -1))
        return Match(self, text, tuple(spans))

    def _search(self, text: str, start: int, must_advance: bool):
        for pos in range(start, len(text) + 1):
            m = self._match_at(text, pos, must_advance=must_advance and pos == start)
            if m is not None:
                return m
        return None

    def fullmatch(self, text: str) -> Match | None:
        return self._match_at(text, 0, fullmatch=True)

    def match(self, text: str) -> Match | None:
        return self._match_at(text, 0)

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
                result.append(m.group())
            elif self.groups == 1:
                result.append(m.group(1) or "")
            else:
                result.append(m.groups(""))
        return result

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"


def compile(pattern: str) -> Pattern:
    """Compile *pattern*; raises :class:`RegexError` if it is invalid."""
    return Pattern(pattern)
