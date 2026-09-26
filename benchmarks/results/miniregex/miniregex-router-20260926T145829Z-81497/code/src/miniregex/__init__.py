"""miniregex: a small regular-expression engine in pure Python.

Supports a subset of Python's ``re`` syntax with identical matching semantics.
"""

from __future__ import annotations

from ._engine import OP_AT_BEGINNING, Matcher, compile_program
from ._parser import RegexError, parse

__all__ = ["compile", "Pattern", "Match", "RegexError"]


class Match:
    """The result of a successful match."""

    def __init__(self, pattern: Pattern, string: str, spans: list[tuple[int, int]]):
        self.re = pattern
        self.string = string
        self._spans = spans

    def _index(self, n: int) -> int:
        if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n < len(self._spans):
            raise IndexError("no such group")
        return n

    def _value(self, n: int) -> str | None:
        start, end = self._spans[self._index(n)]
        if start < 0:
            return None
        return self.string[start:end]

    def group(self, *groups: int) -> str | None | tuple[str | None, ...]:
        if not groups:
            return self._value(0)
        if len(groups) == 1:
            return self._value(groups[0])
        return tuple(self._value(n) for n in groups)

    def __getitem__(self, n: int) -> str | None:
        return self._value(n)

    def groups(self, default: str | None = None) -> tuple[str | None, ...]:
        values = (self._value(n) for n in range(1, len(self._spans)))
        return tuple(default if v is None else v for v in values)

    def span(self, n: int = 0) -> tuple[int, int]:
        return self._spans[self._index(n)]

    def start(self, n: int = 0) -> int:
        return self.span(n)[0]

    def end(self, n: int = 0) -> int:
        return self.span(n)[1]

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self.group()!r}>"


class Pattern:
    """A compiled regular expression."""

    def __init__(self, pattern: str):
        items, ngroups = parse(pattern)
        self.pattern = pattern
        self.groups = ngroups
        self._code = compile_program(items)
        self._anchored = self._code[0][0] == OP_AT_BEGINNING

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"

    def _check(self, text: str) -> None:
        if not isinstance(text, str):
            raise TypeError("expected string")

    def _at(self, text: str, pos: int, match_all: bool) -> Match | None:
        matcher = Matcher(self._code, self.groups, text, match_all, False)
        matcher.reset(pos)
        if matcher.run(0, pos):
            return Match(self, text, matcher.spans())
        return None

    def _search(self, text: str, pos: int, must_advance: bool) -> Match | None:
        matcher = Matcher(self._code, self.groups, text, False, must_advance)
        end = len(text)
        while pos <= end:
            matcher.reset(pos)
            if matcher.run(0, pos):
                return Match(self, text, matcher.spans())
            matcher.must_advance = False
            if self._anchored:
                break
            pos += 1
        return None

    def match(self, text: str) -> Match | None:
        self._check(text)
        return self._at(text, 0, False)

    def fullmatch(self, text: str) -> Match | None:
        self._check(text)
        return self._at(text, 0, True)

    def search(self, text: str) -> Match | None:
        self._check(text)
        return self._search(text, 0, False)

    def findall(self, text: str) -> list:
        self._check(text)
        result: list = []
        pos = 0
        must_advance = False
        while pos <= len(text):
            m = self._search(text, pos, must_advance)
            if m is None:
                break
            if self.groups == 0:
                result.append(m.group())
            elif self.groups == 1:
                result.append(m.group(1) or "")
            else:
                result.append(m.groups(""))
            start, pos = m.span()
            must_advance = start == pos
        return result


def compile(pattern: str) -> Pattern:  # noqa: A001 - mirrors re.compile
    """Compile ``pattern``; raise :class:`RegexError` if it is invalid."""
    return Pattern(pattern)
