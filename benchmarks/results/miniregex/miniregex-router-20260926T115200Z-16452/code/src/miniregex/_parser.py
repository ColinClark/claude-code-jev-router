"""Pattern parser and program generator.

The parser deliberately mirrors the decisions made by CPython's ``re._parser``
and ``re._compiler`` (which quantifier forms are literals, when a
non-capturing group is unwrapped under a quantifier, when a branch is folded
into a character set, which items are "simple" enough for the single-item
repeat instructions).  Producing a program with the same shape as sre's is
what makes match results identical, including capture values inside repeats
and the termination rules for empty iterations.

The program is a flat Python list.  Instruction layouts:

    SUCCESS
    LITERAL ch
    ANY
    IN charset
    AT code
    MARK index
    JUMP target
    BRANCH (alt_pc, ...)            each alternative ends with JUMP end
    REPEAT min max until_pc  item...  MAX_UNTIL|MIN_UNTIL  tail...
    REPEAT_ONE|MIN_REPEAT_ONE min max tail_pc  unit_item  tail...
"""

from __future__ import annotations

from ._errors import RegexError

#: Largest repeat count accepted (``_sre.MAXREPEAT`` on 64-bit builds).
MAXREPEAT = 4_294_967_295

# Opcodes.
SUCCESS = 0
LITERAL = 1
ANY = 2
IN = 3
AT = 4
MARK = 5
JUMP = 6
BRANCH = 7
REPEAT = 8
MAX_UNTIL = 9
MIN_UNTIL = 10
REPEAT_ONE = 11
MIN_REPEAT_ONE = 12

# AT codes.
AT_BEGINNING = 0
AT_END = 1

_DIGITS = frozenset("0123456789")
_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_WORD_CHARS = _ASCII_LETTERS | _DIGITS | {"_"}
_SPACE_CHARS = frozenset(" \t\n\r\f\v")


def _is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_word(ch: str) -> bool:
    return ch in _WORD_CHARS


def _is_space(ch: str) -> bool:
    return ch in _SPACE_CHARS


# name -> (predicate, negated)
_CATEGORIES = {
    "d": (_is_digit, False),
    "D": (_is_digit, True),
    "w": (_is_word, False),
    "W": (_is_word, True),
    "s": (_is_space, False),
    "S": (_is_space, True),
}

_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v", "a": "\a"}

# Node kinds that ``re._parser`` compares by value when factoring a common
# branch prefix (SUBPATTERN / repeat nodes contain SubPattern objects and are
# therefore compared by identity there, i.e. never equal).
_FLAT_KINDS = frozenset({"lit", "any", "in", "at"})


class CharSet:
    """A character set built from literals, ranges and class predicates."""

    __slots__ = ("items", "negate", "_chars", "_ranges", "_cats", "_cache")

    def __init__(self, items, negate: bool) -> None:
        self.items = tuple(items)
        self.negate = negate
        chars = set()
        ranges = []
        cats = []
        for item in self.items:
            kind = item[0]
            if kind == "lit":
                chars.add(item[1])
            elif kind == "range":
                ranges.append((item[1], item[2]))
            else:
                cats.append(item[1])
        self._chars = frozenset(chars)
        self._ranges = tuple(ranges)
        self._cats = tuple(cats)
        self._cache: dict[str, bool] = {}

    def __contains__(self, ch: str) -> bool:
        hit = self._cache.get(ch)
        if hit is None:
            hit = ch in self._chars
            if not hit:
                for lo, hi in self._ranges:
                    if lo <= ch <= hi:
                        hit = True
                        break
            if not hit:
                for pred, negated in self._cats:
                    if pred(ch) != negated:
                        hit = True
                        break
            hit = hit != self.negate
            self._cache[ch] = hit
        return hit

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CharSet):
            return NotImplemented
        return self.negate == other.negate and self.items == other.items

    def __hash__(self) -> int:
        return hash((self.negate, self.items))


class _Source:
    """Tokenizer: yields single characters or two-character escape tokens."""

    __slots__ = ("string", "index", "next")

    def __init__(self, string: str) -> None:
        self.string = string
        self.index = 0
        self.next: str | None = None
        self._advance()

    def _advance(self) -> None:
        string = self.string
        index = self.index
        if index >= len(string):
            self.next = None
            return
        char = string[index]
        if char == "\\":
            index += 1
            if index >= len(string):
                raise RegexError("bad escape (end of pattern)")
            char += string[index]
        self.index = index + 1
        self.next = char

    def get(self) -> str | None:
        this = self.next
        self._advance()
        return this

    def match(self, char: str) -> bool:
        if self.next == char:
            self._advance()
            return True
        return False

    def tell(self) -> int:
        return self.index - len(self.next or "")

    def seek(self, index: int) -> None:
        self.index = index
        self._advance()


class _State:
    __slots__ = ("groups",)

    def __init__(self) -> None:
        self.groups = 0

    def opengroup(self) -> int:
        self.groups += 1
        return self.groups


def _escape(token: str, in_class: bool):
    """Translate an escape token (``\\x``) to a node."""
    ch = token[1]
    cat = _CATEGORIES.get(ch)
    if cat is not None:
        if in_class:
            return ("cat", cat)
        return ("in", CharSet([("cat", cat)], False))
    if ch in _SIMPLE_ESCAPES:
        return ("lit", _SIMPLE_ESCAPES[ch])
    if in_class and ch == "b":
        return ("lit", "\b")
    if ch in _ASCII_LETTERS or ch in _DIGITS:
        raise RegexError(f"bad escape \\{ch}")
    return ("lit", ch)


def _parse_set(source: _Source):
    items = []
    negate = source.match("^")
    while True:
        this = source.get()
        if this is None:
            raise RegexError("unterminated character set")
        if this == "]" and items:
            break
        if this[0] == "\\":
            code1 = _escape(this, True)
        else:
            code1 = ("lit", this)
        if source.match("-"):
            that = source.get()
            if that is None:
                raise RegexError("unterminated character set")
            if that == "]":
                items.append(code1)
                items.append(("lit", "-"))
                break
            if that[0] == "\\":
                code2 = _escape(that, True)
            else:
                code2 = ("lit", that)
            if code1[0] != "lit" or code2[0] != "lit":
                raise RegexError(f"bad character range {this}-{that}")
            lo = code1[1]
            hi = code2[1]
            if hi < lo:
                raise RegexError(f"bad character range {this}-{that}")
            items.append(("range", lo, hi))
        else:
            items.append(code1)
    return ("in", CharSet(items, negate))


def _parse_repeat(source: _Source, this: str, seq: list) -> None:
    if this == "?":
        lo_n, hi_n = 0, 1
    elif this == "*":
        lo_n, hi_n = 0, MAXREPEAT
    elif this == "+":
        lo_n, hi_n = 1, MAXREPEAT
    else:  # "{"
        if source.next == "}":
            seq.append(("lit", "{"))
            return
        here = source.tell()
        lo = hi = ""
        while source.next is not None and source.next in _DIGITS:
            lo += source.get()
        if source.match(","):
            while source.next is not None and source.next in _DIGITS:
                hi += source.get()
        else:
            hi = lo
        if not source.match("}"):
            # Not a quantifier after all: "{" is a literal.
            seq.append(("lit", "{"))
            source.seek(here)
            return
        lo_n, hi_n = 0, MAXREPEAT
        if lo:
            lo_n = int(lo)
            if lo_n >= MAXREPEAT:
                raise RegexError("the repetition number is too large")
        if hi:
            hi_n = int(hi)
            if hi_n >= MAXREPEAT:
                raise RegexError("the repetition number is too large")
            if hi_n < lo_n:
                raise RegexError("min repeat greater than max repeat")
    if not seq or seq[-1][0] == "at":
        raise RegexError("nothing to repeat")
    item = seq[-1]
    if item[0] == "rep":
        raise RegexError("multiple repeat")
    if item[0] == "group" and item[1] is None:
        body = item[2]
    else:
        body = [item]
    if source.match("?"):
        lazy = True
    elif source.match("+"):
        raise RegexError("possessive quantifiers are not supported")
    else:
        lazy = False
    seq[-1] = ("rep", lo_n, hi_n, body, lazy)


def _parse(source: _Source, state: _State, nested: int) -> list:
    seq: list = []
    while True:
        this = source.next
        if this is None or this == "|" or this == ")":
            break
        source.get()
        if this[0] == "\\":
            seq.append(_escape(this, False))
        elif this == "[":
            seq.append(_parse_set(source))
        elif this == "*" or this == "+" or this == "?" or this == "{":
            _parse_repeat(source, this, seq)
        elif this == ".":
            seq.append(("any",))
        elif this == "(":
            group: int | None = -1
            if source.match("?"):
                if source.match(":"):
                    group = None
                elif source.next is None:
                    raise RegexError("unexpected end of pattern")
                else:
                    raise RegexError(f"unsupported extension (?{source.next}")
            if group is not None:
                group = state.opengroup()
            sub = _parse_sub(source, state, nested + 1)
            if not source.match(")"):
                raise RegexError("missing ), unterminated subpattern")
            seq.append(("group", group, sub))
        elif this == "^":
            seq.append(("at", AT_BEGINNING))
        elif this == "$":
            seq.append(("at", AT_END))
        else:
            seq.append(("lit", this))
    return seq


def _parse_sub(source: _Source, state: _State, nested: int) -> list:
    items = []
    while True:
        items.append(_parse(source, state, nested))
        if not source.match("|"):
            break
    if len(items) == 1:
        return items[0]

    seq: list = []
    # Move a common prefix of flat items out of the branch.
    while True:
        prefix = None
        for item in items:
            if not item:
                break
            if prefix is None:
                prefix = item[0]
                if prefix[0] not in _FLAT_KINDS:
                    break
            elif item[0] != prefix:
                break
        else:
            for item in items:
                del item[0]
            seq.append(prefix)
            continue
        break

    # A branch of single characters / non-negated sets is a character set.
    set_items = []
    for item in items:
        if len(item) != 1:
            break
        node = item[0]
        if node[0] == "lit":
            set_items.append(node)
        elif node[0] == "in" and not node[1].negate:
            set_items.extend(node[1].items)
        else:
            break
    else:
        seq.append(("in", CharSet(set_items, False)))
        return seq

    seq.append(("branch", items))
    return seq


def parse(pattern: str) -> tuple[list, int]:
    """Parse ``pattern`` into a node sequence; return ``(seq, group_count)``."""
    source = _Source(pattern)
    state = _State()
    seq = _parse_sub(source, state, 0)
    if source.next is not None:
        # Only an unmatched ")" can stop the top-level parse early.
        raise RegexError("unbalanced parenthesis")
    return seq, state.groups


def _simple(body: list) -> bool:
    if len(body) != 1:
        return False
    node = body[0]
    kind = node[0]
    if kind == "group":
        return node[1] is None and _simple(node[2])
    return kind == "lit" or kind == "any" or kind == "in"


def _emit(seq: list, code: list) -> None:
    for node in seq:
        kind = node[0]
        if kind == "lit":
            code.append(LITERAL)
            code.append(node[1])
        elif kind == "any":
            code.append(ANY)
        elif kind == "in":
            code.append(IN)
            code.append(node[1])
        elif kind == "at":
            code.append(AT)
            code.append(node[1])
        elif kind == "group":
            gid = node[1]
            if gid is not None:
                code.append(MARK)
                code.append((gid - 1) * 2)
            _emit(node[2], code)
            if gid is not None:
                code.append(MARK)
                code.append((gid - 1) * 2 + 1)
        elif kind == "branch":
            code.append(BRANCH)
            alts_slot = len(code)
            code.append(None)
            alts = []
            jumps = []
            for alt in node[1]:
                alts.append(len(code))
                _emit(alt, code)
                code.append(JUMP)
                jumps.append(len(code))
                code.append(None)
            end = len(code)
            code[alts_slot] = tuple(alts)
            for slot in jumps:
                code[slot] = end
        elif kind == "rep":
            _, lo, hi, body, lazy = node
            if _simple(body):
                code.append(MIN_REPEAT_ONE if lazy else REPEAT_ONE)
                code.append(lo)
                code.append(hi)
                skip = len(code)
                code.append(None)
                _emit(body, code)
                code[skip] = len(code)
            else:
                code.append(REPEAT)
                code.append(lo)
                code.append(hi)
                skip = len(code)
                code.append(None)
                _emit(body, code)
                code[skip] = len(code)
                code.append(MIN_UNTIL if lazy else MAX_UNTIL)
        else:  # pragma: no cover - parser only produces the kinds above
            raise RegexError(f"internal error: unknown node {kind!r}")


def compile_pattern(pattern: str) -> tuple[list, int]:
    """Compile ``pattern`` to a program; return ``(code, group_count)``."""
    seq, groups = parse(pattern)
    code: list = []
    _emit(seq, code)
    code.append(SUCCESS)
    return code, groups
