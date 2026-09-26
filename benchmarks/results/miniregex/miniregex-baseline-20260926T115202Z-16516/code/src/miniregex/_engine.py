"""Compiler and backtracking matcher.

The instruction set and the matcher follow CPython's ``_sre`` engine closely:
the same repeat strategies (single-character ``REPEAT_ONE``/``MIN_REPEAT_ONE``
versus general ``REPEAT`` + ``MAX_UNTIL``/``MIN_UNTIL``), the same zero-width
iteration guard, and the same rules for saving and restoring capture marks on
backtracking. Reproducing those rules is what makes group values identical to
``re`` in corner cases such as groups inside repetitions.

Each call of :func:`_run` corresponds to one ``_sre`` match context. When the
C engine would recurse (``DO_JUMP``), ``_run`` yields ``(pc, ptr)`` and the
trampoline in :func:`_execute` runs the child context and sends back its
boolean result. This keeps backtracking depth off the Python call stack.
"""

from __future__ import annotations

from collections.abc import Callable, Generator

from ._parser import MAXREPEAT

# Opcodes
LITERAL = 0
ANY = 1
IN = 2
AT_BEGINNING = 3
AT_END = 4
MARK = 5
BRANCH = 6
JUMP = 7
REPEAT_ONE = 8
MIN_REPEAT_ONE = 9
REPEAT = 10
MAX_UNTIL = 11
MIN_UNTIL = 12
SUCCESS = 13
FAILURE = 14


def _is_simple(seq: list) -> bool:
    """True if ``seq`` always matches exactly one character and contains no groups."""
    if len(seq) != 1:
        return False
    node = seq[0]
    if node[0] == "group":
        return node[1] is None and _is_simple(node[2])
    return node[0] in ("lit", "any", "in")


def _single_char_predicate(seq: list) -> Callable[[str], bool]:
    node = seq[0]
    while node[0] == "group":
        node = node[2][0]
    if node[0] == "lit":
        ch = node[1]
        return lambda c: c == ch
    if node[0] == "any":
        return lambda c: c != "\n"
    charset = node[1]
    return lambda c: c in charset


def compile_tree(tree: list) -> list[tuple]:
    code: list[tuple] = []
    _emit(tree, code)
    code.append((SUCCESS,))
    return code


def _emit(seq: list, code: list) -> None:
    for node in seq:
        kind = node[0]
        if kind == "lit":
            code.append((LITERAL, node[1]))
        elif kind == "any":
            code.append((ANY,))
        elif kind == "in":
            code.append((IN, node[1]))
        elif kind == "at":
            code.append((AT_BEGINNING,) if node[1] == "beg" else (AT_END,))
        elif kind == "group":
            index = node[1]
            if index is not None:
                code.append((MARK, 2 * (index - 1)))
            _emit(node[2], code)
            if index is not None:
                code.append((MARK, 2 * (index - 1) + 1))
        elif kind == "branch":
            branch_pc = len(code)
            code.append(None)
            starts = []
            jumps = []
            for alternative in node[1]:
                starts.append(len(code))
                _emit(alternative, code)
                jumps.append(len(code))
                code.append(None)
            code.append((FAILURE,))
            end = len(code)
            for pc in jumps:
                code[pc] = (JUMP, end)
            code[branch_pc] = (BRANCH, tuple(starts))
        elif kind == "repeat":
            _, lo, hi, greedy, item = node
            if _is_simple(item):
                op = REPEAT_ONE if greedy else MIN_REPEAT_ONE
                code.append((op, lo, hi, _single_char_predicate(item)))
            else:
                repeat_pc = len(code)
                code.append(None)
                _emit(item, code)
                until_pc = len(code)
                code.append((MAX_UNTIL if greedy else MIN_UNTIL,))
                code[repeat_pc] = (REPEAT, lo, hi, until_pc)
        else:  # pragma: no cover - parser never produces anything else
            raise AssertionError(kind)


class _Repeat:
    __slots__ = ("count", "body", "min", "max", "prev", "last_ptr")

    def __init__(self, body: int, lo: int, hi: int, prev: _Repeat | None):
        self.count = -1
        self.body = body
        self.min = lo
        self.max = hi
        self.prev = prev
        self.last_ptr: int | None = None


class State:
    __slots__ = (
        "code",
        "text",
        "end",
        "marks",
        "lastmark",
        "repeat",
        "match_all",
        "must_advance",
        "start",
        "ptr",
    )

    def __init__(self, code: list[tuple], text: str, ngroups: int):
        self.code = code
        self.text = text
        self.end = len(text)
        self.marks: list[int | None] = [None] * (2 * ngroups)
        self.lastmark = -1
        self.repeat: _Repeat | None = None
        self.match_all = False
        self.must_advance = False
        self.start = 0
        self.ptr = 0

    def reset_marks(self) -> None:
        self.lastmark = -1
        self.repeat = None

    def spans(self) -> list[tuple[int, int]]:
        """Span of the whole match followed by each group's span ((-1, -1) if unset)."""
        result = [(self.start, self.ptr)]
        marks = self.marks
        for j in range(0, len(marks), 2):
            if j + 1 <= self.lastmark and marks[j] is not None and marks[j + 1] is not None:
                result.append((marks[j], marks[j + 1]))
            else:
                result.append((-1, -1))
        return result


def _count(text: str, ptr: int, end: int, pred: Callable[[str], bool], limit: int) -> int:
    stop = min(end, ptr + limit) if limit < MAXREPEAT else end
    i = ptr
    while i < stop and pred(text[i]):
        i += 1
    return i - ptr


_Context = Generator[tuple[int, int], bool, bool]


def _run(state: State, pc: int, ptr: int) -> _Context:
    code = state.code
    text = state.text
    end = state.end
    marks = state.marks
    while True:
        op = code[pc]
        kind = op[0]

        if kind == LITERAL:
            if ptr >= end or text[ptr] != op[1]:
                return False
            ptr += 1
            pc += 1

        elif kind == ANY:
            if ptr >= end or text[ptr] == "\n":
                return False
            ptr += 1
            pc += 1

        elif kind == IN:
            if ptr >= end or text[ptr] not in op[1]:
                return False
            ptr += 1
            pc += 1

        elif kind == AT_BEGINNING:
            if ptr != 0:
                return False
            pc += 1

        elif kind == AT_END:
            if not (ptr == end or (ptr + 1 == end and text[ptr] == "\n")):
                return False
            pc += 1

        elif kind == MARK:
            i = op[1]
            if i > state.lastmark:
                for j in range(state.lastmark + 1, i):
                    marks[j] = None
                state.lastmark = i
            marks[i] = ptr
            pc += 1

        elif kind == JUMP:
            pc = op[1]

        elif kind == SUCCESS:
            if (state.match_all and ptr != end) or (state.must_advance and ptr == state.start):
                return False
            state.ptr = ptr
            return True

        elif kind == FAILURE:
            return False

        elif kind == BRANCH:
            lastmark = state.lastmark
            saved = marks[: lastmark + 1] if state.repeat is not None else None
            for alternative in op[1]:
                if (yield (alternative, ptr)):
                    return True
                if saved is not None:
                    marks[: lastmark + 1] = saved
                state.lastmark = lastmark
            return False

        elif kind == REPEAT_ONE:
            _, lo, hi, pred = op
            if lo > end - ptr:
                return False
            count = _count(text, ptr, end, pred, hi)
            if count < lo:
                return False
            ptr += count
            tail = pc + 1
            lastmark = state.lastmark
            saved = marks[: lastmark + 1] if state.repeat is not None else None
            while count >= lo:
                if (yield (tail, ptr)):
                    return True
                if saved is not None:
                    marks[: lastmark + 1] = saved
                state.lastmark = lastmark
                ptr -= 1
                count -= 1
            return False

        elif kind == MIN_REPEAT_ONE:
            _, lo, hi, pred = op
            if lo > end - ptr:
                return False
            if lo:
                count = _count(text, ptr, end, pred, lo)
                if count < lo:
                    return False
                ptr += count
            else:
                count = 0
            tail = pc + 1
            lastmark = state.lastmark
            saved = marks[: lastmark + 1] if state.repeat is not None else None
            while hi == MAXREPEAT or count <= hi:
                if (yield (tail, ptr)):
                    return True
                if saved is not None:
                    marks[: lastmark + 1] = saved
                state.lastmark = lastmark
                if ptr >= end or not pred(text[ptr]):
                    break
                ptr += 1
                count += 1
            return False

        elif kind == REPEAT:
            _, lo, hi, until_pc = op
            rep = _Repeat(pc + 1, lo, hi, state.repeat)
            state.repeat = rep
            ok = yield (until_pc, ptr)
            state.repeat = rep.prev
            return ok

        elif kind == MAX_UNTIL:
            rep = state.repeat
            assert rep is not None
            count = rep.count + 1
            if count < rep.min:
                # Not enough iterations yet: the body must match again.
                rep.count = count
                if (yield (rep.body, ptr)):
                    return True
                rep.count = count - 1
                return False
            if (count < rep.max or rep.max == MAXREPEAT) and ptr != rep.last_ptr:
                # Try one more iteration (unless the last one matched the empty string).
                rep.count = count
                lastmark = state.lastmark
                saved = marks[: lastmark + 1]
                previous_last_ptr = rep.last_ptr
                rep.last_ptr = ptr
                ok = yield (rep.body, ptr)
                rep.last_ptr = previous_last_ptr
                if ok:
                    return True
                marks[: lastmark + 1] = saved
                state.lastmark = lastmark
                rep.count = count - 1
            # No more iterations: the rest of the pattern must match.
            state.repeat = rep.prev
            ok = yield (pc + 1, ptr)
            state.repeat = rep
            return ok

        elif kind == MIN_UNTIL:
            rep = state.repeat
            assert rep is not None
            count = rep.count + 1
            if count < rep.min:
                rep.count = count
                if (yield (rep.body, ptr)):
                    return True
                rep.count = count - 1
                return False
            # Try the rest of the pattern first.
            state.repeat = rep.prev
            lastmark = state.lastmark
            saved = marks[: lastmark + 1] if state.repeat is not None else None
            ok = yield (pc + 1, ptr)
            state.repeat = rep
            if ok:
                return True
            if saved is not None:
                marks[: lastmark + 1] = saved
            state.lastmark = lastmark
            if (count >= rep.max and rep.max != MAXREPEAT) or ptr == rep.last_ptr:
                return False
            rep.count = count
            previous_last_ptr = rep.last_ptr
            rep.last_ptr = ptr
            ok = yield (rep.body, ptr)
            rep.last_ptr = previous_last_ptr
            if ok:
                return True
            rep.count = count - 1
            return False

        else:  # pragma: no cover
            raise AssertionError(kind)


def _execute(state: State, ptr: int) -> bool:
    """Run the program from the start at ``ptr`` using an explicit context stack."""
    stack = [_run(state, 0, ptr)]
    value: bool | None = None
    while True:
        try:
            pc, child_ptr = stack[-1].send(value)
        except StopIteration as stop:
            stack.pop()
            value = stop.value
            if not stack:
                return value
            continue
        stack.append(_run(state, pc, child_ptr))
        value = None


def match_at(state: State, pos: int, match_all: bool) -> bool:
    state.reset_marks()
    state.match_all = match_all
    state.must_advance = False
    state.start = pos
    return _execute(state, pos)


def search(state: State, pos: int, must_advance: bool = False) -> bool:
    """Find the leftmost match starting at or after ``pos``.

    With ``must_advance``, an empty match at ``pos`` itself is rejected (used by
    ``findall`` after an empty match, as in ``re``).
    """
    end = state.end
    if pos > end:
        return False
    state.match_all = False
    state.must_advance = must_advance
    state.reset_marks()
    state.start = pos
    if _execute(state, pos):
        return True
    state.must_advance = False
    while pos < end:
        pos += 1
        state.reset_marks()
        state.start = pos
        if _execute(state, pos):
            return True
    return False
