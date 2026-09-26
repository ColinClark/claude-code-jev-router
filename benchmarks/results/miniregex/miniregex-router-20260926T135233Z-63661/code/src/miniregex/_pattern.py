"""Public ``Pattern`` and ``Match`` objects."""

import sys

from ._matcher import compile_node
from ._parser import parse

_BASE_RECURSION_LIMIT = 20000
_FRAMES_PER_CHAR = 12


class _RecursionHeadroom:
    """Temporarily raise the recursion limit.

    The continuation-passing matcher nests Python calls roughly in proportion
    to the number of characters consumed, so the limit scales with the input.
    """

    def __init__(self, string):
        self.needed = _BASE_RECURSION_LIMIT + _FRAMES_PER_CHAR * len(string)

    def __enter__(self):
        self.old = sys.getrecursionlimit()
        if self.old < self.needed:
            sys.setrecursionlimit(self.needed)
        return self

    def __exit__(self, *exc):
        if sys.getrecursionlimit() != self.old:
            sys.setrecursionlimit(self.old)
        return False


class Match:
    """Result of a successful match."""

    __slots__ = ("string", "re", "_spans")

    def __init__(self, pattern, string, spans):
        self.re = pattern
        self.string = string
        # spans[0] is the whole match; spans[g] is group g, (-1, -1) if unset.
        self._spans = spans

    def _index(self, group):
        if isinstance(group, bool) or not isinstance(group, int):
            try:
                group = group.__index__()
            except (AttributeError, TypeError):
                raise IndexError("no such group") from None
        if group < 0 or group >= len(self._spans):
            raise IndexError("no such group")
        return group

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

    def groups(self, default=None):
        return tuple(self._value(g, default) for g in range(1, len(self._spans)))

    def span(self, group=0):
        return self._spans[self._index(group)]

    def start(self, group=0):
        return self._spans[self._index(group)][0]

    def end(self, group=0):
        return self._spans[self._index(group)][1]

    def __repr__(self):
        return f"<miniregex.Match object; span={self._spans[0]!r}, match={self.group()!r}>"


class Pattern:
    """A compiled regular expression."""

    def __init__(self, pattern):
        ast, ngroups = parse(pattern)
        self.pattern = pattern
        self.groups = ngroups
        self._matcher = compile_node(ast)
        self._init_caps = (-1,) * (2 * ngroups)

    def __repr__(self):
        return f"miniregex.compile({self.pattern!r})"

    def _match_at(self, string, pos, full=False, must_advance=False):
        """Try to match starting exactly at ``pos``; return a Match or None."""
        n = len(string)

        def final(j, caps):
            if full and j != n:
                return None
            if must_advance and j == pos:
                return None
            return (j, caps)

        result = self._matcher(string, pos, self._init_caps, final)
        if result is None:
            return None
        end, caps = result
        spans = [(pos, end)]
        for g in range(self.groups):
            spans.append((caps[2 * g], caps[2 * g + 1]))
        return Match(self, string, tuple(spans))

    def _search(self, string, pos, must_advance=False):
        for start in range(pos, len(string) + 1):
            m = self._match_at(string, start, must_advance=must_advance and start == pos)
            if m is not None:
                return m
        return None

    @staticmethod
    def _check(string):
        if not isinstance(string, str):
            raise TypeError(f"expected string, got {type(string).__name__!r}")

    def match(self, string):
        self._check(string)
        with _RecursionHeadroom(string):
            return self._match_at(string, 0)

    def fullmatch(self, string):
        self._check(string)
        with _RecursionHeadroom(string):
            return self._match_at(string, 0, full=True)

    def search(self, string):
        self._check(string)
        with _RecursionHeadroom(string):
            return self._search(string, 0)

    def finditer(self, string):
        self._check(string)
        return iter(self._find_all_matches(string))

    def _find_all_matches(self, string):
        matches = []
        pos = 0
        must_advance = False
        n = len(string)
        with _RecursionHeadroom(string):
            while pos <= n:
                m = self._search(string, pos, must_advance)
                if m is None:
                    break
                matches.append(m)
                start, end = m.span()
                must_advance = start == end
                pos = end
        return matches

    def findall(self, string):
        self._check(string)
        result = []
        for m in self._find_all_matches(string):
            if self.groups == 0:
                result.append(m.group(0))
            elif self.groups == 1:
                result.append(m.group(1) or "")
            else:
                result.append(m.groups(""))
        return result
