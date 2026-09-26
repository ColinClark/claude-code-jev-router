"""Compile the AST into instructions for the backtracking VM (see ``_vm``).

Repetitions of a single-character matcher compile to one ``STAR`` instruction
(like sre's REPEAT_ONE / MIN_REPEAT_ONE).  All other repetitions compile to
``REPEAT_INIT`` + body + ``UNTIL_MAX`` / ``UNTIL_MIN``, which mirror sre's
REPEAT / MAX_UNTIL / MIN_UNTIL opcodes including the zero-width-iteration
protection (a new optional iteration is not attempted when the position equals
the start position of the previous optional iteration).
"""

from __future__ import annotations

from . import _parser as P

# Opcodes
CHAR = 0  # (CHAR, ch)
ANY = 1  # (ANY,)
SET = 2  # (SET, test)
AT = 3  # (AT, kind)
SAVE = 4  # (SAVE, slot)
SPLIT = 5  # (SPLIT, alt_pc)      try pc+1 first, then alt_pc
JMP = 6  # (JMP, target)
REPEAT_INIT = 7  # (REPEAT_INIT, reg, until_pc)
UNTIL_MAX = 8  # (UNTIL_MAX, reg, lo, hi, body_pc)      exit is pc+1
UNTIL_MIN = 9  # (UNTIL_MIN, reg, lo, hi, body_pc)
STAR = 10  # (STAR, test, lo, hi, greedy)             test is None for '.'
MATCH = 11  # (MATCH,)


def _any_test(ch: str) -> bool:
    return ch != "\n"


class Program:
    __slots__ = ("code", "groups", "nregs", "repeat_base")

    def __init__(self, code, groups, nregs, repeat_base):
        self.code = code
        self.groups = groups
        self.nregs = nregs
        self.repeat_base = repeat_base


class _Compiler:
    def __init__(self, groups: int):
        self.code: list = []
        self.repeat_base = 2 * (groups + 1)
        self.nrepeats = 0

    def emit(self, instr) -> int:
        self.code.append(instr)
        return len(self.code) - 1

    def single_char_test(self, node):
        """Return a per-char test if ``node`` always matches exactly one char."""
        kind = node[0]
        if kind == P.CHAR:
            ch = node[1]
            return lambda c: c == ch
        if kind == P.ANY:
            return _any_test
        if kind == P.SET:
            return node[1].make_test()
        if kind == P.GROUP and node[1] is None:
            return self.single_char_test(node[2])
        if kind == P.SEQ and len(node[1]) == 1:
            return self.single_char_test(node[1][0])
        return None

    def compile(self, node) -> None:
        kind = node[0]
        if kind == P.CHAR:
            self.emit((CHAR, node[1]))
        elif kind == P.ANY:
            self.emit((ANY,))
        elif kind == P.SET:
            self.emit((SET, node[1].make_test()))
        elif kind == P.AT:
            self.emit((AT, node[1]))
        elif kind == P.SEQ:
            for item in node[1]:
                self.compile(item)
        elif kind == P.GROUP:
            index = node[1]
            if index is None:
                self.compile(node[2])
            else:
                self.emit((SAVE, 2 * index))
                self.compile(node[2])
                self.emit((SAVE, 2 * index + 1))
        elif kind == P.ALT:
            jumps = []
            alts = node[1]
            for i, alt in enumerate(alts):
                if i < len(alts) - 1:
                    split = self.emit(None)
                    self.compile(alt)
                    jumps.append(self.emit(None))
                    self.code[split] = (SPLIT, len(self.code))
                else:
                    self.compile(alt)
            end = len(self.code)
            for j in jumps:
                self.code[j] = (JMP, end)
        elif kind == P.REPEAT:
            _, lo, hi, greedy, body = node
            test = self.single_char_test(body)
            if test is not None:
                self.emit((STAR, test, lo, hi, greedy))
                return
            reg = self.repeat_base + 2 * self.nrepeats
            self.nrepeats += 1
            init = self.emit(None)
            body_pc = len(self.code)
            self.compile(body)
            until = self.emit((UNTIL_MAX if greedy else UNTIL_MIN, reg, lo, hi, body_pc))
            self.code[init] = (REPEAT_INIT, reg, until)
        else:  # pragma: no cover
            raise AssertionError(kind)


def compile_ast(ast, groups: int) -> Program:
    c = _Compiler(groups)
    c.compile(ast)
    c.emit((MATCH,))
    return Program(tuple(c.code), groups, c.repeat_base + 2 * c.nrepeats, c.repeat_base)
