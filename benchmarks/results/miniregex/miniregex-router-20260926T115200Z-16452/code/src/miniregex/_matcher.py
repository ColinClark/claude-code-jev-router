"""Backtracking matcher.

This is an iterative translation of the matching loop in CPython's
``Modules/_sre/sre_lib.h``: every ``DO_JUMP`` there becomes a frame pushed on
an explicit Python list, so there is no Python-level recursion and long
inputs (thousands of iterations of a repeated group) cannot exhaust the
interpreter's recursion limit.

Mirroring sre's control flow rather than "a" backtracking algorithm is what
gives results identical to :mod:`re`:

* ``lastmark`` save/restore and the mark push/pop performed inside repeats
  reproduce re's capture values (a group that matched in an earlier iteration
  of a repeat but not in the last one keeps its earlier value);
* the ``last_ptr`` checks in MAX_UNTIL / MIN_UNTIL reproduce re's rules for
  zero-width iterations of ``*``, ``+`` and ``{n,}``;
* the ``match_all`` / ``must_advance`` checks in SUCCESS reproduce
  ``fullmatch`` and the empty-match advancing rules of ``findall``.
"""

from __future__ import annotations

from ._parser import (
    ANY,
    AT,
    AT_BEGINNING,
    BRANCH,
    IN,
    JUMP,
    LITERAL,
    MARK,
    MAX_UNTIL,
    MIN_REPEAT_ONE,
    MIN_UNTIL,
    REPEAT,
    REPEAT_ONE,
    SUCCESS,
)

# Frame kinds: which continuation runs when the frame's callee returns.
J_NONE = 0
J_BRANCH = 1
J_REPEAT = 2
J_MAX_UNTIL_1 = 3
J_MAX_UNTIL_2 = 4
J_MAX_UNTIL_3 = 5
J_MIN_UNTIL_1 = 6
J_MIN_UNTIL_2 = 7
J_MIN_UNTIL_3 = 8
J_REPEAT_ONE = 9
J_MIN_REPEAT_ONE = 10


class _Ctx:
    __slots__ = (
        "jump",
        "pc",
        "ptr",
        "lastmark",
        "lastindex",
        "count",
        "rep",
        "marks",
        "last_ptr",
        "alts",
        "alti",
        "tail",
        "chr",
    )

    def __init__(self, jump: int) -> None:
        self.jump = jump
        self.marks = None


class _Repeat:
    __slots__ = ("count", "pc", "prev", "last_ptr")

    def __init__(self, pc: int, prev) -> None:
        self.count = -1
        self.pc = pc
        self.prev = prev
        self.last_ptr = None


def _count(code: list, ipc: int, text: str, ptr: int, end: int, maxcount: int) -> int:
    """Count how many times the single-width item at ``ipc`` matches from ``ptr``."""
    limit = ptr + maxcount
    if limit > end:
        limit = end
    op = code[ipc]
    i = ptr
    if op == LITERAL:
        ch = code[ipc + 1]
        while i < limit and text[i] == ch:
            i += 1
    elif op == ANY:
        j = text.find("\n", i, limit)
        i = limit if j < 0 else j
    else:  # IN
        charset = code[ipc + 1]
        while i < limit and text[i] in charset:
            i += 1
    return i - ptr


def run(
    code: list,
    text: str,
    start: int,
    end: int,
    nmarks: int,
    match_all: bool,
    must_advance: bool,
):
    """Try to match ``code`` at exactly ``start``.

    Returns ``(matched, end_ptr, marks, lastmark, lastindex)``.
    """
    marks: list = [None] * nmarks
    lastmark = -1
    lastindex = -1
    repeat = None
    sptr = start  # sre's state->ptr
    stack: list[_Ctx] = []
    ctx = _Ctx(J_NONE)
    pc = 0
    ptr = start
    ret = None  # None: dispatch the instruction at pc; bool: return to parent
    while True:
        if ret is None:
            op = code[pc]
            if op == LITERAL:
                if ptr >= end or text[ptr] != code[pc + 1]:
                    ret = False
                else:
                    pc += 2
                    ptr += 1
                continue
            if op == ANY:
                if ptr >= end or text[ptr] == "\n":
                    ret = False
                else:
                    pc += 1
                    ptr += 1
                continue
            if op == IN:
                if ptr >= end or text[ptr] not in code[pc + 1]:
                    ret = False
                else:
                    pc += 2
                    ptr += 1
                continue
            if op == SUCCESS:
                if (match_all and ptr != end) or (must_advance and ptr == start):
                    ret = False
                else:
                    sptr = ptr
                    ret = True
                continue
            if op == AT:
                if code[pc + 1] == AT_BEGINNING:
                    ok = ptr == 0
                else:
                    ok = ptr == end or (ptr + 1 == end and text[ptr] == "\n")
                if ok:
                    pc += 2
                else:
                    ret = False
                continue
            if op == MARK:
                i = code[pc + 1]
                if i & 1:
                    lastindex = i // 2 + 1
                if i > lastmark:
                    j = lastmark + 1
                    while j < i:
                        marks[j] = None
                        j += 1
                    lastmark = i
                marks[i] = ptr
                pc += 2
                continue
            if op == JUMP:
                pc = code[pc + 1]
                continue
            if op == BRANCH:
                ctx.lastmark = lastmark
                ctx.lastindex = lastindex
                if repeat is not None:
                    ctx.marks = marks[: lastmark + 1]
                alts = code[pc + 1]
                ctx.alts = alts
                ctx.alti = 0
                sptr = ptr
                ctx.pc = pc
                ctx.ptr = ptr
                stack.append(ctx)
                ctx = _Ctx(J_BRANCH)
                pc = alts[0]
                ptr = sptr
                continue
            if op == REPEAT_ONE:
                mn = code[pc + 1]
                if mn > end - ptr:
                    ret = False
                    continue
                sptr = ptr
                count = _count(code, pc + 4, text, ptr, end, code[pc + 2])
                ptr += count
                if count < mn:
                    ret = False
                    continue
                tail = code[pc + 3]
                tail_op = code[tail]
                if tail_op == SUCCESS and ptr == end and not (must_advance and ptr == start):
                    sptr = ptr
                    ret = True
                    continue
                ctx.lastmark = lastmark
                ctx.lastindex = lastindex
                if repeat is not None:
                    ctx.marks = marks[: lastmark + 1]
                ctx.tail = tail
                chr_ = code[tail + 1] if tail_op == LITERAL else None
                ctx.chr = chr_
                if chr_ is not None:
                    # Skip end positions where the tail's first literal cannot match.
                    while count >= mn and (ptr >= end or text[ptr] != chr_):
                        ptr -= 1
                        count -= 1
                    if count < mn:
                        ret = False
                        continue
                ctx.count = count
                sptr = ptr
                ctx.pc = pc
                ctx.ptr = ptr
                stack.append(ctx)
                ctx = _Ctx(J_REPEAT_ONE)
                pc = tail
                ptr = sptr
                continue
            if op == MIN_REPEAT_ONE:
                mn = code[pc + 1]
                if mn > end - ptr:
                    ret = False
                    continue
                sptr = ptr
                if mn == 0:
                    count = 0
                else:
                    count = _count(code, pc + 4, text, ptr, end, mn)
                    if count < mn:
                        ret = False
                        continue
                    ptr += count
                tail = code[pc + 3]
                if code[tail] == SUCCESS and not (
                    (match_all and ptr != end) or (must_advance and ptr == start)
                ):
                    sptr = ptr
                    ret = True
                    continue
                ctx.lastmark = lastmark
                ctx.lastindex = lastindex
                if repeat is not None:
                    ctx.marks = marks[: lastmark + 1]
                ctx.tail = tail
                ctx.count = count
                if count <= code[pc + 2]:
                    sptr = ptr
                    ctx.pc = pc
                    ctx.ptr = ptr
                    stack.append(ctx)
                    ctx = _Ctx(J_MIN_REPEAT_ONE)
                    pc = tail
                    ptr = sptr
                    continue
                ret = False
                continue
            if op == REPEAT:
                rep = _Repeat(pc, repeat)
                ctx.rep = rep
                repeat = rep
                sptr = ptr
                ctx.pc = pc
                ctx.ptr = ptr
                stack.append(ctx)
                ctx = _Ctx(J_REPEAT)
                pc = code[pc + 3]
                ptr = sptr
                continue
            if op == MAX_UNTIL:
                rep = repeat
                ctx.rep = rep
                sptr = ptr
                count = rep.count + 1
                ctx.count = count
                rpc = rep.pc
                if count < code[rpc + 1]:
                    # Not enough iterations yet: match another item.
                    rep.count = count
                    ctx.pc = pc
                    ctx.ptr = ptr
                    stack.append(ctx)
                    ctx = _Ctx(J_MAX_UNTIL_1)
                    pc = rpc + 4
                    ptr = sptr
                    continue
                if count < code[rpc + 2] and sptr != rep.last_ptr:
                    # Enough iterations, but greedily try one more.
                    rep.count = count
                    ctx.lastmark = lastmark
                    ctx.lastindex = lastindex
                    ctx.marks = marks[: lastmark + 1]
                    ctx.last_ptr = rep.last_ptr
                    rep.last_ptr = sptr
                    ctx.pc = pc
                    ctx.ptr = ptr
                    stack.append(ctx)
                    ctx = _Ctx(J_MAX_UNTIL_2)
                    pc = rpc + 4
                    ptr = sptr
                    continue
                # Cannot match more items: try the tail.
                repeat = rep.prev
                ctx.pc = pc
                ctx.ptr = ptr
                stack.append(ctx)
                ctx = _Ctx(J_MAX_UNTIL_3)
                pc += 1
                ptr = sptr
                continue
            if op == MIN_UNTIL:
                rep = repeat
                ctx.rep = rep
                sptr = ptr
                count = rep.count + 1
                ctx.count = count
                rpc = rep.pc
                if count < code[rpc + 1]:
                    rep.count = count
                    ctx.pc = pc
                    ctx.ptr = ptr
                    stack.append(ctx)
                    ctx = _Ctx(J_MIN_UNTIL_1)
                    pc = rpc + 4
                    ptr = sptr
                    continue
                # Lazily try the tail first.
                repeat = rep.prev
                ctx.lastmark = lastmark
                ctx.lastindex = lastindex
                if repeat is not None:
                    ctx.marks = marks[: lastmark + 1]
                ctx.pc = pc
                ctx.ptr = ptr
                stack.append(ctx)
                ctx = _Ctx(J_MIN_UNTIL_2)
                pc += 1
                ptr = sptr
                continue
            raise RuntimeError(f"miniregex internal error: bad opcode {op!r}")

        # ---- a frame finished with result `ret`: resume its parent ----
        jump = ctx.jump
        if not stack:
            return ret, sptr, marks, lastmark, lastindex
        ctx = stack.pop()
        pc = ctx.pc
        ptr = ctx.ptr

        if jump == J_BRANCH:
            if ret:
                continue
            saved = ctx.marks
            if saved is not None:
                marks[: len(saved)] = saved
            lastmark = ctx.lastmark
            lastindex = ctx.lastindex
            alti = ctx.alti + 1
            alts = ctx.alts
            if alti < len(alts):
                ctx.alti = alti
                sptr = ptr
                stack.append(ctx)
                ctx = _Ctx(J_BRANCH)
                pc = alts[alti]
                ptr = sptr
                ret = None
            continue

        if jump == J_REPEAT_ONE:
            if ret:
                continue
            saved = ctx.marks
            if saved is not None:
                marks[: len(saved)] = saved
            lastmark = ctx.lastmark
            lastindex = ctx.lastindex
            ptr -= 1
            count = ctx.count - 1
            mn = code[pc + 1]
            chr_ = ctx.chr
            if chr_ is not None:
                while count >= mn and (ptr >= end or text[ptr] != chr_):
                    ptr -= 1
                    count -= 1
            if count < mn:
                continue
            ctx.count = count
            sptr = ptr
            ctx.ptr = ptr
            stack.append(ctx)
            tail = ctx.tail
            ctx = _Ctx(J_REPEAT_ONE)
            pc = tail
            ptr = sptr
            ret = None
            continue

        if jump == J_MIN_REPEAT_ONE:
            if ret:
                continue
            saved = ctx.marks
            if saved is not None:
                marks[: len(saved)] = saved
            lastmark = ctx.lastmark
            lastindex = ctx.lastindex
            sptr = ptr
            if _count(code, pc + 4, text, ptr, end, 1) == 0:
                continue
            ptr += 1
            count = ctx.count + 1
            if count > code[pc + 2]:
                continue
            ctx.count = count
            sptr = ptr
            ctx.ptr = ptr
            stack.append(ctx)
            tail = ctx.tail
            ctx = _Ctx(J_MIN_REPEAT_ONE)
            pc = tail
            ptr = sptr
            ret = None
            continue

        if jump == J_REPEAT:
            repeat = ctx.rep.prev
            continue

        if jump == J_MAX_UNTIL_1:
            if ret:
                continue
            ctx.rep.count = ctx.count - 1
            sptr = ptr
            continue

        if jump == J_MAX_UNTIL_2:
            rep = ctx.rep
            rep.last_ptr = ctx.last_ptr
            if ret:
                continue
            saved = ctx.marks
            marks[: len(saved)] = saved
            lastmark = ctx.lastmark
            lastindex = ctx.lastindex
            rep.count = ctx.count - 1
            sptr = ptr
            # Fall through to the tail attempt.
            repeat = rep.prev
            stack.append(ctx)
            ctx = _Ctx(J_MAX_UNTIL_3)
            pc += 1
            ptr = sptr
            ret = None
            continue

        if jump == J_MAX_UNTIL_3:
            repeat = ctx.rep
            if ret:
                continue
            sptr = ptr
            continue

        if jump == J_MIN_UNTIL_1:
            if ret:
                continue
            ctx.rep.count = ctx.count - 1
            sptr = ptr
            continue

        if jump == J_MIN_UNTIL_2:
            rep = ctx.rep
            repeat = rep
            if ret:
                continue
            saved = ctx.marks
            if saved is not None:
                marks[: len(saved)] = saved
            lastmark = ctx.lastmark
            lastindex = ctx.lastindex
            sptr = ptr
            count = ctx.count
            if count >= code[rep.pc + 2] or sptr == rep.last_ptr:
                continue
            rep.count = count
            ctx.last_ptr = rep.last_ptr
            rep.last_ptr = sptr
            stack.append(ctx)
            ctx = _Ctx(J_MIN_UNTIL_3)
            pc = rep.pc + 4
            ptr = sptr
            ret = None
            continue

        if jump == J_MIN_UNTIL_3:
            rep = ctx.rep
            rep.last_ptr = ctx.last_ptr
            if ret:
                continue
            rep.count = ctx.count - 1
            sptr = ptr
            continue

        raise RuntimeError(f"miniregex internal error: bad frame kind {jump!r}")


def search(code: list, text: str, start: int, end: int, nmarks: int, must_advance: bool):
    """Find the leftmost match starting at or after ``start``.

    Returns ``None`` or ``(match_start, run_result)``.
    """
    if start > end:
        return None
    ptr = start
    result = run(code, text, ptr, end, nmarks, False, must_advance)
    if not result[0] and code[0] == AT and code[1] == AT_BEGINNING:
        return None
    while not result[0] and ptr < end:
        ptr += 1
        result = run(code, text, ptr, end, nmarks, False, False)
    if not result[0]:
        return None
    return ptr, result
