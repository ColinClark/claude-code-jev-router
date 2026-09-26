"""miniregex: a small regular-expression engine in pure Python.

Matching results (spans and group values) are identical to Python's ``re``
module, without flags, for the supported syntax.
"""

from __future__ import annotations

from ._engine import State, compile_node, deep_recursion
from ._parser import RegexError, parse

__all__ = ["Match", "Pattern", "RegexError", "compile"]


class Match:
    """Result of a successful match, modelled on ``re.Match``."""

    __slots__ = ("_spans", "re", "string")

    def __init__(self, pattern: Pattern, string: str, spans: list[tuple[int, int]]):
        self.re = pattern
        self.string = string
        self._spans = spans

    def _index(self, n) -> int:
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n < len(self._spans):
            raise IndexError("no such group")
        return n

    def span(self, n: int = 0) -> tuple[int, int]:
        return self._spans[self._index(n)]

    def start(self, n: int = 0) -> int:
        return self.span(n)[0]

    def end(self, n: int = 0) -> int:
        return self.span(n)[1]

    def group(self, *ns: int):
        if not ns:
            ns = (0,)
        values = []
        for n in ns:
            start, end = self.span(n)
            values.append(None if start < 0 else self.string[start:end])
        return values[0] if len(values) == 1 else tuple(values)

    def groups(self, default=None) -> tuple:
        result = []
        for n in range(1, len(self._spans)):
            value = self.group(n)
            result.append(default if value is None else value)
        return tuple(result)

    def __getitem__(self, n: int):
        return self.group(n)

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self.group()!r}>"


class Pattern:
    """A compiled pattern, modelled on ``re.Pattern``."""

    def __init__(self, pattern: str):
        ast, ngroups = parse(pattern)
        self.pattern = pattern
        self.groups = ngroups
        self._matcher = compile_node(ast)

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"

    def _match_at(self, st: State, start: int, *, full: bool = False, must_advance: bool = False):
        """Try an anchored match at ``start``; return the end position or None."""
        end = st.end
        result = []

        def accept(j: int) -> bool:
            if full and j != end:
                return False
            if must_advance and j == start:
                return False
            result.append(j)
            return True

        st.marks = [None] * (2 * self.groups)
        if self._matcher(st, start, accept):
            return result[0]
        return None

    def _make_match(self, st: State, start: int, end: int) -> Match:
        spans = [(start, end)]
        marks = st.marks
        for g in range(self.groups):
            a, b = marks[2 * g], marks[2 * g + 1]
            spans.append((-1, -1) if a is None else (a, b))
        return Match(self, st.text, spans)

    def _search(self, st: State, pos: int, must_advance: bool = False):
        for start in range(pos, st.end + 1):
            end = self._match_at(st, start, must_advance=must_advance and start == pos)
            if end is not None:
                return self._make_match(st, start, end)
        return None

    def match(self, text: str) -> Match | None:
        st = State(text, self.groups)
        with deep_recursion(len(text)):
            end = self._match_at(st, 0)
        return None if end is None else self._make_match(st, 0, end)

    def fullmatch(self, text: str) -> Match | None:
        st = State(text, self.groups)
        with deep_recursion(len(text)):
            end = self._match_at(st, 0, full=True)
        return None if end is None else self._make_match(st, 0, end)

    def search(self, text: str) -> Match | None:
        st = State(text, self.groups)
        with deep_recursion(len(text)):
            return self._search(st, 0)

    def finditer(self, text: str):
        st = State(text, self.groups)
        pos = 0
        must_advance = False
        while pos <= st.end:
            with deep_recursion(len(text)):
                m = self._search(st, pos, must_advance)
            if m is None:
                return
            yield m
            start, pos = m.span()
            must_advance = start == pos

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


def compile(pattern: str) -> Pattern:
    """Compile ``pattern`` into a :class:`Pattern`; raises :class:`RegexError`."""
    return Pattern(pattern)
