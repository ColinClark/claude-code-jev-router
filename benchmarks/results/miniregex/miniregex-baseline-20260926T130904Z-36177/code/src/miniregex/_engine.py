"""Pattern/Match objects built on top of the backtracking node tree."""

from __future__ import annotations

import sys
import threading

from ._errors import RegexError
from ._nodes import Context
from ._parser import parse

# Backtracking recursion depth grows with the number of repetitions matched
# (e.g. matching "a"*5000 against "a*"), so raise the recursion limit and run
# matches on a worker thread with a bigger C stack to avoid a real stack
# overflow (which, unlike a RecursionError, would crash the interpreter).
_RECURSION_LIMIT = 100_000
_STACK_SIZE = 256 * 1024 * 1024


def _run_with_big_stack(fn):
    result = {}
    error = {}

    def target():
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, _RECURSION_LIMIT))
        try:
            result["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            error["exc"] = exc
        finally:
            sys.setrecursionlimit(old_limit)

    old_stack_size = threading.stack_size()
    try:
        threading.stack_size(_STACK_SIZE)
    except (ValueError, RuntimeError):
        pass
    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    try:
        threading.stack_size(old_stack_size)
    except (ValueError, RuntimeError):
        pass
    if "exc" in error:
        raise error["exc"]
    return result.get("value")


class Match:
    def __init__(self, text, groups, pattern):
        self._text = text
        self._groups = groups
        self.re = pattern

    def _span_for(self, n):
        if not isinstance(n, int):
            raise IndexError("group index must be an integer")
        if n < 0 or n >= len(self._groups):
            raise IndexError("no such group")
        return self._groups[n]

    def group(self, n=0):
        span = self._span_for(n)
        if span is None:
            return None
        start, end = span
        return self._text[start:end]

    def groups(self):
        return tuple(self.group(i) for i in range(1, len(self._groups)))

    def span(self, n=0):
        span = self._span_for(n)
        if span is None:
            return (-1, -1)
        return span

    def start(self, n=0):
        return self.span(n)[0]

    def end(self, n=0):
        return self.span(n)[1]

    def __repr__(self):
        return f"<miniregex.Match span={self.span()!r} match={self.group()!r}>"


class Pattern:
    def __init__(self, pattern_str, root, num_groups):
        self.pattern = pattern_str
        self._root = root
        self._num_groups = num_groups

    def _attempt(self, text, start, full, require_nonempty=False):
        groups = [None] * (self._num_groups + 1)
        ctx = Context(text, groups)
        end_holder = {}

        def k(p):
            if require_nonempty and p == start:
                return False
            if full and p != len(text):
                return False
            end_holder["end"] = p
            return True

        if not self._root.match(ctx, start, k):
            return None
        groups[0] = (start, end_holder["end"])
        return groups

    def _search_from(self, text, start):
        for i in range(start, len(text) + 1):
            groups = self._attempt(text, i, full=False)
            if groups is not None:
                return groups
        return None

    def fullmatch(self, text):
        groups = _run_with_big_stack(lambda: self._attempt(text, 0, True))
        return Match(text, groups, self) if groups is not None else None

    def match(self, text):
        groups = _run_with_big_stack(lambda: self._attempt(text, 0, False))
        return Match(text, groups, self) if groups is not None else None

    def search(self, text):
        groups = _run_with_big_stack(lambda: self._search_from(text, 0))
        return Match(text, groups, self) if groups is not None else None

    def findall(self, text):
        # Mirrors `re`'s scanning loop (finditer/findall since Python 3.7):
        # a zero-width match is allowed right after a non-empty match, but
        # two zero-width matches can't land at the very same spot in a row.
        # When the previous match at this position was empty, we retry here
        # requiring a non-empty result (letting the backtracker pick a
        # longer alternative) before finally advancing past this position.
        def run():
            results = []
            pos = 0
            n = len(text)
            require_nonempty = False
            while pos <= n:
                groups = self._attempt(text, pos, full=False, require_nonempty=require_nonempty)
                if groups is None:
                    pos += 1
                    require_nonempty = False
                    continue
                start, end = groups[0]
                if self._num_groups == 0:
                    results.append(text[start:end])
                elif self._num_groups == 1:
                    g = groups[1]
                    results.append(text[g[0] : g[1]] if g else "")
                else:
                    row = tuple(
                        text[groups[i][0] : groups[i][1]] if groups[i] else ""
                        for i in range(1, self._num_groups + 1)
                    )
                    results.append(row)
                if end == start:
                    require_nonempty = True
                else:
                    pos = end
                    require_nonempty = False
            return results

        return _run_with_big_stack(run)

    def __repr__(self):
        return f"miniregex.compile({self.pattern!r})"


def compile(pattern):  # noqa: A001 - mirrors `re.compile` naming
    if not isinstance(pattern, str):
        raise RegexError("pattern must be a string")
    root, num_groups = parse(pattern)
    return Pattern(pattern, root, num_groups)
