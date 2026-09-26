"""Backtracking VM plus the public ``Pattern`` and ``Match`` classes.

The VM keeps an explicit backtrack stack (no Python recursion), so long inputs do
not hit the recursion limit. Machine state is ``(pc, pos, caps, reps)`` where
``caps`` is an immutable tuple of capture slots and ``reps`` an immutable linked
list of active repeat frames ``(count, last_pos, parent)``. Because both are
persistent values, backtracking restores captures and loop counters exactly.
"""

from __future__ import annotations

from collections.abc import Iterator

from .compiler import (
    ANY,
    BOL,
    CHAR,
    EOL,
    JMP,
    MATCH,
    REPEAT,
    REPEAT_ONE,
    SAVE,
    SET,
    SPLIT,
    UNTIL,
    Instr,
    compile_program,
)
from .parser import parse

# Backtrack entry kinds.
_STATE = 0  # (kind, pc, pos, caps, reps)
_GREEDY_ONE = 1  # (kind, pc, pos, lo, caps, reps): retry tail at pos, then pos-1 ... lo
_LAZY_ONE = 2  # (kind, pc, pos, count, max, test, caps, reps): extend by one char


def _run(
    prog: list[Instr],
    text: str,
    start: int,
    init_caps: tuple,
    fullmatch: bool,
    must_advance: bool,
) -> tuple[int, tuple] | None:
    """Try to match ``prog`` anchored at ``start``. Returns ``(end, caps)`` or None."""
    n = len(text)
    stack: list[tuple] = []
    push = stack.append
    pop = stack.pop
    pc = 0
    pos = start
    caps = init_caps
    reps: tuple | None = None

    while True:
        op = prog[pc]
        code = op[0]
        if code == CHAR:
            if pos < n and text[pos] == op[1]:
                pos += 1
                pc += 1
                continue
        elif code == ANY:
            if pos < n and text[pos] != "\n":
                pos += 1
                pc += 1
                continue
        elif code == SET:
            if pos < n and op[1].contains(text[pos]):
                pos += 1
                pc += 1
                continue
        elif code == SAVE:
            k = op[1]
            caps = caps[:k] + (pos,) + caps[k + 1 :]
            pc += 1
            continue
        elif code == SPLIT:
            push((_STATE, op[2], pos, caps, reps))
            pc = op[1]
            continue
        elif code == JMP:
            pc = op[1]
            continue
        elif code == BOL:
            if pos == 0:
                pc += 1
                continue
        elif code == EOL:
            if pos == n or (pos == n - 1 and text[pos] == "\n"):
                pc += 1
                continue
        elif code == REPEAT:
            reps = (-1, None, reps)
            pc = op[1]
            continue
        elif code == UNTIL:
            _, mn, mx, greedy, body = op
            assert reps is not None
            count, last, parent = reps
            count += 1
            if count < mn:
                # Mandatory iteration; no zero-width protection (as in sre).
                reps = (count, last, parent)
                pc = body
                continue
            can_iterate = (mx is None or count < mx) and pos != last
            if greedy:
                if can_iterate:
                    push((_STATE, pc + 1, pos, caps, parent))
                    reps = (count, pos, parent)
                    pc = body
                    continue
            elif can_iterate:
                push((_STATE, body, pos, caps, (count, pos, parent)))
            reps = parent
            pc += 1
            continue
        elif code == REPEAT_ONE:
            _, test, mn, mx, greedy = op
            limit = n if mx is None else min(n, pos + mx)
            if greedy:
                end = pos
                while end < limit and test(text[end]):
                    end += 1
                lo = pos + mn
                if end >= lo:
                    if end > lo:
                        push((_GREEDY_ONE, pc + 1, end - 1, lo, caps, reps))
                    pos = end
                    pc += 1
                    continue
            else:
                end = pos
                need = pos + mn
                if need <= n:
                    while end < need and test(text[end]):
                        end += 1
                    if end == need:
                        if mx is None or mn < mx:
                            push((_LAZY_ONE, pc + 1, end, mn, mx, test, caps, reps))
                        pos = end
                        pc += 1
                        continue
        elif code == MATCH:
            if (not fullmatch or pos == n) and not (must_advance and pos == start):
                return pos, caps
        else:  # pragma: no cover - defensive
            raise RuntimeError(f"bad opcode {code}")

        # ---- failure: backtrack ------------------------------------------
        while True:
            if not stack:
                return None
            entry = pop()
            kind = entry[0]
            if kind == _STATE:
                _, pc, pos, caps, reps = entry
                break
            if kind == _GREEDY_ONE:
                _, pc, pos, lo, caps, reps = entry
                if pos > lo:
                    push((_GREEDY_ONE, pc, pos - 1, lo, caps, reps))
                break
            # _LAZY_ONE
            _, pc, cur, count, mx, test, caps, reps = entry
            if cur < n and test(text[cur]):
                count += 1
                if mx is None or count < mx:
                    push((_LAZY_ONE, pc, cur + 1, count, mx, test, caps, reps))
                pos = cur + 1
                break


class Match:
    """Result of a successful match. Mirrors the core of ``re.Match``."""

    __slots__ = ("_spans", "re", "string", "pos", "endpos")

    def __init__(
        self,
        pattern: Pattern,
        string: str,
        spans: tuple[tuple[int, int] | None, ...],
        pos: int,
        endpos: int,
    ) -> None:
        self.re = pattern
        self.string = string
        self._spans = spans
        self.pos = pos
        self.endpos = endpos

    def _index(self, group: object) -> int:
        if isinstance(group, bool) or not isinstance(group, int):
            raise IndexError("no such group")
        if group < 0 or group >= len(self._spans):
            raise IndexError("no such group")
        return group

    def _get(self, group: object, default: str | None = None) -> str | None:
        span = self._spans[self._index(group)]
        if span is None:
            return default
        return self.string[span[0] : span[1]]

    def group(self, *groups: int) -> str | None | tuple[str | None, ...]:
        """Return one group (default 0 = whole match) or a tuple of several."""
        if not groups:
            return self._get(0)
        if len(groups) == 1:
            return self._get(groups[0])
        return tuple(self._get(g) for g in groups)

    def __getitem__(self, group: int) -> str | None:
        return self._get(group)

    def groups(self, default: str | None = None) -> tuple[str | None, ...]:
        """All capturing groups; ``default`` for groups that did not participate."""
        return tuple(self._get(g, default) for g in range(1, len(self._spans)))

    def span(self, group: int = 0) -> tuple[int, int]:
        span = self._spans[self._index(group)]
        return (-1, -1) if span is None else span

    def start(self, group: int = 0) -> int:
        return self.span(group)[0]

    def end(self, group: int = 0) -> int:
        return self.span(group)[1]

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self.group()!r}>"


class Pattern:
    """A compiled regular expression."""

    __slots__ = ("pattern", "groups", "_prog", "_init_caps")

    def __init__(self, pattern: str) -> None:
        node, ngroups = parse(pattern)
        self.pattern = pattern
        self.groups = ngroups
        self._prog = compile_program(node)
        self._init_caps = (None,) * (2 * (ngroups + 1))

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Pattern) and other.pattern == self.pattern

    def __hash__(self) -> int:
        return hash(self.pattern)

    # -- internals ---------------------------------------------------------

    def _make(self, text: str, start: int, end: int, caps: tuple) -> Match:
        spans: list[tuple[int, int] | None] = [(start, end)]
        for g in range(1, self.groups + 1):
            s, e = caps[2 * g], caps[2 * g + 1]
            spans.append(None if s is None or e is None else (s, e))
        return Match(self, text, tuple(spans), 0, len(text))

    def _at(self, text: str, start: int, full: bool, must_advance: bool) -> Match | None:
        res = _run(self._prog, text, start, self._init_caps, full, must_advance)
        if res is None:
            return None
        return self._make(text, start, res[0], res[1])

    def _search(self, text: str, start: int, must_advance: bool) -> Match | None:
        # Like sre: must_advance only applies at the first candidate position.
        for i in range(start, len(text) + 1):
            m = self._at(text, i, False, must_advance and i == start)
            if m is not None:
                return m
        return None

    @staticmethod
    def _check(text: object) -> str:
        if not isinstance(text, str):
            raise TypeError(f"expected string, got {type(text).__name__}")
        return text

    # -- public API --------------------------------------------------------

    def fullmatch(self, text: str) -> Match | None:
        """Match the whole of ``text``."""
        return self._at(self._check(text), 0, True, False)

    def match(self, text: str) -> Match | None:
        """Match at the beginning of ``text`` (not necessarily to its end)."""
        return self._at(self._check(text), 0, False, False)

    def search(self, text: str) -> Match | None:
        """Find the leftmost match anywhere in ``text``."""
        return self._search(self._check(text), 0, False)

    def finditer(self, text: str) -> Iterator[Match]:
        """Iterate over successive non-overlapping matches (``re.finditer`` rules)."""
        text = self._check(text)
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
        """Return all matches in the same shape as ``re.findall``."""
        out: list = []
        for m in self.finditer(text):
            if self.groups == 0:
                out.append(m.group())
            elif self.groups == 1:
                out.append(m.groups("")[0])
            else:
                out.append(m.groups(""))
        return out


def compile(pattern: str) -> Pattern:
    """Compile ``pattern``; raises :class:`RegexError` if it is malformed."""
    return Pattern(pattern)
