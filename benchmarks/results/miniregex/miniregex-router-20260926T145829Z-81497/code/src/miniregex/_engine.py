"""Compiler and backtracking virtual machine.

The program layout and the matcher follow CPython's ``_sre`` closely: the
same opcodes (REPEAT_ONE / MIN_REPEAT_ONE for single-character bodies,
REPEAT + MAX_UNTIL / MIN_UNTIL otherwise), the same zero-width iteration
guard, and the same points where capture marks are saved and restored.
Matching that structure is what makes group values and spans agree with
``re`` in the corner cases (groups inside repetitions, failed alternatives).
"""

from __future__ import annotations

from collections.abc import Callable, Generator

from ._parser import (
    ANY,
    AT,
    BEGINNING,
    BRANCH,
    CATEGORY,
    LITERAL,
    RANGE,
    REPEAT,
    SUBPATTERN,
    UNIT_OPS,
)

# Opcodes
OP_CHAR = 0  # (OP_CHAR, predicate)
OP_AT_BEGINNING = 1
OP_AT_END = 2
OP_MARK = 3  # (OP_MARK, index)
OP_JUMP = 4  # (OP_JUMP, target)
OP_BRANCH = 5  # (OP_BRANCH, [alternative start pcs])
OP_REPEAT_ONE = 6  # (op, min, max, predicate)
OP_MIN_REPEAT_ONE = 7  # (op, min, max, predicate)
OP_REPEAT = 8  # (OP_REPEAT, min, max, body_pc, until_pc)
OP_MAX_UNTIL = 9
OP_MIN_UNTIL = 10
OP_SUCCESS = 11

Predicate = Callable[[str], bool]

_WORD = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_DIGIT = frozenset("0123456789")
_SPACE = frozenset(" \t\n\r\f\v")
_CATEGORIES: dict[str, tuple[frozenset[str], bool]] = {
    "d": (_DIGIT, False),
    "D": (_DIGIT, True),
    "w": (_WORD, False),
    "W": (_WORD, True),
    "s": (_SPACE, False),
    "S": (_SPACE, True),
}


def _set_predicate(negate: bool, members: tuple) -> Predicate:
    chars: set[str] = set()
    ranges: list[tuple[str, str]] = []
    categories: list[tuple[frozenset[str], bool]] = []
    for member in members:
        if member[0] == LITERAL:
            chars.add(member[1])
        elif member[0] == RANGE:
            ranges.append((member[1], member[2]))
        elif member[0] == CATEGORY:
            categories.append(_CATEGORIES[member[1]])
    frozen = frozenset(chars)

    def contains(c: str) -> bool:
        if c in frozen:
            return True
        for lo, hi in ranges:
            if lo <= c <= hi:
                return True
        for cset, inverted in categories:
            if (c in cset) != inverted:
                return True
        return False

    if negate:
        return lambda c: not contains(c)
    return contains


def _unit_predicate(item: tuple) -> Predicate:
    kind = item[0]
    if kind == LITERAL:
        ch = item[1]
        return lambda c: c == ch
    if kind == ANY:
        return lambda c: c != "\n"
    return _set_predicate(item[1], item[2])


def _simple(items: list) -> bool:
    if len(items) != 1:
        return False
    item = items[0]
    if item[0] == SUBPATTERN:
        return item[1] is None and _simple(item[2])
    return item[0] in UNIT_OPS


def _unit_of(items: list) -> tuple:
    item = items[0]
    while item[0] == SUBPATTERN:
        item = item[2][0]
    return item


def compile_program(items: list) -> list[tuple]:
    code: list = []
    _emit(items, code)
    code.append((OP_SUCCESS,))
    return code


def _emit(items: list, code: list) -> None:
    for item in items:
        kind = item[0]
        if kind in UNIT_OPS:
            code.append((OP_CHAR, _unit_predicate(item)))
        elif kind == AT:
            code.append((OP_AT_BEGINNING,) if item[1] == BEGINNING else (OP_AT_END,))
        elif kind == SUBPATTERN:
            group = item[1]
            if group is not None:
                code.append((OP_MARK, 2 * (group - 1)))
            _emit(item[2], code)
            if group is not None:
                code.append((OP_MARK, 2 * (group - 1) + 1))
        elif kind == BRANCH:
            head = len(code)
            code.append(None)
            starts = []
            jumps = []
            for alt in item[1]:
                starts.append(len(code))
                _emit(alt, code)
                jumps.append(len(code))
                code.append(None)
            code[head] = (OP_BRANCH, starts)
            for j in jumps:
                code[j] = (OP_JUMP, len(code))
        elif kind == REPEAT:
            _, lo, hi, lazy, body = item
            if _simple(body):
                op = OP_MIN_REPEAT_ONE if lazy else OP_REPEAT_ONE
                code.append((op, lo, hi, _unit_predicate(_unit_of(body))))
            else:
                head = len(code)
                code.append(None)
                _emit(body, code)
                until = len(code)
                code.append((OP_MIN_UNTIL if lazy else OP_MAX_UNTIL,))
                code[head] = (OP_REPEAT, lo, hi, head + 1, until)
        else:  # pragma: no cover - parser never produces anything else
            raise AssertionError(kind)


class _RepeatContext:
    __slots__ = ("count", "lo", "hi", "body", "prev", "last_ptr")

    def __init__(self, lo: int, hi: int | None, body: int, prev: _RepeatContext | None):
        self.count = -1
        self.lo = lo
        self.hi = hi
        self.body = body
        self.prev = prev
        self.last_ptr: int | None = None


class Matcher:
    """State for one matching attempt series over a single string."""

    def __init__(self, code: list, ngroups: int, text: str, match_all: bool, must_advance: bool):
        self.code = code
        self.text = text
        self.end = len(text)
        self.nmarks = 2 * ngroups
        self.marks: list[int | None] = [None] * self.nmarks
        self.lastmark = -1
        self.repeat: _RepeatContext | None = None
        self.start = 0
        self.match_all = match_all
        self.must_advance = must_advance
        self.end_ptr = -1

    def reset(self, start: int) -> None:
        self.marks = [None] * self.nmarks
        self.lastmark = -1
        self.repeat = None
        self.start = start

    def spans(self) -> list[tuple[int, int]]:
        result = [(self.start, self.end_ptr)]
        marks = self.marks
        for j in range(0, self.nmarks, 2):
            a, b = marks[j], marks[j + 1]
            if j + 1 <= self.lastmark and a is not None and b is not None:
                result.append((a, b))
            else:
                result.append((-1, -1))
        return result

    def _save_marks(self) -> list[int | None]:
        return self.marks[: self.lastmark + 1]

    def _restore_marks(self, saved: list[int | None]) -> None:
        self.marks[: len(saved)] = saved

    def run(self, pc: int, ptr: int) -> bool:
        """Match the program from ``pc`` at ``ptr``.

        Backtracking points are generators that yield ``(pc, ptr)`` sub-calls;
        this driver runs them on an explicit stack so deep repetitions are not
        limited by Python's recursion limit.
        """
        stack = [self._run(pc, ptr)]
        result = None
        while stack:
            try:
                request = stack[-1].send(result)
            except StopIteration as stop:
                stack.pop()
                result = stop.value
                continue
            stack.append(self._run(*request))
            result = None
        return result

    def _run(self, pc: int, ptr: int) -> Generator[tuple[int, int], bool, bool]:
        code = self.code
        text = self.text
        end = self.end
        while True:
            op = code[pc]
            kind = op[0]

            if kind == OP_CHAR:
                if ptr >= end or not op[1](text[ptr]):
                    return False
                ptr += 1
                pc += 1

            elif kind == OP_MARK:
                i = op[1]
                if i > self.lastmark:
                    for j in range(self.lastmark + 1, i):
                        self.marks[j] = None
                    self.lastmark = i
                self.marks[i] = ptr
                pc += 1

            elif kind == OP_JUMP:
                pc = op[1]

            elif kind == OP_AT_BEGINNING:
                if ptr != 0:
                    return False
                pc += 1

            elif kind == OP_AT_END:
                if not (ptr == end or (ptr == end - 1 and text[ptr] == "\n")):
                    return False
                pc += 1

            elif kind == OP_SUCCESS:
                if (self.match_all and ptr != end) or (self.must_advance and ptr == self.start):
                    return False
                self.end_ptr = ptr
                return True

            elif kind == OP_BRANCH:
                lastmark = self.lastmark
                saved = self._save_marks() if self.repeat is not None else None
                for alt in op[1]:
                    if (yield alt, ptr):
                        return True
                    if saved is not None:
                        self._restore_marks(saved)
                    self.lastmark = lastmark
                return False

            elif kind == OP_REPEAT_ONE:
                _, lo, hi, pred = op
                if lo > end - ptr:
                    return False
                limit = end - ptr if hi is None else min(hi, end - ptr)
                count = 0
                while count < limit and pred(text[ptr + count]):
                    count += 1
                if count < lo:
                    return False
                ptr += count
                lastmark = self.lastmark
                saved = self._save_marks() if self.repeat is not None else None
                tail = pc + 1
                while count >= lo:
                    if (yield tail, ptr):
                        return True
                    if saved is not None:
                        self._restore_marks(saved)
                    self.lastmark = lastmark
                    ptr -= 1
                    count -= 1
                return False

            elif kind == OP_MIN_REPEAT_ONE:
                _, lo, hi, pred = op
                if lo > end - ptr:
                    return False
                count = 0
                while count < lo:
                    if not pred(text[ptr]):
                        return False
                    ptr += 1
                    count += 1
                lastmark = self.lastmark
                saved = self._save_marks() if self.repeat is not None else None
                tail = pc + 1
                while hi is None or count <= hi:
                    if (yield tail, ptr):
                        return True
                    if saved is not None:
                        self._restore_marks(saved)
                    self.lastmark = lastmark
                    if ptr >= end or not pred(text[ptr]):
                        break
                    ptr += 1
                    count += 1
                return False

            elif kind == OP_REPEAT:
                _, lo, hi, body, until = op
                rep = _RepeatContext(lo, hi, body, self.repeat)
                self.repeat = rep
                ok = (yield until, ptr)
                self.repeat = rep.prev
                return ok

            elif kind == OP_MAX_UNTIL:
                rep = self.repeat
                assert rep is not None
                count = rep.count + 1
                if count < rep.lo:
                    rep.count = count
                    if (yield rep.body, ptr):
                        return True
                    rep.count = count - 1
                    return False
                if (rep.hi is None or count < rep.hi) and ptr != rep.last_ptr:
                    rep.count = count
                    lastmark = self.lastmark
                    saved = self._save_marks()
                    last_ptr = rep.last_ptr
                    rep.last_ptr = ptr
                    ok = (yield rep.body, ptr)
                    rep.last_ptr = last_ptr
                    if ok:
                        return True
                    self._restore_marks(saved)
                    self.lastmark = lastmark
                    rep.count = count - 1
                self.repeat = rep.prev
                ok = (yield pc + 1, ptr)
                self.repeat = rep
                return ok

            elif kind == OP_MIN_UNTIL:
                rep = self.repeat
                assert rep is not None
                count = rep.count + 1
                if count < rep.lo:
                    rep.count = count
                    if (yield rep.body, ptr):
                        return True
                    rep.count = count - 1
                    return False
                self.repeat = rep.prev
                lastmark = self.lastmark
                saved = self._save_marks() if self.repeat is not None else None
                ok = (yield pc + 1, ptr)
                self.repeat = rep
                if ok:
                    return True
                if saved is not None:
                    self._restore_marks(saved)
                self.lastmark = lastmark
                if (rep.hi is not None and count >= rep.hi) or ptr == rep.last_ptr:
                    return False
                rep.count = count
                last_ptr = rep.last_ptr
                rep.last_ptr = ptr
                ok = (yield rep.body, ptr)
                rep.last_ptr = last_ptr
                if ok:
                    return True
                rep.count = count - 1
                return False

            else:  # pragma: no cover
                raise AssertionError(kind)
