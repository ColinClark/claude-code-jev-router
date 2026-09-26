from __future__ import annotations

from .errors import RegexError
from .parser import Parser


class Match:
    __slots__ = ("_text", "_start", "_end", "_groups", "_group_count")

    def __init__(self, text, start, end, groups, group_count):
        self._text = text
        self._start = start
        self._end = end
        self._groups = groups
        self._group_count = group_count

    def _check_index(self, n):
        if n < 0 or n > self._group_count:
            raise IndexError(f"no such group: {n}")

    def span(self, n=0):
        self._check_index(n)
        if n == 0:
            return (self._start, self._end)
        span = self._groups[n - 1]
        return span if span is not None else (-1, -1)

    def start(self, n=0):
        return self.span(n)[0]

    def end(self, n=0):
        return self.span(n)[1]

    def group(self, n=0):
        self._check_index(n)
        if n == 0:
            return self._text[self._start:self._end]
        span = self._groups[n - 1]
        if span is None:
            return None
        return self._text[span[0]:span[1]]

    def groups(self):
        return tuple(self.group(i) for i in range(1, self._group_count + 1))

    def __repr__(self):
        return f"<Match span={self.span()} match={self.group()!r}>"


class Pattern:
    def __init__(self, pattern, root, group_count):
        self.pattern = pattern
        self._root = root
        self._group_count = group_count

    def _run(self, text, start):
        """Attempts a match anchored at ``start``. Returns a Match or None."""
        groups = [None] * self._group_count
        result = {}

        def cont(end):
            result["end"] = end
            return True

        if self._root.match(text, start, groups, cont):
            return Match(text, start, result["end"], tuple(groups), self._group_count)
        return None

    def _run_require_progress(self, text, start):
        """Like ``_run`` but rejects a zero-width result at ``start``.

        Mirrors CPython's ``must_advance`` behaviour used by finditer/sub
        when retrying at the position of a just-emitted empty match.
        """
        groups = [None] * self._group_count
        result = {}

        def cont(end):
            if end == start:
                return False
            result["end"] = end
            return True

        if self._root.match(text, start, groups, cont):
            return Match(text, start, result["end"], tuple(groups), self._group_count)
        return None

    def _run_full(self, text, start):
        groups = [None] * self._group_count
        n = len(text)

        def cont(end):
            return end == n

        if self._root.match(text, start, groups, cont):
            return Match(text, start, n, tuple(groups), self._group_count)
        return None

    def match(self, text):
        return self._run(text, 0)

    def fullmatch(self, text):
        return self._run_full(text, 0)

    def search(self, text):
        for start in range(len(text) + 1):
            m = self._run(text, start)
            if m is not None:
                return m
        return None

    def _finditer(self, text):
        pos = 0
        n = len(text)
        must_advance = False
        while pos <= n:
            m = self._run_require_progress(text, pos) if must_advance else self._run(text, pos)
            if m is None:
                pos += 1
                must_advance = False
                continue
            yield m
            if m.end() == m.start():
                must_advance = True
                pos = m.end()
            else:
                must_advance = False
                pos = m.end()

    def findall(self, text):
        results = []
        for m in self._finditer(text):
            if self._group_count == 0:
                results.append(m.group(0))
            elif self._group_count == 1:
                results.append(m.group(1) if m.group(1) is not None else "")
            else:
                results.append(tuple(g if g is not None else "" for g in m.groups()))
        return results


def compile(pattern):
    try:
        root, group_count = Parser(pattern).parse()
    except RegexError:
        raise
    except Exception as exc:  # defensive: surface parser bugs as RegexError
        raise RegexError(str(exc)) from exc
    return Pattern(pattern, root, group_count)
