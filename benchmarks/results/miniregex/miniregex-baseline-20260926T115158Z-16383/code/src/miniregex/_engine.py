"""Compiler and backtracking matcher.

The syntax tree is compiled into a flat list of instructions that mirrors the opcodes of
CPython's ``_sre`` engine, and the matcher follows ``_sre``'s backtracking algorithm,
including how capture marks are saved and restored and how repetitions guard against
empty iterations. Following that design closely is what makes group values and spans
(especially for groups inside repetitions and alternations) identical to ``re``.
"""

from __future__ import annotations

import sys

from ._parser import (
    ANY,
    AT,
    AT_BEGINNING,
    BRANCH,
    IN,
    LITERAL,
    MAXREPEAT,
    REPEAT,
    SUBPATTERN,
)

# Instruction opcodes. Each instruction is a list whose first element is the opcode.
OP_LITERAL = 0  # [op, ch]
OP_ANY = 1  # [op]
OP_IN = 2  # [op, charset]
OP_AT_BEGINNING = 3  # [op]
OP_AT_END = 4  # [op]
OP_MARK = 5  # [op, mark_index]
OP_BRANCH = 6  # [op, [first_pc_of_each_alternative]]
OP_JUMP = 7  # [op, target_pc]
OP_REPEAT_ONE = 8  # [op, min, max, unit_instruction]  (greedy, single-character body)
OP_MIN_REPEAT_ONE = 9  # [op, min, max, unit_instruction]  (lazy, single-character body)
OP_REPEAT = 10  # [op, min, max, until_pc]  body starts at pc + 1
OP_MAX_UNTIL = 11  # [op]  end of a greedy repeat body
OP_MIN_UNTIL = 12  # [op]  end of a lazy repeat body
OP_SUCCESS = 13  # [op]

_UNIT_NODES = (LITERAL, ANY, IN)


def _is_simple(seq: list) -> bool:
    """True if ``seq`` always matches exactly one character (``_sre``'s REPEAT_ONE case)."""
    if len(seq) != 1:
        return False
    op, arg = seq[0]
    if op is SUBPATTERN:
        return arg[0] is None and _is_simple(arg[1])
    return op in _UNIT_NODES


def _unit(seq: list) -> list:
    op, arg = seq[0]
    if op is SUBPATTERN:
        return _unit(arg[1])
    if op is LITERAL:
        return [OP_LITERAL, arg]
    if op is ANY:
        return [OP_ANY]
    return [OP_IN, arg]


def compile_tree(tree: list) -> list:
    code: list = []
    _compile(code, tree)
    code.append([OP_SUCCESS])
    return code


def _compile(code: list, seq: list) -> None:
    for op, arg in seq:
        if op in _UNIT_NODES:
            code.append(_unit([(op, arg)]))
        elif op is AT:
            code.append([OP_AT_BEGINNING] if arg is AT_BEGINNING else [OP_AT_END])
        elif op is SUBPATTERN:
            group, body = arg
            if group is not None:
                code.append([OP_MARK, 2 * (group - 1)])
            _compile(code, body)
            if group is not None:
                code.append([OP_MARK, 2 * (group - 1) + 1])
        elif op is BRANCH:
            branch = [OP_BRANCH, []]
            code.append(branch)
            jumps = []
            for alternative in arg:
                branch[1].append(len(code))
                _compile(code, alternative)
                jump = [OP_JUMP, None]
                code.append(jump)
                jumps.append(jump)
            for jump in jumps:
                jump[1] = len(code)
        elif op is REPEAT:
            lo, hi, greedy, body = arg
            if _is_simple(body):
                code.append([OP_REPEAT_ONE if greedy else OP_MIN_REPEAT_ONE, lo, hi, _unit(body)])
            else:
                repeat = [OP_REPEAT, lo, hi, None]
                code.append(repeat)
                _compile(code, body)
                repeat[3] = len(code)
                code.append([OP_MAX_UNTIL if greedy else OP_MIN_UNTIL])
        else:  # pragma: no cover
            raise AssertionError(f"unknown node {op!r}")


class _Repeat:
    """Runtime context of an active general repeat (``_sre``'s SRE_REPEAT)."""

    __slots__ = ("count", "body", "min", "max", "last_ptr", "prev")

    def __init__(self, body: int, lo: int, hi: int, prev: _Repeat | None) -> None:
        self.count = -1
        self.body = body
        self.min = lo
        self.max = hi
        self.last_ptr = -1
        self.prev = prev


class State:
    """Matching state for one match attempt sequence over ``text``."""

    def __init__(self, code: list, ngroups: int, text: str) -> None:
        self.code = code
        self.text = text
        self.end = len(text)
        self.marks: list[int | None] = [None] * (2 * ngroups)
        self.lastmark = -1
        self.repeat: _Repeat | None = None
        self.start = 0
        self.ptr = 0
        self.match_all = False
        self.must_advance = False

    # -- public entry points -------------------------------------------------------------

    def match(self, start: int) -> bool:
        """Try to match at exactly ``start``; on success the match ends at ``self.ptr``."""
        self.start = start
        self.lastmark = -1
        self.repeat = None
        with _recursion_room(self.end):
            return self._run(0, start)

    def search(self, start: int, must_advance: bool = False) -> bool:
        """Find the leftmost match at or after ``start``; sets ``self.start``/``self.ptr``.

        With ``must_advance``, a match at ``start`` itself must not be empty (this is how
        ``findall`` steps past an empty match).
        """
        with _recursion_room(self.end):
            pos = start
            self.must_advance = must_advance
            try:
                while pos <= self.end:
                    self.start = pos
                    self.lastmark = -1
                    self.repeat = None
                    if self._run(0, pos):
                        return True
                    self.must_advance = False
                    if self.code[0][0] == OP_AT_BEGINNING:
                        break
                    pos += 1
            finally:
                self.must_advance = False
        return False

    def span(self, group: int) -> tuple[int, int]:
        if group == 0:
            return (self.start, self.ptr)
        j = 2 * (group - 1)
        marks = self.marks
        if j + 1 <= self.lastmark and marks[j] is not None and marks[j + 1] is not None:
            return (marks[j], marks[j + 1])
        return (-1, -1)

    # -- matcher -------------------------------------------------------------------------

    def _unit_matches(self, unit: list, ptr: int) -> bool:
        if ptr >= self.end:
            return False
        ch = self.text[ptr]
        kind = unit[0]
        if kind == OP_LITERAL:
            return ch == unit[1]
        if kind == OP_ANY:
            return ch != "\n"
        return ch in unit[1]

    def _count(self, unit: list, ptr: int, maxcount: int) -> int:
        """Number of consecutive characters from ``ptr`` matching ``unit`` (at most maxcount)."""
        limit = min(self.end, ptr + maxcount) if maxcount < MAXREPEAT else self.end
        text = self.text
        i = ptr
        kind = unit[0]
        if kind == OP_LITERAL:
            ch = unit[1]
            while i < limit and text[i] == ch:
                i += 1
        elif kind == OP_ANY:
            while i < limit and text[i] != "\n":
                i += 1
        else:
            charset = unit[1]
            while i < limit and text[i] in charset:
                i += 1
        return i - ptr

    def _save_marks(self) -> list | None:
        """MARK_PUSH: snapshot marks up to lastmark."""
        if self.lastmark >= 0:
            return self.marks[: self.lastmark + 1]
        return None

    def _restore_marks(self, saved: list | None) -> None:
        """MARK_POP: restore a snapshot taken by _save_marks."""
        if saved is not None:
            self.marks[: len(saved)] = saved

    def _run(self, pc: int, ptr: int) -> bool:
        code = self.code
        text = self.text
        end = self.end
        while True:
            instr = code[pc]
            op = instr[0]

            if op == OP_LITERAL:
                if ptr >= end or text[ptr] != instr[1]:
                    return False
                ptr += 1
                pc += 1

            elif op == OP_ANY:
                if ptr >= end or text[ptr] == "\n":
                    return False
                ptr += 1
                pc += 1

            elif op == OP_IN:
                if ptr >= end or text[ptr] not in instr[1]:
                    return False
                ptr += 1
                pc += 1

            elif op == OP_MARK:
                i = instr[1]
                if i > self.lastmark:
                    marks = self.marks
                    for j in range(self.lastmark + 1, i):
                        marks[j] = None
                    self.lastmark = i
                self.marks[i] = ptr
                pc += 1

            elif op == OP_AT_BEGINNING:
                if ptr != 0:
                    return False
                pc += 1

            elif op == OP_AT_END:
                if not (ptr == end or (ptr + 1 == end and text[ptr] == "\n")):
                    return False
                pc += 1

            elif op == OP_JUMP:
                pc = instr[1]

            elif op == OP_SUCCESS:
                if (self.match_all and ptr != end) or (self.must_advance and ptr == self.start):
                    return False
                self.ptr = ptr
                return True

            elif op == OP_BRANCH:
                lastmark = self.lastmark
                in_repeat = self.repeat is not None
                saved = self._save_marks() if in_repeat else None
                for alternative in instr[1]:
                    if self._run(alternative, ptr):
                        return True
                    if in_repeat:
                        self._restore_marks(saved)
                    self.lastmark = lastmark
                return False

            elif op == OP_REPEAT_ONE:
                return self._repeat_one(instr, pc, ptr)

            elif op == OP_MIN_REPEAT_ONE:
                return self._min_repeat_one(instr, pc, ptr)

            elif op == OP_REPEAT:
                rep = _Repeat(pc + 1, instr[1], instr[2], self.repeat)
                self.repeat = rep
                matched = self._run(instr[3], ptr)
                self.repeat = rep.prev
                return matched

            elif op == OP_MAX_UNTIL:
                return self._max_until(pc, ptr)

            elif op == OP_MIN_UNTIL:
                return self._min_until(pc, ptr)

            else:  # pragma: no cover
                raise AssertionError(f"bad opcode {op}")

    def _repeat_one(self, instr: list, pc: int, ptr: int) -> bool:
        lo, hi, unit = instr[1], instr[2], instr[3]
        if lo > self.end - ptr:
            return False
        count = self._count(unit, ptr, hi)
        if count < lo:
            return False
        ptr += count
        lastmark = self.lastmark
        in_repeat = self.repeat is not None
        saved = self._save_marks() if in_repeat else None
        while count >= lo:
            if self._run(pc + 1, ptr):
                return True
            if in_repeat:
                self._restore_marks(saved)
            self.lastmark = lastmark
            ptr -= 1
            count -= 1
        return False

    def _min_repeat_one(self, instr: list, pc: int, ptr: int) -> bool:
        lo, hi, unit = instr[1], instr[2], instr[3]
        if lo > self.end - ptr:
            return False
        count = 0
        if lo:
            count = self._count(unit, ptr, lo)
            if count < lo:
                return False
            ptr += count
        lastmark = self.lastmark
        in_repeat = self.repeat is not None
        saved = self._save_marks() if in_repeat else None
        while hi == MAXREPEAT or count <= hi:
            if self._run(pc + 1, ptr):
                return True
            if in_repeat:
                self._restore_marks(saved)
            self.lastmark = lastmark
            if not self._unit_matches(unit, ptr):
                break
            ptr += 1
            count += 1
        return False

    def _max_until(self, pc: int, ptr: int) -> bool:
        rep = self.repeat
        assert rep is not None
        count = rep.count + 1

        if count < rep.min:
            # Not enough iterations yet: the body must match again.
            rep.count = count
            if self._run(rep.body, ptr):
                return True
            rep.count = count - 1
            return False

        if (count < rep.max or rep.max == MAXREPEAT) and ptr != rep.last_ptr:
            # Try one more iteration first (greedy). An iteration that matched the empty
            # string (ptr == last_ptr) is not followed by another one.
            rep.count = count
            lastmark = self.lastmark
            saved = self._save_marks()
            old_last_ptr = rep.last_ptr
            rep.last_ptr = ptr
            matched = self._run(rep.body, ptr)
            rep.last_ptr = old_last_ptr
            if matched:
                return True
            self._restore_marks(saved)
            self.lastmark = lastmark
            rep.count = count - 1

        # Match the tail after the repeat.
        self.repeat = rep.prev
        matched = self._run(pc + 1, ptr)
        self.repeat = rep
        return matched

    def _min_until(self, pc: int, ptr: int) -> bool:
        rep = self.repeat
        assert rep is not None
        count = rep.count + 1

        if count < rep.min:
            rep.count = count
            if self._run(rep.body, ptr):
                return True
            rep.count = count - 1
            return False

        # Try the tail first (lazy).
        self.repeat = rep.prev
        lastmark = self.lastmark
        tail_in_repeat = self.repeat is not None
        saved = self._save_marks() if tail_in_repeat else None
        matched = self._run(pc + 1, ptr)
        self.repeat = rep
        if matched:
            return True
        if tail_in_repeat:
            self._restore_marks(saved)
        self.lastmark = lastmark

        if (count >= rep.max and rep.max != MAXREPEAT) or ptr == rep.last_ptr:
            return False

        rep.count = count
        old_last_ptr = rep.last_ptr
        rep.last_ptr = ptr
        matched = self._run(rep.body, ptr)
        rep.last_ptr = old_last_ptr
        if matched:
            return True
        rep.count = count - 1
        return False


class _recursion_room:
    """Temporarily raise the recursion limit so long texts do not overflow the stack.

    The matcher recurses once per backtracking point (roughly once per iteration of a
    repeat), so the needed depth grows with the length of the text.
    """

    def __init__(self, length: int) -> None:
        self.needed = 4 * length + 1000

    def __enter__(self) -> None:
        self.old = sys.getrecursionlimit()
        if self.needed + 200 > self.old:
            sys.setrecursionlimit(self.old + self.needed)

    def __exit__(self, *exc: object) -> None:
        sys.setrecursionlimit(self.old)
