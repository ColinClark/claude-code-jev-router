"""Backtracking virtual machine plus the public ``Pattern`` and ``Match`` types.

The VM keeps an explicit backtrack stack of ``(pc, pos, captures, repeats)``
choice points, so memory grows with the number of pending alternatives but the
Python call depth stays constant regardless of text length.

``captures`` is an immutable tuple (two slots per group), ``repeats`` is an
immutable linked list ``(count, last_ptr, prev)`` of active repeat contexts;
restoring a choice point therefore restores captures and repeat counters
exactly, which is what gives "captures are restored on backtracking" and
"last iteration wins" semantics identical to sre.
"""

from __future__ import annotations

from collections.abc import Iterator

from ._compiler import (
    OP_ANY,
    OP_BOL,
    OP_CHAR,
    OP_EOL,
    OP_JMP,
    OP_REPEAT,
    OP_SAVE,
    OP_SET,
    OP_SPLIT,
    OP_UNTIL,
    compile_ast,
)
from ._parser import parse

_Result = tuple[int, tuple[int, ...]]


def _run(
    prog: list[tuple],
    ncaps: int,
    text: str,
    start: int,
    must_advance: bool,
    match_all: bool,
) -> _Result | None:
    """Run ``prog`` anchored at ``start``; return ``(end, captures)`` or ``None``.

    ``must_advance`` rejects an empty match at ``start`` (findall continuation
    after an empty match); ``match_all`` requires the match to end at the end
    of ``text`` (fullmatch). Both are checked at MATCH with full backtracking,
    exactly like sre's ``must_advance`` / ``match_all`` state flags.
    """
    n = len(text)
    pc = 0
    pos = start
    caps: tuple[int, ...] = (-1,) * ncaps
    reps: tuple | None = None
    stack: list[tuple] = []
    push = stack.append
    pop = stack.pop
    while True:
        ins = prog[pc]
        op = ins[0]
        if op == OP_CHAR:
            if pos < n and text[pos] == ins[1]:
                pos += 1
                pc += 1
                continue
        elif op == OP_SPLIT:
            push((ins[2], pos, caps, reps))
            pc = ins[1]
            continue
        elif op == OP_UNTIL:
            count, last, prev = reps  # type: ignore[misc]
            count += 1
            mn = ins[1]
            mx = ins[2]
            if count < mn:
                # Mandatory iteration: no zero-width protection, no fallback.
                reps = (count, last, prev)
                pc = ins[4]
                continue
            if (mx is None or count < mx) and pos != last:
                if ins[3]:
                    # Lazy: try the tail first, one more iteration as fallback.
                    push((ins[4], pos, caps, (count, pos, prev)))
                    reps = prev
                    pc += 1
                    continue
                # Greedy: one more iteration first, the tail as fallback.
                push((pc + 1, pos, caps, prev))
                reps = (count, pos, prev)
                pc = ins[4]
                continue
            # Cannot iterate again (max reached or last iteration was empty).
            reps = prev
            pc += 1
            continue
        elif op == OP_SET:
            if pos < n and ins[1](text[pos]):
                pos += 1
                pc += 1
                continue
        elif op == OP_ANY:
            if pos < n and text[pos] != "\n":
                pos += 1
                pc += 1
                continue
        elif op == OP_SAVE:
            slot = ins[1]
            caps = caps[:slot] + (pos,) + caps[slot + 1 :]
            pc += 1
            continue
        elif op == OP_JMP:
            pc = ins[1]
            continue
        elif op == OP_REPEAT:
            reps = (-1, -1, reps)
            pc = ins[1]
            continue
        elif op == OP_BOL:
            if pos == 0:
                pc += 1
                continue
        elif op == OP_EOL:
            if pos == n or (pos == n - 1 and text[pos] == "\n"):
                pc += 1
                continue
        else:  # OP_MATCH
            if not ((match_all and pos != n) or (must_advance and pos == start)):
                return pos, caps
        # Failure: backtrack to the most recent choice point.
        if not stack:
            return None
        pc, pos, caps, reps = pop()


class Match:
    """Result of a successful match. Mirrors the parts of ``re.Match`` we support."""

    __slots__ = ("_caps", "_end", "_ngroups", "_start", "pattern", "string")

    def __init__(
        self,
        pattern: Pattern,
        string: str,
        start: int,
        end: int,
        caps: tuple[int, ...],
    ) -> None:
        self.pattern = pattern
        self.string = string
        self._start = start
        self._end = end
        self._caps = caps
        self._ngroups = pattern.groups

    def _span(self, index: object) -> tuple[int, int]:
        if isinstance(index, bool) or not isinstance(index, int):
            raise IndexError("no such group")
        if index == 0:
            return self._start, self._end
        if index < 0 or index > self._ngroups:
            raise IndexError("no such group")
        slot = 2 * (index - 1)
        s = self._caps[slot]
        e = self._caps[slot + 1]
        if s < 0 or e < 0:
            return -1, -1
        return s, e

    def _value(self, index: object, default: object = None) -> object:
        s, e = self._span(index)
        if s < 0:
            return default
        return self.string[s:e]

    def group(self, *indices: int) -> object:
        if not indices:
            return self._value(0)
        if len(indices) == 1:
            return self._value(indices[0])
        return tuple(self._value(i) for i in indices)

    def __getitem__(self, index: int) -> object:
        return self._value(index)

    def groups(self, default: object = None) -> tuple:
        return tuple(self._value(i, default) for i in range(1, self._ngroups + 1))

    def span(self, index: int = 0) -> tuple[int, int]:
        return self._span(index)

    def start(self, index: int = 0) -> int:
        return self._span(index)[0]

    def end(self, index: int = 0) -> int:
        return self._span(index)[1]

    def __repr__(self) -> str:
        return f"<miniregex.Match span={self.span()!r}, match={self.group()!r}>"


class Pattern:
    """A compiled pattern. Create with :func:`miniregex.compile`."""

    __slots__ = ("_ncaps", "_prog", "groups", "pattern")

    def __init__(self, pattern: str, prog: list[tuple], ngroups: int) -> None:
        self.pattern = pattern
        self.groups = ngroups
        self._prog = prog
        self._ncaps = 2 * ngroups

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"

    def _attempt(self, text: str, start: int, must_advance: bool, match_all: bool) -> Match | None:
        result = _run(self._prog, self._ncaps, text, start, must_advance, match_all)
        if result is None:
            return None
        end, caps = result
        return Match(self, text, start, end, caps)

    def _search(self, text: str, start: int, must_advance: bool) -> Match | None:
        # Like sre, must_advance only applies at the first attempted position.
        for s in range(start, len(text) + 1):
            m = self._attempt(text, s, must_advance and s == start, False)
            if m is not None:
                return m
        return None

    def match(self, text: str) -> Match | None:
        _check_text(text)
        return self._attempt(text, 0, False, False)

    def fullmatch(self, text: str) -> Match | None:
        _check_text(text)
        return self._attempt(text, 0, False, True)

    def search(self, text: str) -> Match | None:
        _check_text(text)
        return self._search(text, 0, False)

    def finditer(self, text: str) -> Iterator[Match]:
        _check_text(text)
        pos = 0
        must_advance = False
        n = len(text)
        while pos <= n:
            m = self._search(text, pos, must_advance)
            if m is None:
                return
            yield m
            start, end = m.span()
            must_advance = start == end
            pos = end

    def findall(self, text: str) -> list:
        out: list = []
        ngroups = self.groups
        for m in self.finditer(text):
            if ngroups == 0:
                out.append(m.group())
            elif ngroups == 1:
                out.append(m.group(1) or "")
            else:
                out.append(tuple(m.group(i) or "" for i in range(1, ngroups + 1)))
        return out


def _check_text(text: object) -> None:
    if not isinstance(text, str):
        raise TypeError(f"expected string, got {type(text).__name__}")


def compile(pattern: str) -> Pattern:  # noqa: A001
    """Compile ``pattern`` into a :class:`Pattern`; raise ``RegexError`` if invalid."""
    ast, ngroups = parse(pattern)
    return Pattern(pattern, compile_ast(ast), ngroups)
