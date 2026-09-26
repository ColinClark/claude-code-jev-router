"""miniregex: a small regular-expression engine in pure Python.

The results (matches, spans and capture groups) are identical to those of
Python's ``re`` module (without flags) for the supported syntax.
"""

from __future__ import annotations

from collections.abc import Iterator

from . import _engine
from ._parser import RegexError, parse

__all__ = ["compile", "Pattern", "Match", "RegexError"]


class Match:
    """Result of a successful match."""

    __slots__ = ("string", "re", "_spans")

    def __init__(self, pattern: Pattern, string: str, spans: tuple):
        self.re = pattern
        self.string = string
        self._spans = spans  # (start, end) per group, group 0 first

    def _index(self, group: int) -> int:
        if isinstance(group, bool) or not isinstance(group, int):
            raise IndexError("no such group")
        if group < 0 or group >= len(self._spans):
            raise IndexError("no such group")
        return group

    def group(self, *groups: int):
        if not groups:
            groups = (0,)
        values = []
        for g in groups:
            start, end = self._spans[self._index(g)]
            values.append(None if start < 0 else self.string[start:end])
        return values[0] if len(values) == 1 else tuple(values)

    def __getitem__(self, group: int):
        return self.group(group)

    def groups(self, default=None) -> tuple:
        return tuple(
            default if start < 0 else self.string[start:end]
            for start, end in self._spans[1:]
        )

    def span(self, group: int = 0) -> tuple[int, int]:
        return self._spans[self._index(group)]

    def start(self, group: int = 0) -> int:
        return self._spans[self._index(group)][0]

    def end(self, group: int = 0) -> int:
        return self._spans[self._index(group)][1]

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self.group()!r}>"


class Pattern:
    """A compiled regular expression."""

    __slots__ = ("pattern", "groups", "_code")

    def __init__(self, pattern: str):
        seq, ngroups = parse(pattern)
        self.pattern = pattern
        self.groups = ngroups
        self._code = _engine.compile_code(seq)

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"

    # -- helpers -----------------------------------------------------------

    def _state(self, text: str):
        if not isinstance(text, str):
            raise TypeError("expected a str")
        return _engine.new_state(text, self.groups)

    def _spans(self, st, start: int) -> tuple:
        spans = [(start, st.ptr)]
        marks = st.marks
        lastmark = st.lastmark
        for g in range(self.groups):
            j = 2 * g
            if j + 1 <= lastmark and marks[j] is not None and marks[j + 1] is not None:
                spans.append((marks[j], marks[j + 1]))
            else:
                spans.append((-1, -1))
        return tuple(spans)

    def _make_match(self, text: str, st, start: int) -> Match:
        return Match(self, text, self._spans(st, start))

    # -- public API ----------------------------------------------------------

    def match(self, text: str) -> Match | None:
        """Match at the start of ``text``."""
        st = self._state(text)
        if _engine.run(st, self._code, 0):
            return self._make_match(text, st, 0)
        return None

    def fullmatch(self, text: str) -> Match | None:
        """Match the whole of ``text``."""
        st = self._state(text)
        st.match_all = True
        if _engine.run(st, self._code, 0):
            return self._make_match(text, st, 0)
        return None

    def search(self, text: str) -> Match | None:
        """Find the leftmost match in ``text``."""
        st = self._state(text)
        start = _engine.search(st, self._code, 0)
        if start < 0:
            return None
        return self._make_match(text, st, start)

    def finditer(self, text: str) -> Iterator[Match]:
        """Iterate over all non-overlapping matches, like ``re.finditer``."""
        st = self._state(text)
        pos = 0
        while pos <= st.end:
            start = _engine.search(st, self._code, pos)
            if start < 0:
                return
            m = self._make_match(text, st, start)
            yield m
            st.must_advance = st.ptr == start
            pos = st.ptr

    def findall(self, text: str) -> list:
        """Return all non-overlapping matches, like ``re.findall``."""
        result = []
        for m in self.finditer(text):
            if self.groups == 0:
                result.append(m.group())
            elif self.groups == 1:
                result.append(m.groups(""))
                result[-1] = result[-1][0]
            else:
                result.append(m.groups(""))
        return result


def compile(pattern: str) -> Pattern:  # noqa: A001 - mirrors re.compile
    """Compile ``pattern``; raises :class:`RegexError` if it is invalid."""
    return Pattern(pattern)
