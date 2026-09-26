"""miniregex: a regular-expression engine in pure Python.

Supports a subset of Python's ``re`` syntax with identical matching semantics::

    >>> from miniregex import compile
    >>> m = compile(r"(\\w+)@(\\w+)").search("mail bob@example now")
    >>> m.groups()
    ('bob', 'example')
"""

from __future__ import annotations

from ._engine import State, compile_tree, match_at, search
from ._parser import RegexError, parse

__all__ = ["Match", "Pattern", "RegexError", "compile"]


class Match:
    """The result of a successful match."""

    __slots__ = ("re", "string", "_spans")

    def __init__(self, pattern: Pattern, string: str, spans: list[tuple[int, int]]):
        self.re = pattern
        self.string = string
        self._spans = spans

    def _index(self, group: int) -> int:
        if not isinstance(group, int) or isinstance(group, bool):
            raise IndexError("no such group")
        if not 0 <= group < len(self._spans):
            raise IndexError("no such group")
        return group

    def _value(self, group: int, default: str | None = None) -> str | None:
        start, end = self._spans[self._index(group)]
        if start < 0:
            return default
        return self.string[start:end]

    def group(self, *groups: int) -> str | None | tuple[str | None, ...]:
        if not groups:
            return self._value(0)
        if len(groups) == 1:
            return self._value(groups[0])
        return tuple(self._value(g) for g in groups)

    def __getitem__(self, group: int) -> str | None:
        return self._value(group)

    def groups(self, default: str | None = None) -> tuple[str | None, ...]:
        return tuple(self._value(g, default) for g in range(1, len(self._spans)))

    def span(self, group: int = 0) -> tuple[int, int]:
        return self._spans[self._index(group)]

    def start(self, group: int = 0) -> int:
        return self.span(group)[0]

    def end(self, group: int = 0) -> int:
        return self.span(group)[1]

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self.group()!r}>"


class Pattern:
    """A compiled regular expression."""

    __slots__ = ("pattern", "groups", "_code")

    def __init__(self, pattern: str):
        if not isinstance(pattern, str):
            raise TypeError("pattern must be a str")
        tree, ngroups = parse(pattern)
        self.pattern = pattern
        self.groups = ngroups
        self._code = compile_tree(tree)

    def _state(self, text: str) -> State:
        if not isinstance(text, str):
            raise TypeError("expected a str")
        return State(self._code, text, self.groups)

    def _result(self, state: State, ok: bool) -> Match | None:
        return Match(self, state.text, state.spans()) if ok else None

    def fullmatch(self, text: str) -> Match | None:
        state = self._state(text)
        return self._result(state, match_at(state, 0, match_all=True))

    def match(self, text: str) -> Match | None:
        state = self._state(text)
        return self._result(state, match_at(state, 0, match_all=False))

    def search(self, text: str) -> Match | None:
        state = self._state(text)
        return self._result(state, search(state, 0))

    def findall(self, text: str) -> list:
        state = self._state(text)
        results: list = []
        pos = 0
        must_advance = False
        while pos <= len(text) and search(state, pos, must_advance):
            spans = state.spans()
            values = [text[s:e] if s >= 0 else "" for s, e in spans]
            if self.groups == 0:
                results.append(values[0])
            elif self.groups == 1:
                results.append(values[1])
            else:
                results.append(tuple(values[1:]))
            must_advance = state.ptr == state.start
            pos = state.ptr
        return results

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"


def compile(pattern: str) -> Pattern:  # noqa: A001 - mirrors re.compile
    """Compile ``pattern``; raise :class:`RegexError` if it is invalid or unsupported."""
    return Pattern(pattern)
