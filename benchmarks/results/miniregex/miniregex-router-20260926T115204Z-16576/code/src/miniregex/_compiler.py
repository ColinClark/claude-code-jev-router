"""Compile the parser AST into a flat instruction list for the backtracking VM.

Instruction tuples (first element is the opcode):

    (OP_CHAR, ch)
    (OP_ANY,)
    (OP_SET, predicate)
    (OP_BOL,)
    (OP_EOL,)
    (OP_SPLIT, first_pc, second_pc)     try first_pc, fall back to second_pc
    (OP_JMP, pc)
    (OP_SAVE, slot)                     record current position in capture slot
    (OP_REPEAT, until_pc)               open a repeat context, jump to its UNTIL
    (OP_UNTIL, min, max_or_None, lazy, body_pc)
    (OP_MATCH,)

The REPEAT/UNTIL pair reproduces sre's REPEAT + MAX_UNTIL / MIN_UNTIL control
flow, including its "stop iterating after an empty iteration" rule.
"""

from __future__ import annotations

from collections.abc import Callable

(
    OP_CHAR,
    OP_ANY,
    OP_SET,
    OP_BOL,
    OP_EOL,
    OP_SPLIT,
    OP_JMP,
    OP_SAVE,
    OP_REPEAT,
    OP_UNTIL,
    OP_MATCH,
) = range(11)


def _is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_word(ch: str) -> bool:
    return ch == "_" or "0" <= ch <= "9" or "a" <= ch <= "z" or "A" <= ch <= "Z"


def _is_space(ch: str) -> bool:
    return ch in " \t\n\r\f\v"


_CLASS_TESTS: dict[str, Callable[[str], bool]] = {"d": _is_digit, "w": _is_word, "s": _is_space}


def _class_test(name: str) -> Callable[[str], bool]:
    base = _CLASS_TESTS[name.lower()]
    if name.isupper():

        def negated(ch: str) -> bool:
            return not base(ch)

        return negated
    return base


def make_set_predicate(
    negate: bool, ranges: tuple[tuple[str, str], ...], classes: tuple[str, ...]
) -> Callable[[str], bool]:
    tests = tuple(_class_test(name) for name in classes)
    single = frozenset(lo for lo, hi in ranges if lo == hi)
    spans = tuple((lo, hi) for lo, hi in ranges if lo != hi)

    def predicate(ch: str) -> bool:
        if ch in single:
            return not negate
        for lo, hi in spans:
            if lo <= ch <= hi:
                return not negate
        for test in tests:
            if test(ch):
                return not negate
        return negate

    return predicate


def compile_ast(node: tuple) -> list[tuple]:
    prog: list[tuple] = []

    def emit(n: tuple) -> None:
        kind = n[0]
        if kind == "lit":
            prog.append((OP_CHAR, n[1]))
        elif kind == "any":
            prog.append((OP_ANY,))
        elif kind == "set":
            prog.append((OP_SET, make_set_predicate(n[1], n[2], n[3])))
        elif kind == "bol":
            prog.append((OP_BOL,))
        elif kind == "eol":
            prog.append((OP_EOL,))
        elif kind == "cat":
            for child in n[1]:
                emit(child)
        elif kind == "alt":
            alternatives = n[1]
            jumps: list[int] = []
            for alt in alternatives[:-1]:
                split_at = len(prog)
                prog.append(None)  # type: ignore[arg-type]
                emit(alt)
                jumps.append(len(prog))
                prog.append(None)  # type: ignore[arg-type]
                prog[split_at] = (OP_SPLIT, split_at + 1, len(prog))
            emit(alternatives[-1])
            end = len(prog)
            for j in jumps:
                prog[j] = (OP_JMP, end)
        elif kind == "group":
            index = n[1]
            if index is None:
                emit(n[2])
            else:
                slot = 2 * (index - 1)
                prog.append((OP_SAVE, slot))
                emit(n[2])
                prog.append((OP_SAVE, slot + 1))
        elif kind == "repeat":
            _, mn, mx, lazy, child = n
            repeat_at = len(prog)
            prog.append(None)  # type: ignore[arg-type]
            body = len(prog)
            emit(child)
            until = len(prog)
            prog.append((OP_UNTIL, mn, mx, lazy, body))
            prog[repeat_at] = (OP_REPEAT, until)
        else:  # pragma: no cover - parser never produces other kinds
            raise AssertionError(f"unknown node kind {kind!r}")

    emit(node)
    prog.append((OP_MATCH,))
    return prog
