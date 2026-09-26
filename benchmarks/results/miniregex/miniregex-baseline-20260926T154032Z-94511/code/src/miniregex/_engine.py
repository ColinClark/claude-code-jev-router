"""Compiler and backtracking virtual machine.

The program model mirrors CPython's ``_sre`` closely enough to reproduce its results,
including capture values for groups inside repetitions and the "zero-width match
protection" of general repeats:

* Single-character bodies (``a*``, ``[x-z]+?``, ``.{2,5}``) compile to ``REP1``, which
  counts matches in a loop and backtracks one character at a time.
* Other repeats compile to ``REPEAT_INIT`` + body + ``UNTIL``. Each repeat has a count
  register and a ``last`` register (the position at which the latest optional iteration
  started); an optional iteration is not attempted again at the position where the
  previous optional iteration started, exactly like ``_sre``'s ``MAX_UNTIL``/``MIN_UNTIL``.

All mutable state (group marks, repeat registers) is changed through a trail on the
backtracking stack, so every choice point restores the exact state it saw. The machine
is iterative, so deep inputs never hit Python's recursion limit.
"""

from __future__ import annotations

from ._parser import (
    AT_BEGINNING,
    AT_BEGINNING_STRING,
    AT_BOUNDARY,
    AT_END,
    AT_END_STRING,
    AT_NON_BOUNDARY,
    is_word,
)

# opcodes
CHAR = 0  # (CHAR, ch)
TEST = 1  # (TEST, predicate)
AT = 2  # (AT, kind)
MARK = 3  # (MARK, index)
SPLIT = 4  # (SPLIT, alternative_pc): try pc+1 first, then alternative_pc
JMP = 5  # (JMP, target)
REP1 = 6  # (REP1, predicate, min, max, greedy)
REPEAT_INIT = 7  # (REPEAT_INIT, reg, until_pc)
UNTIL = 8  # (UNTIL, reg, min, max, greedy, body_pc)
SUCCESS = 9  # (SUCCESS,)

# backtrack stack entry kinds
BT_CHOICE = 0  # (BT_CHOICE, pc, pos)
BT_MARK = 1  # (BT_MARK, index, old)
BT_COUNT = 2  # (BT_COUNT, reg, old)
BT_LAST = 3  # (BT_LAST, reg, old)
BT_REP1_GREEDY = 4  # (kind, next_pc, min_end, candidate_end)
BT_REP1_LAZY = 5  # (kind, next_pc, predicate, max, pos, count)
BT_LAZY_ITER = 6  # (kind, reg, count, pos, body_pc)


class Program:
    __slots__ = ("code", "ngroups", "nregs")

    def __init__(self, code: list[tuple], ngroups: int, nregs: int):
        self.code = code
        self.ngroups = ngroups
        self.nregs = nregs


def _char_predicate(node):
    """Return a predicate if ``node`` always matches exactly one character, else None."""
    kind = node[0]
    if kind == "char":
        return node[1].__eq__
    if kind == "set":
        return node[1]
    if kind == "group" and node[1] is None:
        return _char_predicate(node[2])
    return None


class _Compiler:
    def __init__(self):
        self.code: list = []
        self.nregs = 0

    def emit(self, *instr) -> int:
        self.code.append(instr)
        return len(self.code) - 1

    def patch(self, at: int, *instr) -> None:
        self.code[at] = instr

    def compile(self, node) -> None:
        kind = node[0]
        if kind == "char":
            self.emit(CHAR, node[1])
        elif kind == "set":
            self.emit(TEST, node[1])
        elif kind == "at":
            self.emit(AT, node[1])
        elif kind == "cat":
            for item in node[1]:
                self.compile(item)
        elif kind == "group":
            index = node[1]
            if index is None:
                self.compile(node[2])
            else:
                self.emit(MARK, 2 * (index - 1))
                self.compile(node[2])
                self.emit(MARK, 2 * (index - 1) + 1)
        elif kind == "alt":
            jumps = []
            branches = node[1]
            for i, branch in enumerate(branches):
                if i < len(branches) - 1:
                    split = self.emit(None)
                    self.compile(branch)
                    jumps.append(self.emit(None))
                    self.patch(split, SPLIT, len(self.code))
                else:
                    self.compile(branch)
            end = len(self.code)
            for j in jumps:
                self.patch(j, JMP, end)
        elif kind == "repeat":
            _, body, min_, max_, greedy = node
            pred = _char_predicate(body)
            if pred is not None:
                self.emit(REP1, pred, min_, max_, greedy)
                return
            reg = self.nregs
            self.nregs += 1
            init = self.emit(None)
            body_pc = len(self.code)
            self.compile(body)
            until_pc = self.emit(UNTIL, reg, min_, max_, greedy, body_pc)
            self.patch(init, REPEAT_INIT, reg, until_pc)
        else:  # pragma: no cover - parser never produces other nodes
            raise AssertionError(f"unknown node {kind!r}")


def compile_tree(tree, ngroups: int) -> Program:
    compiler = _Compiler()
    compiler.compile(tree)
    compiler.emit(SUCCESS)
    return Program(compiler.code, ngroups, compiler.nregs)


def _at(kind: str, s: str, pos: int, n: int) -> bool:
    if kind == AT_BEGINNING or kind == AT_BEGINNING_STRING:
        return pos == 0
    if kind == AT_END:
        return pos == n or (pos == n - 1 and s[pos] == "\n")
    if kind == AT_END_STRING:
        return pos == n
    # word boundaries: like _sre, they never match in an empty string
    if n == 0:
        return False
    before = pos > 0 and is_word(s[pos - 1])
    after = pos < n and is_word(s[pos])
    if kind == AT_BOUNDARY:
        return before != after
    if kind == AT_NON_BOUNDARY:
        return before == after
    raise AssertionError(kind)  # pragma: no cover


def run(prog: Program, s: str, start: int, match_all: bool, must_advance: bool):
    """Try to match ``prog`` at ``start``.

    Returns ``(end, marks)`` on success or ``None``. ``match_all`` requires the match to
    end at the end of ``s``; ``must_advance`` rejects an empty match at ``start``.
    """
    code = prog.code
    n = len(s)
    marks = [-1] * (2 * prog.ngroups)
    counts = [0] * prog.nregs
    lasts = [-1] * prog.nregs
    stack: list[tuple] = []
    push = stack.append
    pop = stack.pop
    pc = 0
    pos = start

    while True:
        instr = code[pc]
        op = instr[0]
        ok = True

        if op == CHAR:
            if pos < n and s[pos] == instr[1]:
                pos += 1
                pc += 1
            else:
                ok = False
        elif op == TEST:
            if pos < n and instr[1](s[pos]):
                pos += 1
                pc += 1
            else:
                ok = False
        elif op == MARK:
            index = instr[1]
            push((BT_MARK, index, marks[index]))
            marks[index] = pos
            pc += 1
        elif op == SPLIT:
            push((BT_CHOICE, instr[1], pos))
            pc += 1
        elif op == JMP:
            pc = instr[1]
        elif op == AT:
            if _at(instr[1], s, pos, n):
                pc += 1
            else:
                ok = False
        elif op == REP1:
            _, pred, min_, max_, greedy = instr
            limit = n if max_ is None else min(n, pos + max_)
            if greedy:
                end = pos
                while end < limit and pred(s[end]):
                    end += 1
                if end - pos < min_:
                    ok = False
                else:
                    if end - pos > min_:
                        push((BT_REP1_GREEDY, pc + 1, pos + min_, end - 1))
                    pos = end
                    pc += 1
            else:
                end = pos + min_
                if end > n:
                    ok = False
                else:
                    for i in range(pos, end):
                        if not pred(s[i]):
                            ok = False
                            break
                    if ok:
                        if max_ is None or min_ < max_:
                            push((BT_REP1_LAZY, pc + 1, pred, max_, end, min_))
                        pos = end
                        pc += 1
        elif op == REPEAT_INIT:
            reg = instr[1]
            push((BT_COUNT, reg, counts[reg]))
            push((BT_LAST, reg, lasts[reg]))
            counts[reg] = -1
            lasts[reg] = -1
            pc = instr[2]
        elif op == UNTIL:
            _, reg, min_, max_, greedy, body_pc = instr
            count = counts[reg] + 1
            if count < min_:
                push((BT_COUNT, reg, counts[reg]))
                counts[reg] = count
                pc = body_pc
            elif greedy:
                if (max_ is None or count < max_) and pos != lasts[reg]:
                    push((BT_CHOICE, pc + 1, pos))
                    push((BT_COUNT, reg, counts[reg]))
                    push((BT_LAST, reg, lasts[reg]))
                    counts[reg] = count
                    lasts[reg] = pos
                    pc = body_pc
                else:
                    pc += 1
            else:
                if (max_ is None or count < max_) and pos != lasts[reg]:
                    push((BT_LAZY_ITER, reg, count, pos, body_pc))
                pc += 1
        elif op == SUCCESS:
            if (match_all and pos != n) or (must_advance and pos == start):
                ok = False
            else:
                return pos, marks
        else:  # pragma: no cover
            raise AssertionError(f"bad opcode {op}")

        if ok:
            continue

        # backtrack: unwind the trail until a choice point resumes
        while True:
            if not stack:
                return None
            entry = pop()
            kind = entry[0]
            if kind == BT_MARK:
                marks[entry[1]] = entry[2]
            elif kind == BT_COUNT:
                counts[entry[1]] = entry[2]
            elif kind == BT_LAST:
                lasts[entry[1]] = entry[2]
            elif kind == BT_CHOICE:
                pc = entry[1]
                pos = entry[2]
                break
            elif kind == BT_REP1_GREEDY:
                _, next_pc, min_end, cand = entry
                if cand > min_end:
                    push((BT_REP1_GREEDY, next_pc, min_end, cand - 1))
                pos = cand
                pc = next_pc
                break
            elif kind == BT_REP1_LAZY:
                _, next_pc, pred, max_, p, count = entry
                if p < n and pred(s[p]):
                    p += 1
                    count += 1
                    if max_ is None or count < max_:
                        push((BT_REP1_LAZY, next_pc, pred, max_, p, count))
                    pos = p
                    pc = next_pc
                    break
            elif kind == BT_LAZY_ITER:
                _, reg, count, p, body_pc = entry
                push((BT_COUNT, reg, counts[reg]))
                push((BT_LAST, reg, lasts[reg]))
                counts[reg] = count
                lasts[reg] = p
                pos = p
                pc = body_pc
                break
