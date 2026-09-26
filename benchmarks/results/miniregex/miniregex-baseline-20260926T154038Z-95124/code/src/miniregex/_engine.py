"""Compiler from AST to a small instruction set, and a backtracking VM that runs it.

The VM mirrors the matching order of CPython's ``_sre`` so that results (spans and
group captures) are identical to ``re``:

* alternatives are tried left to right;
* greedy repeats try one more iteration before the tail, lazy repeats the reverse;
* a repeat stops iterating once an iteration matched the empty string
  (``_sre``'s "zero-width match protection"), but that empty iteration still counts;
* captures made in an iteration survive later iterations that do not touch the group.

Backtracking uses an explicit stack of choice points and an undo trail for registers
(capture slots and repeat counters), so there is no Python recursion while matching.
"""

from __future__ import annotations

# Opcodes
CHAR = 0  # (CHAR, c)
ANY = 1  # (ANY,)
SET = 2  # (SET, charset)
BOL = 3  # (BOL,)
EOL = 4  # (EOL,)
SPLIT = 5  # (SPLIT, alternative_pc): try next instruction first, then alternative_pc
JMP = 6  # (JMP, target)
SAVE = 7  # (SAVE, slot)
RINIT = 8  # (RINIT, count_reg): reset a general repeat
RUNTIL = 9  # (RUNTIL, count_reg, min, max, body_pc, exit_pc, greedy)
RMORE = 10  # (RMORE, count_reg, max, body_pc): lazy repeat's "one more iteration"
ONE = 11  # (ONE, matcher, min, max, greedy): repeat of a single-character item
MATCH = 12  # (MATCH,)

# Choice-point kinds
_RESUME = 0
_ONE_GREEDY = 1
_ONE_LAZY = 2


def _single(node):
    """Return a single-character matcher tuple for ``node``, or None."""
    kind = node[0]
    if kind == "char":
        return (CHAR, node[1])
    if kind == "any":
        return (ANY,)
    if kind == "set":
        return (SET, node[1])
    if kind == "group" and node[1] is None:
        return _single(node[2])
    return None


class Program:
    __slots__ = ("code", "nregs", "ngroups")

    def __init__(self, code, nregs, ngroups):
        self.code = code
        self.nregs = nregs
        self.ngroups = ngroups


def compile_ast(ast, ngroups: int) -> Program:
    code: list = []
    # Registers: 2 capture slots per group (group 0 included), then 2 per general repeat
    # (iteration count, position at which the current iteration started).
    nregs = [2 * (ngroups + 1)]

    def emit(*ins) -> int:
        code.append(list(ins))
        return len(code) - 1

    def gen(node) -> None:
        kind = node[0]
        if kind in ("char", "any", "set"):
            emit(*_single(node))
        elif kind == "bol":
            emit(BOL)
        elif kind == "eol":
            emit(EOL)
        elif kind == "cat":
            for item in node[1]:
                gen(item)
        elif kind == "alt":
            jumps = []
            branches = node[1]
            for i, branch in enumerate(branches):
                if i < len(branches) - 1:
                    split = emit(SPLIT, None)
                    gen(branch)
                    jumps.append(emit(JMP, None))
                    code[split][1] = len(code)
                else:
                    gen(branch)
            for j in jumps:
                code[j][1] = len(code)
        elif kind == "group":
            index, body = node[1], node[2]
            if index is None:
                gen(body)
            else:
                emit(SAVE, 2 * index)
                gen(body)
                emit(SAVE, 2 * index + 1)
        elif kind == "rep":
            _, body, lo, hi, greedy = node
            single = _single(body)
            if single is not None:
                emit(ONE, single, lo, hi, greedy)
                return
            reg = nregs[0]
            nregs[0] += 2
            emit(RINIT, reg)
            until = emit(RUNTIL, reg, lo, hi, None, None, greedy)
            more = None
            if not greedy:
                more = emit(RMORE, reg, hi, None)
            body_pc = len(code)
            gen(body)
            emit(JMP, until)
            exit_pc = len(code)
            code[until][4] = body_pc
            code[until][5] = exit_pc
            if more is not None:
                code[more][3] = body_pc
        else:  # pragma: no cover - parser never produces other nodes
            raise AssertionError(kind)

    emit(SAVE, 0)
    gen(ast)
    emit(SAVE, 1)
    emit(MATCH)
    return Program([tuple(ins) for ins in code], nregs[0], ngroups)


def _match_one(m, ch: str) -> bool:
    op = m[0]
    if op == CHAR:
        return ch == m[1]
    if op == ANY:
        return ch != "\n"
    return m[1].contains(ch)


def run(prog: Program, text: str, start: int, fullmatch: bool, must_advance: bool):
    """Try to match at ``start``. Returns the capture registers or None.

    ``fullmatch`` requires the match to end at the end of ``text``; ``must_advance``
    rejects an empty match at ``start``. Both are checked at MATCH, so the engine
    backtracks to find an alternative that satisfies them, as ``_sre`` does.
    """
    code = prog.code
    n = len(text)
    regs = [-1] * prog.nregs
    trail: list = []
    stack: list = []
    pc = 0
    pos = start

    while True:
        ins = code[pc]
        op = ins[0]
        ok = True
        if op == CHAR:
            if pos < n and text[pos] == ins[1]:
                pos += 1
                pc += 1
            else:
                ok = False
        elif op == SET:
            if pos < n and ins[1].contains(text[pos]):
                pos += 1
                pc += 1
            else:
                ok = False
        elif op == ANY:
            if pos < n and text[pos] != "\n":
                pos += 1
                pc += 1
            else:
                ok = False
        elif op == SAVE:
            slot = ins[1]
            trail.append((slot, regs[slot]))
            regs[slot] = pos
            pc += 1
        elif op == SPLIT:
            stack.append((_RESUME, ins[1], pos, len(trail), 0, 0))
            pc += 1
        elif op == JMP:
            pc = ins[1]
        elif op == ONE:
            m, lo, hi, greedy = ins[1], ins[2], ins[3], ins[4]
            limit = n - pos if hi is None else min(hi, n - pos)
            if greedy:
                count = 0
                while count < limit and _match_one(m, text[pos + count]):
                    count += 1
                if count < lo:
                    ok = False
                else:
                    if count > lo:
                        stack.append((_ONE_GREEDY, pc + 1, pos, len(trail), count - 1, lo))
                    pos += count
                    pc += 1
            else:
                if lo > limit:
                    ok = False
                else:
                    count = 0
                    while count < lo and _match_one(m, text[pos + count]):
                        count += 1
                    if count < lo:
                        ok = False
                    else:
                        stack.append((_ONE_LAZY, pc, pos, len(trail), lo, 0))
                        pos += lo
                        pc += 1
        elif op == BOL:
            if pos == 0:
                pc += 1
            else:
                ok = False
        elif op == EOL:
            if pos == n or (pos == n - 1 and text[pos] == "\n"):
                pc += 1
            else:
                ok = False
        elif op == RINIT:
            reg = ins[1]
            trail.append((reg, regs[reg]))
            trail.append((reg + 1, regs[reg + 1]))
            regs[reg] = 0
            regs[reg + 1] = -1
            pc += 1
        elif op == RUNTIL:
            reg, lo, hi, body_pc, exit_pc, greedy = ins[1:]
            count = regs[reg]
            if count < lo:
                trail.append((reg, count))
                regs[reg] = count + 1
                pc = body_pc
            elif greedy:
                if (hi is None or count < hi) and pos != regs[reg + 1]:
                    stack.append((_RESUME, exit_pc, pos, len(trail), 0, 0))
                    trail.append((reg, count))
                    trail.append((reg + 1, regs[reg + 1]))
                    regs[reg] = count + 1
                    regs[reg + 1] = pos
                    pc = body_pc
                else:
                    pc = exit_pc
            else:
                stack.append((_RESUME, pc + 1, pos, len(trail), 0, 0))
                pc = exit_pc
        elif op == RMORE:
            reg, hi, body_pc = ins[1:]
            count = regs[reg]
            if (hi is None or count < hi) and pos != regs[reg + 1]:
                trail.append((reg, count))
                trail.append((reg + 1, regs[reg + 1]))
                regs[reg] = count + 1
                regs[reg + 1] = pos
                pc = body_pc
            else:
                ok = False
        elif op == MATCH:
            if (fullmatch and pos != n) or (must_advance and pos == start):
                ok = False
            else:
                return regs
        else:  # pragma: no cover
            raise AssertionError(op)

        if ok:
            continue

        # Backtrack to the most recent choice point that can still make progress.
        while True:
            if not stack:
                return None
            kind, pc, base, mark, a, b = stack.pop()
            while len(trail) > mark:
                slot, old = trail.pop()
                regs[slot] = old
            if kind == _RESUME:
                pos = base
                break
            if kind == _ONE_GREEDY:
                # a = count to try now, b = minimum
                if a > b:
                    stack.append((_ONE_GREEDY, pc, base, mark, a - 1, b))
                pos = base + a
                break
            # _ONE_LAZY: pc is the ONE instruction, a = count matched so far
            ins = code[pc]
            hi = ins[3]
            end = base + a
            if (hi is None or a < hi) and end < n and _match_one(ins[1], text[end]):
                stack.append((_ONE_LAZY, pc, base, mark, a + 1, 0))
                pos = end + 1
                pc += 1
                break
