"""AST -> backtracking VM program.

Instructions are tuples whose first element is an opcode constant below.

  (CHAR, c)                         consume ``c``
  (ANY,)                            consume any char except ``\\n``
  (SET, charset)                    consume a char in ``charset``
  (BOL,) / (EOL,)                   anchors
  (SAVE, slot)                      record the current position in capture slot
  (SPLIT, preferred, alternative)   try ``preferred``, backtrack to ``alternative``
  (JMP, target)
  (REPEAT, until_pc)                push a repeat frame and jump to its UNTIL
  (UNTIL, min, max, greedy, body)   loop control for a general repeat
  (REPEAT_ONE, test, min, max, greedy)
                                    repeat of a single-character matcher
  (MATCH,)

The REPEAT/UNTIL pair reproduces CPython's ``MAX_UNTIL``/``MIN_UNTIL`` opcodes,
including their zero-width-iteration protection.
"""

from __future__ import annotations

from collections.abc import Callable

from .nodes import Alt, Any, Bol, Char, CharSet, Eol, Group, Node, Repeat, Seq

CHAR = 0
ANY = 1
SET = 2
BOL = 3
EOL = 4
SAVE = 5
SPLIT = 6
JMP = 7
REPEAT = 8
UNTIL = 9
REPEAT_ONE = 10
MATCH = 11

Instr = tuple


def _unwrap(node: Node) -> Node:
    while isinstance(node, Seq) and len(node.items) == 1:
        node = node.items[0]
    return node


def _single_char_test(node: Node) -> Callable[[str], bool] | None:
    node = _unwrap(node)
    if isinstance(node, Char):
        c = node.ch
        return lambda ch: ch == c
    if isinstance(node, Any):
        return lambda ch: ch != "\n"
    if isinstance(node, CharSet):
        return node.contains
    return None


class Compiler:
    def __init__(self) -> None:
        self.code: list[Instr] = []

    def emit(self, instr: Instr) -> int:
        self.code.append(instr)
        return len(self.code) - 1

    def compile(self, node: Node) -> list[Instr]:
        self.visit(node)
        self.emit((MATCH,))
        return self.code

    def visit(self, node: Node) -> None:
        code = self.code
        if isinstance(node, Char):
            self.emit((CHAR, node.ch))
        elif isinstance(node, Any):
            self.emit((ANY,))
        elif isinstance(node, CharSet):
            self.emit((SET, node))
        elif isinstance(node, Bol):
            self.emit((BOL,))
        elif isinstance(node, Eol):
            self.emit((EOL,))
        elif isinstance(node, Seq):
            for item in node.items:
                self.visit(item)
        elif isinstance(node, Group):
            self.emit((SAVE, 2 * node.index))
            self.visit(node.body)
            self.emit((SAVE, 2 * node.index + 1))
        elif isinstance(node, Alt):
            jumps: list[int] = []
            branches = node.branches
            for i, branch in enumerate(branches):
                if i < len(branches) - 1:
                    split = self.emit((SPLIT, None, None))
                    self.visit(branch)
                    jumps.append(self.emit((JMP, None)))
                    code[split] = (SPLIT, split + 1, len(code))
                else:
                    self.visit(branch)
            end = len(code)
            for j in jumps:
                code[j] = (JMP, end)
        elif isinstance(node, Repeat):
            test = _single_char_test(node.body)
            if test is not None:
                self.emit((REPEAT_ONE, test, node.min, node.max, node.greedy))
                return
            rep = self.emit((REPEAT, None))
            body = len(code)
            self.visit(node.body)
            until = self.emit((UNTIL, node.min, node.max, node.greedy, body))
            code[rep] = (REPEAT, until)
        else:  # pragma: no cover - defensive
            raise TypeError(f"unknown node {node!r}")


def compile_program(node: Node) -> list[Instr]:
    return Compiler().compile(node)
