"""Pattern parser: turns a pattern string into a small AST.

The grammar and the error cases follow CPython's ``re._parser`` (no flags).

AST nodes are tuples:

* ``("char", pred)``          -- one character accepted by ``pred(ch)``
* ``("at", kind)``            -- zero-width assertion: ``bol``, ``eol``, ``A``, ``Z``, ``b``, ``B``
* ``("seq", [node, ...])``
* ``("alt", [node, ...])``
* ``("group", index_or_None, node)``
* ``("rep", node, min, max_or_None, greedy)``
"""

from __future__ import annotations

MAXREPEAT = 4294967295

DIGITS = frozenset("0123456789")
OCTDIGITS = frozenset("01234567")
HEXDIGITS = frozenset("0123456789abcdefABCDEF")
ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def is_digit(c: str) -> bool:
    return c.isdecimal()


def is_word(c: str) -> bool:
    return c.isalnum() or c == "_"


def is_space(c: str) -> bool:
    return c.isspace()


# Unicode semantics, exactly as re uses for str patterns without flags.
CLASSES = {
    "d": is_digit,
    "D": lambda c: not is_digit(c),
    "w": is_word,
    "W": lambda c: not is_word(c),
    "s": is_space,
    "S": lambda c: not is_space(c),
}

SIMPLE_ESCAPES = {
    "a": "\a",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
}


class RegexError(ValueError):
    """Raised for invalid or unsupported patterns."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None):
        if pattern is not None and pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)
        self.msg = msg
        self.pattern = pattern
        self.pos = pos


def _literal(ch: str):
    return ("char", lambda c: c == ch)


class Parser:
    def __init__(self, pattern: str):
        self.p = pattern
        self.i = 0
        self.ngroups = 0

    # -- helpers ---------------------------------------------------------

    def error(self, msg: str, pos: int | None = None):
        return RegexError(msg, self.p, self.i if pos is None else pos)

    def peek(self) -> str | None:
        return self.p[self.i] if self.i < len(self.p) else None

    def get(self) -> str | None:
        if self.i < len(self.p):
            c = self.p[self.i]
            self.i += 1
            return c
        return None

    def match(self, s: str) -> bool:
        if self.p.startswith(s, self.i):
            self.i += len(s)
            return True
        return False

    def getwhile(self, n: int, charset) -> str:
        out = ""
        while len(out) < n and self.peek() is not None and self.peek() in charset:
            out += self.get()
        return out

    # -- grammar ---------------------------------------------------------

    def parse(self):
        node = self.parse_alt()
        if self.i < len(self.p):
            # only an unmatched ")" can stop the top-level alternation
            raise self.error("unbalanced parenthesis")
        return node

    def parse_alt(self):
        branches = [self.parse_seq()]
        while self.match("|"):
            branches.append(self.parse_seq())
        if len(branches) == 1:
            return branches[0]
        return ("alt", branches)

    def parse_seq(self):
        items: list = []
        # parallel list telling whether each item came from a quantifier
        is_rep: list[bool] = []
        while True:
            c = self.peek()
            if c is None or c in "|)":
                break
            start = self.i
            self.i += 1
            if c in "*+?{":
                if c == "{":
                    q = self.parse_brace()
                    if q is None:
                        items.append(_literal("{"))
                        is_rep.append(False)
                        continue
                    lo, hi = q
                elif c == "*":
                    lo, hi = 0, None
                elif c == "+":
                    lo, hi = 1, None
                else:
                    lo, hi = 0, 1
                if not items or items[-1][0] == "at":
                    raise self.error("nothing to repeat", start)
                if is_rep[-1]:
                    raise self.error("multiple repeat", start)
                greedy = True
                if self.match("?"):
                    greedy = False
                elif self.peek() == "+":
                    raise self.error("possessive quantifiers are not supported")
                items[-1] = ("rep", items[-1], lo, hi, greedy)
                is_rep[-1] = True
                continue
            if c == ".":
                items.append(("char", lambda ch: ch != "\n"))
            elif c == "^":
                items.append(("at", "bol"))
            elif c == "$":
                items.append(("at", "eol"))
            elif c == "[":
                items.append(self.parse_set())
            elif c == "(":
                items.append(self.parse_group())
            elif c == "\\":
                items.append(self.parse_escape())
            else:
                items.append(_literal(c))
            is_rep.append(False)
        if len(items) == 1:
            return items[0]
        return ("seq", items)

    def parse_brace(self):
        """Parse ``{...}`` after the ``{``; return (min, max) or None for a literal ``{``."""
        here = self.i
        if self.peek() == "}":
            return None
        lo = self.getwhile(len(self.p), DIGITS)
        if self.match(","):
            hi = self.getwhile(len(self.p), DIGITS)
        else:
            hi = lo
        if not self.match("}"):
            self.i = here
            return None
        lo_v = int(lo) if lo else 0
        hi_v = int(hi) if hi else None
        if lo_v >= MAXREPEAT or (hi_v is not None and hi_v >= MAXREPEAT):
            raise self.error("the repetition number is too large", here)
        if hi_v is not None and hi_v < lo_v:
            raise self.error("min repeat greater than max repeat", here)
        return lo_v, hi_v

    def parse_group(self):
        start = self.i - 1
        index = None
        if self.match("?"):
            if not self.match(":"):
                if self.peek() is None:
                    raise self.error("unexpected end of pattern")
                raise self.error(f"unsupported group extension '(?{self.peek()}'", start)
        else:
            self.ngroups += 1
            index = self.ngroups
        inner = self.parse_alt()
        if not self.match(")"):
            raise self.error("missing ), unterminated subpattern", start)
        return ("group", index, inner)

    def parse_escape(self):
        start = self.i - 1
        c = self.get()
        if c is None:
            raise self.error("bad escape (end of pattern)", start)
        if c in CLASSES:
            return ("char", CLASSES[c])
        if c == "A":
            return ("at", "A")
        if c == "Z":
            return ("at", "Z")
        if c == "b":
            return ("at", "b")
        if c == "B":
            return ("at", "B")
        if c in DIGITS:
            if c == "0":
                digits = c + self.getwhile(2, OCTDIGITS)
                return _literal(chr(int(digits, 8)))
            if (
                c in OCTDIGITS
                and self.i + 1 < len(self.p)
                and self.p[self.i] in OCTDIGITS
                and self.p[self.i + 1] in OCTDIGITS
            ):
                digits = c + self.p[self.i : self.i + 2]
                self.i += 2
                value = int(digits, 8)
                if value > 0o377:
                    raise self.error(f"octal escape value \\{digits} outside of range 0-0o377")
                return _literal(chr(value))
            raise self.error("backreferences are not supported", start)
        return _literal(self.escape_char(c, start))

    def escape_char(self, c: str, start: int) -> str:
        """Resolve a single-character escape shared by patterns and sets."""
        if c in SIMPLE_ESCAPES:
            return SIMPLE_ESCAPES[c]
        if c in "xuU":
            width = {"x": 2, "u": 4, "U": 8}[c]
            digits = self.getwhile(width, HEXDIGITS)
            if len(digits) != width:
                raise self.error(f"incomplete escape \\{c}{digits}", start)
            value = int(digits, 16)
            if value > 0x10FFFF:
                raise self.error(f"bad escape \\{c}{digits}", start)
            return chr(value)
        if c in ASCII_LETTERS:
            raise self.error(f"bad escape \\{c}", start)
        return c

    def parse_set(self):
        start = self.i - 1
        negate = self.match("^")
        items: list = []  # ("lit", ch) | ("range", lo, hi) | ("class", pred)
        while True:
            this = self.get()
            if this is None:
                raise self.error("unterminated character set", start)
            if this == "]" and items:
                break
            code1 = self.set_atom(this)
            if self.match("-"):
                that = self.get()
                if that is None:
                    raise self.error("unterminated character set", start)
                if that == "]":
                    items.append(code1)
                    items.append(("lit", "-"))
                    break
                code2 = self.set_atom(that)
                if code1[0] != "lit" or code2[0] != "lit":
                    raise self.error("bad character range")
                if ord(code2[1]) < ord(code1[1]):
                    raise self.error("bad character range")
                items.append(("range", code1[1], code2[1]))
            else:
                items.append(code1)

        chars = frozenset(item[1] for item in items if item[0] == "lit")
        ranges = tuple((item[1], item[2]) for item in items if item[0] == "range")
        classes = tuple(item[1] for item in items if item[0] == "class")

        def inside(ch: str) -> bool:
            if ch in chars:
                return True
            for lo, hi in ranges:
                if lo <= ch <= hi:
                    return True
            return any(pred(ch) for pred in classes)

        if negate:
            return ("char", lambda ch: not inside(ch))
        return ("char", inside)

    def set_atom(self, this: str):
        if this != "\\":
            return ("lit", this)
        start = self.i - 1
        c = self.get()
        if c is None:
            raise self.error("bad escape (end of pattern)", start)
        if c in CLASSES:
            return ("class", CLASSES[c])
        if c == "b":
            return ("lit", "\b")
        if c in OCTDIGITS:
            digits = c + self.getwhile(2, OCTDIGITS)
            value = int(digits, 8)
            if value > 0o377:
                raise self.error(f"octal escape value \\{digits} outside of range 0-0o377")
            return ("lit", chr(value))
        if c in DIGITS:
            raise self.error(f"bad escape \\{c}", start)
        return ("lit", self.escape_char(c, start))


def parse(pattern: str):
    """Parse ``pattern``; return ``(ast, number_of_groups)``."""
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a str")
    parser = Parser(pattern)
    ast = parser.parse()
    return ast, parser.ngroups
