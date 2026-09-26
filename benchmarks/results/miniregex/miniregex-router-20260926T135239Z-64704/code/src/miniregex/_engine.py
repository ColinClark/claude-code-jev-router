"""Compiler from AST to a small instruction list, and a backtracking VM.

The VM mirrors the semantics of CPython's ``sre`` engine so that match spans and
group captures agree with ``re``:

* Alternatives and repetitions are tried in the same order as ``sre``.
* General repetitions keep a per-loop iteration counter and the position at which
  the last iteration started (``sre``'s ``last_ptr``); an iteration that would
  start where the previous one did is not attempted (zero-width protection).
* Captures are never reset between iterations; they are only restored on
  backtracking, so groups keep the value from the last successful iteration.

Backtracking uses an explicit stack plus an undo trail for registers (group
marks and loop state), so matching long texts does not hit Python's recursion
limit.
"""

from __future__ import annotations

# Opcodes
LIT = 0  # (LIT, ch)
CHAR = 1  # (CHAR, pred)
ANY = 2  # (ANY,)
BOL = 3  # (BOL,)
EOL = 4  # (EOL,)
SPLIT = 5  # (SPLIT, first, second)
JMP = 6  # (JMP, target)
SAVE = 7  # (SAVE, slot)
REPEAT_ONE = 8  # (REPEAT_ONE, pred, min, max, greedy) for single-character items
REPEAT = 9  # (REPEAT, loop, until_pc)
UNTIL = 10  # (UNTIL, loop, body_pc, min, max, greedy)
MATCH = 11  # (MATCH,)

# Backtrack entry kinds
_BT_PC = 0  # (kind, pc, pos, trail_len)
_BT_ONE_GREEDY = 1  # (kind, pc, start, trail_len, count, min)
_BT_ONE_LAZY = 2  # (kind, pc, start, trail_len, count, limit, pred)
_BT_MIN_UNTIL = 3  # (kind, until_pc, pos, trail_len, count)


def _any_pred(ch: str) -> bool:
    return ch != "\n"


class Program:
    __slots__ = ("code", "ngroups", "nregs", "loop_base")

    def __init__(self, code, ngroups: int, nloops: int):
        self.code = code
        self.ngroups = ngroups
        # Registers: slots 2*i and 2*i+1 hold the marks of group i (1..ngroups);
        # then two registers (count, last_pos) per general repetition.
        self.loop_base = 2 * (ngroups + 1)
        self.nregs = self.loop_base + 2 * nloops


class _Compiler:
    def __init__(self):
        self.code: list[list] = []
        self.nloops = 0

    def emit(self, *ins) -> int:
        self.code.append(list(ins))
        return len(self.code) - 1

    def compile(self, node) -> None:
        kind = node[0]
        code = self.code
        if kind == "lit":
            self.emit(LIT, node[1])
        elif kind == "any":
            self.emit(ANY)
        elif kind == "set":
            self.emit(CHAR, node[1])
        elif kind == "bol":
            self.emit(BOL)
        elif kind == "eol":
            self.emit(EOL)
        elif kind == "cat":
            for sub in node[1]:
                self.compile(sub)
        elif kind == "alt":
            branches = node[1]
            jumps = []
            for branch in branches[:-1]:
                split = self.emit(SPLIT, None, None)
                code[split][1] = len(code)
                self.compile(branch)
                jumps.append(self.emit(JMP, None))
                code[split][2] = len(code)
            self.compile(branches[-1])
            for j in jumps:
                code[j][1] = len(code)
        elif kind == "group":
            index = node[1]
            self.emit(SAVE, 2 * index)
            self.compile(node[2])
            self.emit(SAVE, 2 * index + 1)
        elif kind == "rep":
            _, sub, mn, mx, greedy = node
            pred = _single_char_pred(sub)
            if pred is not None:
                self.emit(REPEAT_ONE, pred, mn, mx, greedy)
            else:
                loop = self.nloops
                self.nloops += 1
                rep = self.emit(REPEAT, loop, None)
                body = len(code)
                self.compile(sub)
                until = self.emit(UNTIL, loop, body, mn, mx, greedy)
                code[rep][2] = until
        else:  # pragma: no cover - parser never produces other nodes
            raise AssertionError(f"unknown node {kind!r}")


def _single_char_pred(node):
    kind = node[0]
    if kind == "lit":
        return node[1].__eq__
    if kind == "any":
        return _any_pred
    if kind == "set":
        return node[1]
    return None


def compile_ast(ast, ngroups: int) -> Program:
    c = _Compiler()
    c.compile(ast)
    c.emit(MATCH)
    code = [tuple(ins) for ins in c.code]
    return Program(code, ngroups, c.nloops)


def execute(prog: Program, text: str, start: int, fullmatch: bool, must_advance: bool):
    """Try to match *prog* at exactly *start*.

    Returns ``(registers, end)`` on success, else ``None``.  With *fullmatch* the
    match must end at the end of *text*; with *must_advance* an empty match at
    *start* is rejected (used by ``findall`` after an empty match).
    """
    code = prog.code
    loop_base = prog.loop_base
    n = len(text)
    regs: list = [None] * prog.nregs
    trail: list = []
    stack: list = []
    pc = 0
    pos = start

    while True:
        ins = code[pc]
        op = ins[0]
        if op == LIT:
            if pos < n and text[pos] == ins[1]:
                pos += 1
                pc += 1
                continue
        elif op == CHAR:
            if pos < n and ins[1](text[pos]):
                pos += 1
                pc += 1
                continue
        elif op == ANY:
            if pos < n and text[pos] != "\n":
                pos += 1
                pc += 1
                continue
        elif op == SPLIT:
            stack.append((_BT_PC, ins[2], pos, len(trail)))
            pc = ins[1]
            continue
        elif op == JMP:
            pc = ins[1]
            continue
        elif op == SAVE:
            slot = ins[1]
            trail.append((slot, regs[slot]))
            regs[slot] = pos
            pc += 1
            continue
        elif op == REPEAT_ONE:
            _, pred, mn, mx, greedy = ins
            limit = n - pos if mx is None else min(mx, n - pos)
            count = 0
            if greedy:
                while count < limit and pred(text[pos + count]):
                    count += 1
                if count >= mn:
                    if count > mn:
                        stack.append((_BT_ONE_GREEDY, pc + 1, pos, len(trail), count, mn))
                    pos += count
                    pc += 1
                    continue
            else:
                while count < mn and count < limit and pred(text[pos + count]):
                    count += 1
                if count >= mn:
                    if count < limit:
                        stack.append((_BT_ONE_LAZY, pc + 1, pos, len(trail), count, limit, pred))
                    pos += count
                    pc += 1
                    continue
        elif op == REPEAT:
            ci = loop_base + 2 * ins[1]
            trail.append((ci, regs[ci]))
            trail.append((ci + 1, regs[ci + 1]))
            regs[ci] = -1
            regs[ci + 1] = None
            pc = ins[2]
            continue
        elif op == UNTIL:
            _, loop, body, mn, mx, greedy = ins
            ci = loop_base + 2 * loop
            count = regs[ci] + 1
            if count < mn:
                trail.append((ci, regs[ci]))
                regs[ci] = count
                pc = body
                continue
            if greedy:
                if (mx is None or count < mx) and pos != regs[ci + 1]:
                    # Try another iteration; on failure fall back to the tail.
                    stack.append((_BT_PC, pc + 1, pos, len(trail)))
                    trail.append((ci, regs[ci]))
                    trail.append((ci + 1, regs[ci + 1]))
                    regs[ci] = count
                    regs[ci + 1] = pos
                    pc = body
                    continue
                pc += 1
                continue
            # Lazy: try the tail first; on failure try another iteration.
            stack.append((_BT_MIN_UNTIL, pc, pos, len(trail), count))
            pc += 1
            continue
        elif op == BOL:
            if pos == 0:
                pc += 1
                continue
        elif op == EOL:
            if pos == n or (pos == n - 1 and text[pos] == "\n"):
                pc += 1
                continue
        elif op == MATCH:
            if (not fullmatch or pos == n) and not (must_advance and pos == start):
                return regs, pos

        # Failure: backtrack.
        while True:
            if not stack:
                return None
            entry = stack.pop()
            tl = entry[3]
            while len(trail) > tl:
                slot, old = trail.pop()
                regs[slot] = old
            kind = entry[0]
            if kind == _BT_PC:
                pc = entry[1]
                pos = entry[2]
                break
            if kind == _BT_ONE_GREEDY:
                _, pc, begin, _, count, mn = entry
                count -= 1
                if count > mn:
                    stack.append((_BT_ONE_GREEDY, pc, begin, tl, count, mn))
                pos = begin + count
                break
            if kind == _BT_ONE_LAZY:
                _, next_pc, begin, _, count, limit, pred = entry
                if pred(text[begin + count]):
                    count += 1
                    if count < limit:
                        stack.append((_BT_ONE_LAZY, next_pc, begin, tl, count, limit, pred))
                    pc = next_pc
                    pos = begin + count
                    break
                continue
            # _BT_MIN_UNTIL: the tail failed; try one more iteration.
            _, until_pc, upos, _, count = entry
            _, loop, body, _, mx, _ = code[until_pc]
            ci = loop_base + 2 * loop
            if (mx is not None and count >= mx) or upos == regs[ci + 1]:
                continue
            trail.append((ci, regs[ci]))
            trail.append((ci + 1, regs[ci + 1]))
            regs[ci] = count
            regs[ci + 1] = upos
            pc = body
            pos = upos
            break
