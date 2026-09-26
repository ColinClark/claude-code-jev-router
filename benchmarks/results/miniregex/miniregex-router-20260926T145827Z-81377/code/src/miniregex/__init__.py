"""miniregex: a regular-expression engine in pure Python.

Usage mirrors the ``re`` module::

    >>> from miniregex import compile
    >>> compile(r"(\\w+)@(\\w+)").search("mail bob@example now").groups()
    ('bob', 'example')
"""

from __future__ import annotations

import sys

from ._engine import compile_node
from ._parser import RegexError, parse

__all__ = ["compile", "Pattern", "Match", "RegexError"]


class Match:
    """The result of a successful match, with the same accessors as ``re.Match``."""

    __slots__ = ("string", "re", "_spans")

    def __init__(self, pattern: Pattern, string: str, start: int, end: int, caps: tuple):
        self.re = pattern
        self.string = string
        spans = [(start, end)]
        for g in range(0, len(caps), 2):
            spans.append((caps[g], caps[g + 1]))
        self._spans = tuple(spans)

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

    def _group(self, n, default=None):
        start, end = self.span(n)
        if start < 0:
            return default
        return self.string[start:end]

    def group(self, *ns):
        if not ns:
            return self._group(0)
        if len(ns) == 1:
            return self._group(ns[0])
        return tuple(self._group(n) for n in ns)

    def __getitem__(self, n):
        return self._group(n)

    def groups(self, default=None) -> tuple:
        return tuple(self._group(n, default) for n in range(1, len(self._spans)))

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self.group()!r}>"


class Pattern:
    """A compiled regular expression."""

    def __init__(self, pattern: str):
        ast, ngroups = parse(pattern)
        self.pattern = pattern
        self.groups = ngroups
        self._matcher = compile_node(ast)
        self._empty_caps = (-1,) * (2 * ngroups)

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"

    def _run(self, s: str, start: int, accept):
        """Match at ``start``; ``accept(end)`` filters candidate end positions."""

        def done(end, caps):
            if accept(end):
                return end, caps
            return None

        return self._matcher(s, start, self._empty_caps, done)

    def _search(self, s: str, pos: int, must_advance: bool):
        _check_str(s)
        with _deep_recursion(len(s)):
            for start in range(pos, len(s) + 1):
                if must_advance and start == pos:
                    r = self._run(s, start, lambda end, p=pos: end != p)
                else:
                    r = self._run(s, start, _always)
                if r is not None:
                    return Match(self, s, start, r[0], r[1])
        return None

    def match(self, string: str) -> Match | None:
        """Match at the start of ``string``."""
        _check_str(string)
        with _deep_recursion(len(string)):
            r = self._run(string, 0, _always)
        return None if r is None else Match(self, string, 0, r[0], r[1])

    def fullmatch(self, string: str) -> Match | None:
        """Match the whole of ``string``."""
        _check_str(string)
        n = len(string)
        with _deep_recursion(n):
            r = self._run(string, 0, lambda end: end == n)
        return None if r is None else Match(self, string, 0, r[0], r[1])

    def search(self, string: str) -> Match | None:
        """Return the first match found anywhere in ``string``."""
        return self._search(string, 0, False)

    def finditer(self, string: str):
        """Yield successive non-overlapping matches, like ``re.finditer``."""
        pos = 0
        must_advance = False
        while pos <= len(string):
            m = self._search(string, pos, must_advance)
            if m is None:
                return
            yield m
            start, end = m.span()
            must_advance = start == end
            pos = end

    def findall(self, string: str) -> list:
        """Return all non-overlapping matches, shaped like ``re.findall``."""
        out = []
        for m in self.finditer(string):
            if self.groups == 0:
                out.append(m.group())
            elif self.groups == 1:
                out.append(m.group(1) or "")
            else:
                out.append(m.groups(""))
        return out


def compile(pattern: str) -> Pattern:  # noqa: A001 - mirrors re.compile
    """Compile ``pattern``; raise :class:`RegexError` if it is invalid."""
    return Pattern(pattern)


def _always(end: int) -> bool:
    return True


def _check_str(s) -> None:
    if not isinstance(s, str):
        raise TypeError(f"expected str, got {type(s).__name__}")


class _deep_recursion:
    """Temporarily raise the recursion limit: matching recurses per step."""

    def __init__(self, n: int):
        self.needed = 10_000 + 50 * n

    def __enter__(self):
        self.old = sys.getrecursionlimit()
        if self.needed > self.old:
            sys.setrecursionlimit(self.needed)

    def __exit__(self, *exc):
        sys.setrecursionlimit(self.old)
        return False
