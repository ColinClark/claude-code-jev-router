"""miniregex: a minimal regular expression engine in pure Python.

Supported syntax: literals, ``.``, ``^``, ``$``, character sets ``[...]``
(ranges, negation, class escapes), the class escapes ``\\d \\D \\w \\W \\s \\S``
(ASCII meaning), escaped metacharacters, capturing ``(...)`` and
non-capturing ``(?:...)`` groups, alternation (empty branches allowed) and
the quantifiers ``* + ? {n} {n,} {,m} {n,m}`` with an optional lazy ``?``.
For every supported pattern the results are identical to :mod:`re` without
flags: which strings match, spans, and the value and span of every group.

Deliberate divergences from :mod:`re`:

* possessive quantifiers (``*+``, ``++``, ``?+``, ``{n,m}+``) are rejected
  with :class:`RegexError` instead of being supported;
* escapes outside the supported list (``\\b`` outside a set, ``\\B``, ``\\A``,
  ``\\Z``, back-references, ``\\x..``, ``\\0``, ...) raise :class:`RegexError`;
* ``(?...)`` forms other than ``(?:...)`` raise :class:`RegexError`;
* repetition counts that :mod:`re` rejects with :class:`OverflowError` raise
  :class:`RegexError`.
"""

from __future__ import annotations

import operator
from collections.abc import Iterator

from ._errors import RegexError
from ._matcher import run as _run
from ._matcher import search as _search
from ._parser import compile_pattern as _compile_pattern

__all__ = ["Match", "Pattern", "RegexError", "compile"]

_NO_SUCH_GROUP = "no such group"


class Match:
    """The result of a successful match."""

    __slots__ = ("_regs", "_lastindex", "re", "string", "pos", "endpos")

    def __init__(self, pattern: Pattern, string: str, regs: tuple, lastindex: int) -> None:
        self.re = pattern
        self.string = string
        self.pos = 0
        self.endpos = len(string)
        self._regs = regs
        self._lastindex = lastindex

    def _index(self, group) -> int:
        try:
            index = operator.index(group)
        except TypeError:
            raise IndexError(_NO_SUCH_GROUP) from None
        if index < 0 or index >= len(self._regs):
            raise IndexError(_NO_SUCH_GROUP)
        return index

    def _value(self, index: int, default=None):
        start, end = self._regs[index]
        if start < 0:
            return default
        return self.string[start:end]

    def group(self, *groups):
        """Return one or more subgroups of the match (``None`` if unmatched)."""
        if not groups:
            return self._value(0)
        if len(groups) == 1:
            return self._value(self._index(groups[0]))
        return tuple(self._value(self._index(g)) for g in groups)

    def __getitem__(self, group):
        return self._value(self._index(group))

    def groups(self, default=None) -> tuple:
        """Return a tuple with all capturing groups (``default`` if unmatched)."""
        return tuple(self._value(i, default) for i in range(1, len(self._regs)))

    def span(self, group=0) -> tuple[int, int]:
        """Return ``(start, end)`` of a group; ``(-1, -1)`` if it did not participate."""
        return self._regs[self._index(group)]

    def start(self, group=0) -> int:
        return self._regs[self._index(group)][0]

    def end(self, group=0) -> int:
        return self._regs[self._index(group)][1]

    @property
    def regs(self) -> tuple:
        return self._regs

    @property
    def lastindex(self) -> int | None:
        """Index of the last matched capturing group, or ``None``."""
        return self._lastindex if self._lastindex >= 0 else None

    @property
    def lastgroup(self) -> None:
        return None  # named groups are not supported

    def __repr__(self) -> str:
        start, end = self._regs[0]
        return f"<miniregex.Match object; span={(start, end)!r}, match={self.string[start:end]!r}>"


class Pattern:
    """A compiled regular expression."""

    __slots__ = ("pattern", "groups", "_code", "_nmarks")

    def __init__(self, pattern: str) -> None:
        if not isinstance(pattern, str):
            raise TypeError("pattern must be a str")
        self.pattern = pattern
        self._code, self.groups = _compile_pattern(pattern)
        self._nmarks = 2 * self.groups

    @property
    def flags(self) -> int:
        return 0

    @property
    def groupindex(self) -> dict:
        return {}

    def _make_match(self, string: str, start: int, result) -> Match:
        _, end, marks, lastmark, lastindex = result
        regs = [(start, end)]
        for j in range(0, self._nmarks, 2):
            if j + 1 <= lastmark and marks[j] is not None and marks[j + 1] is not None:
                regs.append((marks[j], marks[j + 1]))
            else:
                regs.append((-1, -1))
        return Match(self, string, tuple(regs), lastindex)

    def _match_at(self, string: str, match_all: bool) -> Match | None:
        if not isinstance(string, str):
            raise TypeError("expected string")
        result = _run(self._code, string, 0, len(string), self._nmarks, match_all, False)
        if not result[0]:
            return None
        return self._make_match(string, 0, result)

    def match(self, string: str) -> Match | None:
        """Match the pattern at the start of ``string``."""
        return self._match_at(string, False)

    def fullmatch(self, string: str) -> Match | None:
        """Match the pattern against all of ``string``."""
        return self._match_at(string, True)

    def search(self, string: str) -> Match | None:
        """Find the leftmost match in ``string``."""
        if not isinstance(string, str):
            raise TypeError("expected string")
        found = _search(self._code, string, 0, len(string), self._nmarks, False)
        if found is None:
            return None
        start, result = found
        return self._make_match(string, start, result)

    def finditer(self, string: str) -> Iterator[Match]:
        """Iterate over all non-overlapping matches, like :meth:`re.Pattern.finditer`."""
        if not isinstance(string, str):
            raise TypeError("expected string")
        end = len(string)
        pos = 0
        must_advance = False
        while pos <= end:
            found = _search(self._code, string, pos, end, self._nmarks, must_advance)
            if found is None:
                break
            start, result = found
            match = self._make_match(string, start, result)
            yield match
            match_end = result[1]
            must_advance = match_end == start
            pos = match_end

    def findall(self, string: str) -> list:
        """Return all matches, shaped like :meth:`re.Pattern.findall`."""
        out = []
        ngroups = self.groups
        for match in self.finditer(string):
            if ngroups == 0:
                out.append(match.group(0))
            elif ngroups == 1:
                out.append(match._value(1, ""))
            else:
                out.append(tuple(match._value(i, "") for i in range(1, ngroups + 1)))
        return out

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"


def compile(pattern: str) -> Pattern:  # noqa: A001 - mirrors re.compile
    """Compile ``pattern`` into a :class:`Pattern`; raise :class:`RegexError` if invalid."""
    return Pattern(pattern)


def match(pattern: str, string: str) -> Match | None:
    return compile(pattern).match(string)


def fullmatch(pattern: str, string: str) -> Match | None:
    return compile(pattern).fullmatch(string)


def search(pattern: str, string: str) -> Match | None:
    return compile(pattern).search(string)


def findall(pattern: str, string: str) -> list:
    return compile(pattern).findall(string)
