"""Explicit-stack backtracking VM.

State consists of ``pc``, ``pos`` and a register file ``regs`` holding the
capture slots followed by two registers per general repetition (iteration
count and start position of the last optional iteration).  Every register
write is logged on an undo trail, and every backtrack entry records the trail
length, so backtracking restores captures and loop state exactly.
"""

from __future__ import annotations

import sys

from . import _parser as P
from ._compiler import (
    ANY,
    AT,
    CHAR,
    JMP,
    MATCH,
    REPEAT_INIT,
    SAVE,
    SET,
    SPLIT,
    STAR,
    UNTIL_MAX,
    UNTIL_MIN,
    Program,
    _any_test,
)

# Backtrack entry kinds
_BT_PLAIN = 0  # resume at (pc, pos)
_BT_GREEDY_STAR = 1  # retry greedy STAR with one char fewer
_BT_LAZY_STAR = 2  # retry lazy STAR with one char more
_BT_LAZY_MORE = 3  # lazy general repeat: try one more iteration

# Python 3.14 changed \B so that it matches the empty string.
_NON_BOUNDARY_EMPTY = sys.version_info >= (3, 14)


def _check_at(kind: str, text: str, pos: int, n: int) -> bool:
    if kind == P.AT_BEGINNING or kind == P.AT_BEGINNING_STRING:
        return pos == 0
    if kind == P.AT_END:
        return pos == n or (pos == n - 1 and text[pos] == "\n")
    if kind == P.AT_END_STRING:
        return pos == n
    if kind == P.AT_BOUNDARY:
        if n == 0:
            return False
        before = pos > 0 and P.is_word(text[pos - 1])
        after = pos < n and P.is_word(text[pos])
        return before != after
    if kind == P.AT_NON_BOUNDARY:
        if n == 0:
            return _NON_BOUNDARY_EMPTY
        before = pos > 0 and P.is_word(text[pos - 1])
        after = pos < n and P.is_word(text[pos])
        return before == after
    raise AssertionError(kind)  # pragma: no cover


def run(prog: Program, text: str, start: int, full: bool, must_advance: bool):
    """Try to match at ``start``. Returns the register list or ``None``."""
    code = prog.code
    n = len(text)
    regs = [-1] * prog.nregs
    trail: list = []
    stack: list = []
    pc = 0
    pos = start

    while True:
        op = code[pc]
        c = op[0]
        if c == CHAR:
            if pos < n and text[pos] == op[1]:
                pos += 1
                pc += 1
                continue
        elif c == SAVE:
            i = op[1]
            trail.append((i, regs[i]))
            regs[i] = pos
            pc += 1
            continue
        elif c == SPLIT:
            stack.append((_BT_PLAIN, op[1], pos, len(trail), 0))
            pc += 1
            continue
        elif c == JMP:
            pc = op[1]
            continue
        elif c == SET:
            if pos < n and op[1](text[pos]):
                pos += 1
                pc += 1
                continue
        elif c == ANY:
            if pos < n and text[pos] != "\n":
                pos += 1
                pc += 1
                continue
        elif c == STAR:
            _, test, lo, hi, greedy = op
            if greedy:
                limit = n if hi is None else min(n, pos + hi)
                if test is _any_test:
                    nl = text.find("\n", pos, limit)
                    p = limit if nl < 0 else nl
                else:
                    p = pos
                    while p < limit and test(text[p]):
                        p += 1
                count = p - pos
                if count >= lo:
                    if count > lo:
                        stack.append((_BT_GREEDY_STAR, pc, pos, len(trail), count - 1))
                    pos = p
                    pc += 1
                    continue
            else:
                limit = pos + lo
                if limit <= n:
                    p = pos
                    while p < limit and test(text[p]):
                        p += 1
                    if p == limit:
                        stack.append((_BT_LAZY_STAR, pc, pos, len(trail), lo))
                        pos = p
                        pc += 1
                        continue
        elif c == AT:
            if _check_at(op[1], text, pos, n):
                pc += 1
                continue
        elif c == REPEAT_INIT:
            reg = op[1]
            trail.append((reg, regs[reg]))
            trail.append((reg + 1, regs[reg + 1]))
            regs[reg] = 0
            regs[reg + 1] = -1
            pc = op[2]
            continue
        elif c == UNTIL_MAX:
            _, reg, lo, hi, body = op
            count = regs[reg]
            if count < lo:
                trail.append((reg, count))
                regs[reg] = count + 1
                pc = body
                continue
            if (hi is None or count < hi) and pos != regs[reg + 1]:
                # Prefer another iteration; fall back to the tail.
                stack.append((_BT_PLAIN, pc + 1, pos, len(trail), 0))
                trail.append((reg, count))
                trail.append((reg + 1, regs[reg + 1]))
                regs[reg] = count + 1
                regs[reg + 1] = pos
                pc = body
                continue
            pc += 1
            continue
        elif c == UNTIL_MIN:
            _, reg, lo, hi, body = op
            count = regs[reg]
            if count < lo:
                trail.append((reg, count))
                regs[reg] = count + 1
                pc = body
                continue
            # Prefer the tail; fall back to another iteration.
            stack.append((_BT_LAZY_MORE, pc, pos, len(trail), 0))
            pc += 1
            continue
        elif c == MATCH:
            if not ((full and pos != n) or (must_advance and pos == start)):
                regs[0] = start
                regs[1] = pos
                return regs
        else:  # pragma: no cover
            raise AssertionError(c)

        # ---- failure: backtrack ----
        while True:
            if not stack:
                return None
            kind, pc, pos, tl, extra = stack.pop()
            if len(trail) > tl:
                for k in range(len(trail) - 1, tl - 1, -1):
                    i, v = trail[k]
                    regs[i] = v
                del trail[tl:]
            if kind == _BT_PLAIN:
                break
            if kind == _BT_GREEDY_STAR:
                if extra > code[pc][2]:
                    stack.append((_BT_GREEDY_STAR, pc, pos, tl, extra - 1))
                pos += extra
                pc += 1
                break
            if kind == _BT_LAZY_STAR:
                op = code[pc]
                hi = op[3]
                p = pos + extra
                if (hi is None or extra < hi) and p < n and op[1](text[p]):
                    stack.append((_BT_LAZY_STAR, pc, pos, tl, extra + 1))
                    pos = p + 1
                    pc += 1
                    break
                continue
            # _BT_LAZY_MORE
            op = code[pc]
            _, reg, lo, hi, body = op
            count = regs[reg]
            if (hi is not None and count >= hi) or pos == regs[reg + 1]:
                continue
            trail.append((reg, count))
            trail.append((reg + 1, regs[reg + 1]))
            regs[reg] = count + 1
            regs[reg + 1] = pos
            pc = body
            break
