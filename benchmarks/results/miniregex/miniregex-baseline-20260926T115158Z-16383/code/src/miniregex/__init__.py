"""miniregex: a regular-expression engine in pure Python.

Supports a subset of Python's ``re`` syntax with identical matching semantics::

    >>> from miniregex import compile
    >>> m = compile(r"(\\w+)@(\\w+)\\.com").search("mail bob@example.com now")
    >>> m.group(1), m.span(2)
    ('bob', (9, 16))
"""

from __future__ import annotations

from ._engine import State, compile_tree
from ._parser import RegexError, parse

__all__ = ["compile", "Pattern", "Match", "RegexError"]


class Pattern:
    """A compiled regular expression."""

    def __init__(self, pattern: str) -> None:
        tree, groups = parse(pattern)
        self.pattern = pattern
        self.groups = groups
        self._code = compile_tree(tree)

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"

    def _state(self, text: str) -> State:
        if not isinstance(text, str):
            raise TypeError(f"expected string, got {type(text).__name__}")
        return State(self._code, self.groups, text)

    def fullmatch(self, text: str) -> Match | None:
        """Match the whole of ``text``."""
        state = self._state(text)
        state.match_all = True
        return Match(self, state) if state.match(0) else None

    def match(self, text: str) -> Match | None:
        """Match at the start of ``text``."""
        state = self._state(text)
        return Match(self, state) if state.match(0) else None

    def search(self, text: str) -> Match | None:
        """Return the leftmost match anywhere in ``text``."""
        state = self._state(text)
        return Match(self, state) if state.search(0) else None

    def findall(self, text: str) -> list:
        """Return all non-overlapping matches, like ``re.findall``."""
        state = self._state(text)
        results: list = []
        pos = 0
        must_advance = False
        while pos <= len(text) and state.search(pos, must_advance):
            if self.groups == 0:
                start, end = state.start, state.ptr
                results.append(text[start:end])
            else:
                values = []
                for g in range(1, self.groups + 1):
                    start, end = state.span(g)
                    values.append(text[start:end] if start >= 0 else "")
                results.append(values[0] if self.groups == 1 else tuple(values))
            must_advance = state.ptr == state.start
            pos = state.ptr
        return results


class Match:
    """The result of a successful match."""

    def __init__(self, pattern: Pattern, state: State) -> None:
        self.re = pattern
        self.string = state.text
        self._spans = tuple(state.span(g) for g in range(pattern.groups + 1))

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self.group()!r}>"

    def _span(self, group: int) -> tuple[int, int]:
        if isinstance(group, bool) or not isinstance(group, int):
            raise IndexError("no such group")
        if not 0 <= group < len(self._spans):
            raise IndexError("no such group")
        return self._spans[group]

    def group(self, *groups: int) -> str | None | tuple[str | None, ...]:
        """``group()`` / ``group(n)`` return one group; several arguments return a tuple."""
        if not groups:
            groups = (0,)
        values = []
        for g in groups:
            start, end = self._span(g)
            values.append(self.string[start:end] if start >= 0 else None)
        return values[0] if len(values) == 1 else tuple(values)

    def __getitem__(self, group: int) -> str | None:
        return self.group(group)

    def groups(self, default: object = None) -> tuple:
        """All capturing groups; ``default`` for groups that did not participate."""
        return tuple(
            self.string[start:end] if start >= 0 else default for start, end in self._spans[1:]
        )

    def span(self, group: int = 0) -> tuple[int, int]:
        return self._span(group)

    def start(self, group: int = 0) -> int:
        return self._span(group)[0]

    def end(self, group: int = 0) -> int:
        return self._span(group)[1]


def compile(pattern: str) -> Pattern:
    """Compile ``pattern``; raise ``RegexError`` if it is invalid or unsupported."""
    return Pattern(pattern)
