"""Compiler and backtracking matcher.

The parsed tree is compiled into a flat list of instructions modelled on
CPython's ``_sre`` opcodes, and executed by an interpreter that follows the
``_sre`` matching algorithm step by step: greedy/lazy single-character
repeats (``REPEAT_ONE``/``MIN_REPEAT_ONE``), general repeats
(``REPEAT`` + ``MAX_UNTIL``/``MIN_UNTIL``) including the zero-width iteration
guard, and the exact mark (capture) save/restore discipline.  Following the
reference algorithm is what makes capture values and spans identical to
``re``, including in the corner cases (empty iterations, captures surviving
from earlier iterations, ...).

Backtracking is implemented with an explicit stack of generator frames
instead of Python recursion, so long inputs do not hit the recursion limit.
"""

from __future__ import annotations

from ._parser import MAXREPEAT

# opcodes
LIT = 0
NLIT = 1
ANY = 2
IN = 3
AT_BEG = 4
AT_END = 5
MARK = 6
JUMP = 7
BRANCH = 8
REPEAT_ONE = 9
MIN_REPEAT_ONE = 10
REPEAT = 11
MAX_UNTIL = 12
MIN_UNTIL = 13
SUCCESS = 14

_DIGIT = frozenset("0123456789")
_WORD = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_SPACE = frozenset(" \t\n\r\f\v")

_CATEGORIES = {
    "d": lambda ch: ch in _DIGIT,
    "D": lambda ch: ch not in _DIGIT,
    "w": lambda ch: ch in _WORD,
    "W": lambda ch: ch not in _WORD,
    "s": lambda ch: ch in _SPACE,
    "S": lambda ch: ch not in _SPACE,
}


def _make_charset(items: list, negate: bool):
    chars = set()
    ranges = []
    cats = []
    for item in items:
        kind = item[0]
        if kind == "LIT":
            chars.add(item[1])
        elif kind == "RANGE":
            ranges.append((item[1], item[2]))
        else:
            cats.append(_CATEGORIES[item[1]])
    chars_f = frozenset(chars)
    ranges_t = tuple(ranges)
    cats_t = tuple(cats)

    def test(ch: str) -> bool:
        if ch in chars_f:
            found = True
        else:
            found = False
            for lo, hi in ranges_t:
                if lo <= ch <= hi:
                    found = True
                    break
            else:
                for cat in cats_t:
                    if cat(ch):
                        found = True
                        break
        return found != negate

    return test


def _char_test(node: tuple):
    """Predicate for a single-character node."""
    kind = node[0]
    if kind == "LIT":
        c = node[1]
        return lambda ch: ch == c
    if kind == "NLIT":
        c = node[1]
        return lambda ch: ch != c
    if kind == "ANY":
        return lambda ch: ch != "\n"
    if kind == "IN":
        return _make_charset(node[1], node[2])
    raise AssertionError(node)  # pragma: no cover


_UNIT = ("LIT", "NLIT", "ANY", "IN")


def _simple(seq: list) -> bool:
    if len(seq) != 1:
        return False
    node = seq[0]
    if node[0] == "SUB":
        return node[1] is None and _simple(node[2])
    return node[0] in _UNIT


def _unit(node: tuple) -> tuple:
    while node[0] == "SUB":
        node = node[2][0]
    return node


def _count(st: _State, ptr: int, limit: int, kind: tuple, test) -> int:
    """Number of consecutive characters from ``ptr`` (below ``limit``) passing ``test``."""
    if ptr >= limit:
        return 0
    text = st.text
    k, c = kind
    if k == "LIT":
        if text[ptr] != c:
            return 0
        chunk = text[ptr:limit]
        return len(chunk) - len(chunk.lstrip(c))
    if k == "ANY" or k == "NLIT":
        q = text.find("\n" if k == "ANY" else c, ptr, limit)
        return (limit if q < 0 else q) - ptr
    # character set: scan a little, then switch to a cached run-length table
    p = ptr
    stop = min(limit, ptr + 32)
    while p < stop and test(text[p]):
        p += 1
    if p < stop or p == limit:
        return p - ptr
    runs = st.runs.get(test)
    if runs is None:
        runs = [0] * (st.end + 1)
        n = 0
        for i in range(st.end - 1, -1, -1):
            n = n + 1 if test(text[i]) else 0
            runs[i] = n
        st.runs[test] = runs
    return min(runs[ptr], limit - ptr)


def _first_char_test(code: list, pc: int):
    """Cheap pre-check used by BRANCH to skip alternatives (like _sre)."""
    op = code[pc]
    if op[0] == LIT:
        return op[1], None
    if op[0] == IN:
        return None, op[1]
    return None, None


def compile_code(seq: list) -> list:
    code: list = []
    _compile(code, seq)
    code.append((SUCCESS,))
    return code


def _compile(code: list, seq: list) -> None:
    for node in seq:
        kind = node[0]
        if kind == "LIT":
            code.append((LIT, node[1]))
        elif kind == "NLIT":
            code.append((NLIT, node[1]))
        elif kind == "ANY":
            code.append((ANY,))
        elif kind == "IN":
            code.append((IN, _make_charset(node[1], node[2])))
        elif kind == "AT":
            code.append((AT_BEG,) if node[1] == "BEG" else (AT_END,))
        elif kind == "SUB":
            group = node[1]
            if group:
                code.append((MARK, (group - 1) * 2))
            _compile(code, node[2])
            if group:
                code.append((MARK, (group - 1) * 2 + 1))
        elif kind == "BRANCH":
            at = len(code)
            code.append(None)
            starts = []
            jumps = []
            for alt in node[1]:
                starts.append(len(code))
                _compile(code, alt)
                jumps.append(len(code))
                code.append(None)
            end = len(code)
            for j in jumps:
                code[j] = (JUMP, end)
            alts = tuple((s, *_first_char_test(code, s)) for s in starts)
            code[at] = (BRANCH, alts)
        elif kind == "REPEAT":
            _, lo, hi, body, greedy = node
            if _simple(body):
                op = REPEAT_ONE if greedy else MIN_REPEAT_ONE
                unit = _unit(body[0])
                code.append((op, lo, hi, _char_test(unit), (unit[0], unit[1] if len(unit) > 1 else None)))
            else:
                at = len(code)
                code.append(None)
                _compile(code, body)
                until = len(code)
                code.append((MAX_UNTIL if greedy else MIN_UNTIL,))
                code[at] = (REPEAT, lo, hi, until)
        else:  # pragma: no cover
            raise AssertionError(node)


class _Repeat:
    __slots__ = ("count", "lo", "hi", "body", "last_ptr", "prev")

    def __init__(self, lo: int, hi: int, body: int, prev: _Repeat | None):
        self.count = -1
        self.lo = lo
        self.hi = hi
        self.body = body
        self.last_ptr = -1
        self.prev = prev


class _State:
    __slots__ = (
        "text",
        "end",
        "start",
        "match_all",
        "must_advance",
        "marks",
        "lastmark",
        "repeat",
        "ptr",
        "runs",
    )

    def __init__(self, text: str, ngroups: int):
        self.text = text
        self.end = len(text)
        self.start = 0
        self.match_all = False
        self.must_advance = False
        self.marks: list = [None] * (2 * ngroups)
        self.lastmark = -1
        self.repeat: _Repeat | None = None
        self.ptr = 0
        self.runs: dict = {}

    def reset(self) -> None:
        self.lastmark = -1
        self.repeat = None


def _frame(st: _State, code: list, pc: int, ptr: int):
    """One matching context.

    Runs instructions sequentially; whenever the reference implementation
    would recurse (``DO_JUMP``) the frame yields ``(pc, ptr)`` and receives
    the child's boolean result.  Returns True on success.
    """
    text = st.text
    end = st.end
    marks = st.marks
    while True:
        op = code[pc]
        kind = op[0]

        if kind == LIT:
            if ptr < end and text[ptr] == op[1]:
                ptr += 1
                pc += 1
                continue
            return False

        if kind == NLIT:
            if ptr < end and text[ptr] != op[1]:
                ptr += 1
                pc += 1
                continue
            return False

        if kind == ANY:
            if ptr < end and text[ptr] != "\n":
                ptr += 1
                pc += 1
                continue
            return False

        if kind == IN:
            if ptr < end and op[1](text[ptr]):
                ptr += 1
                pc += 1
                continue
            return False

        if kind == MARK:
            i = op[1]
            if i > st.lastmark:
                for j in range(st.lastmark + 1, i):
                    marks[j] = None
                st.lastmark = i
            marks[i] = ptr
            pc += 1
            continue

        if kind == JUMP:
            pc = op[1]
            continue

        if kind == AT_BEG:
            if ptr == 0:
                pc += 1
                continue
            return False

        if kind == AT_END:
            if ptr == end or (ptr + 1 == end and text[ptr] == "\n"):
                pc += 1
                continue
            return False

        if kind == SUCCESS:
            if (st.match_all and ptr != end) or (
                st.must_advance and ptr == st.start
            ):
                return False
            st.ptr = ptr
            return True

        if kind == BRANCH:
            lastmark = st.lastmark
            saved = marks[: lastmark + 1] if st.repeat is not None else None
            for alt_pc, lit, charset in op[1]:
                if lit is not None and (ptr >= end or text[ptr] != lit):
                    continue
                if charset is not None and (ptr >= end or not charset(text[ptr])):
                    continue
                if (yield (alt_pc, ptr)):
                    return True
                if saved is not None:
                    marks[: lastmark + 1] = saved
                st.lastmark = lastmark
            return False

        if kind == REPEAT_ONE:
            lo = op[1]
            hi = op[2]
            test = op[3]
            if lo > end - ptr:
                return False
            limit = end if hi == MAXREPEAT or hi >= end - ptr else ptr + hi
            count = _count(st, ptr, limit, op[4], test)
            if count < lo:
                return False
            ptr += count
            lastmark = st.lastmark
            saved = marks[: lastmark + 1] if st.repeat is not None else None
            nxt = pc + 1
            nop = code[nxt]
            if nop[0] == LIT:
                # tail starts with a literal: skip hopeless positions
                c = nop[1]
                while True:
                    q = text.rfind(c, ptr - (count - lo), ptr + 1)
                    if q < 0:
                        break
                    count -= ptr - q
                    ptr = q
                    if (yield (nxt, ptr)):
                        return True
                    if saved is not None:
                        marks[: lastmark + 1] = saved
                    st.lastmark = lastmark
                    ptr -= 1
                    count -= 1
                    if count < lo:
                        break
            else:
                while count >= lo:
                    if (yield (nxt, ptr)):
                        return True
                    if saved is not None:
                        marks[: lastmark + 1] = saved
                    st.lastmark = lastmark
                    ptr -= 1
                    count -= 1
            return False

        if kind == MIN_REPEAT_ONE:
            lo = op[1]
            hi = op[2]
            test = op[3]
            if lo > end - ptr:
                return False
            if lo:
                for p in range(ptr, ptr + lo):
                    if not test(text[p]):
                        return False
                ptr += lo
            count = lo
            lastmark = st.lastmark
            saved = marks[: lastmark + 1] if st.repeat is not None else None
            nxt = pc + 1
            while hi == MAXREPEAT or count <= hi:
                if (yield (nxt, ptr)):
                    return True
                if saved is not None:
                    marks[: lastmark + 1] = saved
                st.lastmark = lastmark
                if ptr < end and test(text[ptr]):
                    ptr += 1
                    count += 1
                else:
                    break
            return False

        if kind == REPEAT:
            _, lo, hi, until = op
            rep = _Repeat(lo, hi, pc + 1, st.repeat)
            st.repeat = rep
            ret = yield (until, ptr)
            st.repeat = rep.prev
            return bool(ret)

        if kind == MAX_UNTIL:
            rep = st.repeat
            count = rep.count + 1
            if count < rep.lo:
                # not enough iterations yet
                rep.count = count
                if (yield (rep.body, ptr)):
                    return True
                rep.count = count - 1
                return False
            if (rep.hi == MAXREPEAT or count < rep.hi) and ptr != rep.last_ptr:
                # try one more iteration
                rep.count = count
                lastmark = st.lastmark
                saved = marks[: lastmark + 1]
                old_last = rep.last_ptr
                rep.last_ptr = ptr  # zero-width iteration guard
                ret = yield (rep.body, ptr)
                rep.last_ptr = old_last
                if ret:
                    return True
                marks[: lastmark + 1] = saved
                st.lastmark = lastmark
                rep.count = count - 1
            # match the tail
            st.repeat = rep.prev
            ret = yield (pc + 1, ptr)
            st.repeat = rep
            return bool(ret)

        if kind == MIN_UNTIL:
            rep = st.repeat
            count = rep.count + 1
            if count < rep.lo:
                rep.count = count
                if (yield (rep.body, ptr)):
                    return True
                rep.count = count - 1
                return False
            # try the tail first
            st.repeat = rep.prev
            lastmark = st.lastmark
            saved = marks[: lastmark + 1] if st.repeat is not None else None
            ret = yield (pc + 1, ptr)
            st.repeat = rep
            if ret:
                return True
            if saved is not None:
                marks[: lastmark + 1] = saved
            st.lastmark = lastmark
            if (rep.hi != MAXREPEAT and count >= rep.hi) or ptr == rep.last_ptr:
                return False
            rep.count = count
            old_last = rep.last_ptr
            rep.last_ptr = ptr
            ret = yield (rep.body, ptr)
            rep.last_ptr = old_last
            if ret:
                return True
            rep.count = count - 1
            return False

        raise AssertionError(f"bad opcode {kind}")  # pragma: no cover


def run(st: _State, code: list, ptr: int) -> bool:
    """Try to match ``code`` at ``ptr``; on success ``st.ptr`` is the end."""
    st.reset()
    st.start = ptr
    stack = [_frame(st, code, 0, ptr)]
    ret = None
    while stack:
        try:
            req = stack[-1].send(ret)
        except StopIteration as stop:
            stack.pop()
            ret = stop.value
            continue
        stack.append(_frame(st, code, req[0], req[1]))
        ret = None
    return bool(ret)


def new_state(text: str, ngroups: int) -> _State:
    return _State(text, ngroups)


def search(st: _State, code: list, pos: int) -> int:
    """Search from ``pos``; returns the match start or -1."""
    end = st.end
    first = True
    while pos <= end:
        if run(st, code, pos):
            st.must_advance = False
            return pos
        if first:
            st.must_advance = False
            first = False
        pos += 1
    st.must_advance = False
    return -1
