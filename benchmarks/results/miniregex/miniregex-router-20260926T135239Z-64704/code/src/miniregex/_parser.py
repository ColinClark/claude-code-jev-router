"""Pattern parser: turns a pattern string into a small AST.

AST nodes are tuples:

    ("lit", ch)                         a literal character
    ("any",)                            ``.`` (anything but ``\\n``)
    ("set", pred)                       a character set or class; ``pred(ch) -> bool``
    ("bol",) / ("eol",)                 ``^`` / ``$``
    ("cat", [node, ...])                concatenation
    ("alt", [node, ...])                alternation
    ("group", index, node)              capturing group
    ("rep", node, min, max, greedy)     repetition; ``max`` is ``None`` for unbounded
"""

from __future__ import annotations

DIGITS = frozenset("0123456789")
WORD = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
SPACE = frozenset(" \t\n\r\f\v")

# Class escapes: letter -> (member set, negated)
CLASSES = {
    "d": (DIGITS, False),
    "D": (DIGITS, True),
    "w": (WORD, False),
    "W": (WORD, True),
    "s": (SPACE, False),
    "S": (SPACE, True),
}

CONTROL_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v", "a": "\a"}

REPEAT_CHARS = "*+?{"

# Escapes that re accepts but miniregex does not implement (word boundaries,
# string anchors, numeric/octal/unicode escapes and backreferences).
UNSUPPORTED_ESCAPES = frozenset("bBAZxuUN0123456789")


class RegexError(Exception):
    """Raised for invalid (or unsupported) patterns."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None):
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)


def _class_pred(members: frozenset[str], negated: bool):
    if negated:
        return lambda ch: ch not in members
    return members.__contains__


class _Parser:
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.pos = 0
        self.ngroups = 0

    # -- helpers ---------------------------------------------------------

    def error(self, msg: str, pos: int | None = None):
        return RegexError(msg, self.pattern, self.pos if pos is None else pos)

    def peek(self) -> str | None:
        if self.pos < len(self.pattern):
            return self.pattern[self.pos]
        return None

    def at_end(self) -> bool:
        return self.pos >= len(self.pattern)

    # -- grammar ---------------------------------------------------------

    def parse(self):
        node = self.parse_alt()
        if not self.at_end():
            # Only a stray ")" can stop parse_alt early.
            raise self.error("unbalanced parenthesis")
        return node

    def parse_alt(self):
        branches = [self.parse_seq()]
        while self.peek() == "|":
            self.pos += 1
            branches.append(self.parse_seq())
        if len(branches) == 1:
            return branches[0]
        return ("alt", branches)

    def parse_seq(self):
        items = []
        while True:
            ch = self.peek()
            if ch is None or ch in "|)":
                break
            start = self.pos
            atom = self.parse_atom()
            if atom is None:
                continue
            atom = self.parse_quantifiers(atom, start)
            items.append(atom)
        if len(items) == 1:
            return items[0]
        return ("cat", items)

    def parse_atom(self):
        p = self.pattern
        ch = p[self.pos]
        if ch == "(":
            return self.parse_group()
        if ch == "[":
            return self.parse_set()
        if ch == ".":
            self.pos += 1
            return ("any",)
        if ch == "^":
            self.pos += 1
            return ("bol",)
        if ch == "$":
            self.pos += 1
            return ("eol",)
        if ch == "\\":
            return self.parse_escape()
        if ch in "*+?":
            raise self.error("nothing to repeat")
        if ch == "{":
            if self.try_brace() is not None:
                raise self.error("nothing to repeat")
            self.pos += 1
            return ("lit", "{")
        self.pos += 1
        return ("lit", ch)

    def parse_group(self):
        open_pos = self.pos
        self.pos += 1
        index = None
        if self.peek() == "?":
            if self.pos + 1 < len(self.pattern) and self.pattern[self.pos + 1] == ":":
                self.pos += 2
            else:
                raise self.error("unsupported group extension", open_pos + 1)
        else:
            self.ngroups += 1
            index = self.ngroups
        body = self.parse_alt()
        if self.peek() != ")":
            raise self.error("missing ), unterminated subpattern", open_pos)
        self.pos += 1
        if index is None:
            # Wrap so that e.g. "(?:^)*" is not mistaken for a bare anchor.
            return ("cat", [body])
        return ("group", index, body)

    def parse_escape(self):
        start = self.pos
        self.pos += 1
        if self.at_end():
            raise self.error("bad escape (end of pattern)", start)
        ch = self.pattern[self.pos]
        self.pos += 1
        if ch in CLASSES:
            return ("set", _class_pred(*CLASSES[ch]))
        if ch in CONTROL_ESCAPES:
            return ("lit", CONTROL_ESCAPES[ch])
        if ch in UNSUPPORTED_ESCAPES:
            raise self.error(f"unsupported escape \\{ch}", start)
        if ch.isascii() and ch.isalnum():
            raise self.error(f"bad escape \\{ch}", start)
        return ("lit", ch)

    def try_brace(self):
        """Parse ``{n}``, ``{n,}``, ``{,m}``, ``{n,m}`` at self.pos without consuming.

        Returns ``(min, max, end_pos)`` or ``None`` if the text is not a valid
        quantifier (in which case ``{`` is a literal, as in ``re``).
        """
        p = self.pattern
        i = self.pos + 1
        n = len(p)
        if i < n and p[i] == "}":
            return None
        j = i
        while j < n and p[j] in DIGITS:
            j += 1
        lo = p[i:j]
        if j < n and p[j] == ",":
            k = j + 1
            while k < n and p[k] in DIGITS:
                k += 1
            hi = p[j + 1 : k]
            j = k
        else:
            hi = lo
        if j >= n or p[j] != "}":
            return None
        mn = int(lo) if lo else 0
        mx = int(hi) if hi else None
        if mx is not None and mx < mn:
            raise self.error("min repeat greater than max repeat", i)
        return mn, mx, j + 1

    def parse_quantifiers(self, atom, atom_start: int):
        quantified = False
        while not self.at_end():
            ch = self.pattern[self.pos]
            if ch not in REPEAT_CHARS:
                break
            here = self.pos
            if ch == "{":
                brace = self.try_brace()
                if brace is None:
                    break
                mn, mx, end = brace
            else:
                mn, mx = {"*": (0, None), "+": (1, None), "?": (0, 1)}[ch]
                end = self.pos + 1
            if quantified:
                raise self.error("multiple repeat", here)
            if atom[0] in ("bol", "eol"):
                raise self.error("nothing to repeat", atom_start)
            self.pos = end
            greedy = True
            nxt = self.peek()
            if nxt == "?":
                greedy = False
                self.pos += 1
            elif nxt == "+":
                raise self.error("unsupported possessive quantifier", self.pos)
            atom = ("rep", atom, mn, mx, greedy)
            quantified = True
        return atom

    def parse_set(self):
        p = self.pattern
        start = self.pos
        self.pos += 1
        negated = False
        if self.peek() == "^":
            negated = True
            self.pos += 1
        chars: set[str] = set()
        ranges: list[tuple[str, str]] = []
        classes: list = []
        first = True
        while True:
            if self.at_end():
                raise self.error("unterminated character set", start)
            ch = p[self.pos]
            if ch == "]" and not first:
                self.pos += 1
                break
            first = False
            item_pos = self.pos
            lo = self.parse_set_item()
            if self.peek() == "-" and self.pos + 1 < len(p) and p[self.pos + 1] != "]":
                self.pos += 1
                hi = self.parse_set_item()
                if isinstance(lo, tuple) or isinstance(hi, tuple):
                    raise self.error(f"bad character range {p[item_pos : self.pos]}", item_pos)
                if ord(hi) < ord(lo):
                    raise self.error(f"bad character range {p[item_pos : self.pos]}", item_pos)
                ranges.append((lo, hi))
            elif self.peek() == "-" and self.pos + 1 >= len(p):
                raise self.error("unterminated character set", start)
            elif isinstance(lo, tuple):
                classes.append(_class_pred(*lo))
            else:
                chars.add(lo)
        members = frozenset(chars)
        ranges_t = tuple(ranges)
        classes_t = tuple(classes)

        def pred(c: str) -> bool:
            if c in members:
                return not negated
            for a, b in ranges_t:
                if a <= c <= b:
                    return not negated
            for cls in classes_t:
                if cls(c):
                    return not negated
            return negated

        return ("set", pred)

    def parse_set_item(self):
        """Return a single character, or ``(members, negated)`` for a class escape."""
        p = self.pattern
        ch = p[self.pos]
        if ch != "\\":
            self.pos += 1
            return ch
        start = self.pos
        self.pos += 1
        if self.at_end():
            raise self.error("bad escape (end of pattern)", start)
        ch = p[self.pos]
        self.pos += 1
        if ch in CLASSES:
            return CLASSES[ch]
        if ch in CONTROL_ESCAPES:
            return CONTROL_ESCAPES[ch]
        if ch in UNSUPPORTED_ESCAPES:
            raise self.error(f"unsupported escape \\{ch}", start)
        if ch.isascii() and ch.isalnum():
            raise self.error(f"bad escape \\{ch}", start)
        return ch


def parse(pattern: str):
    """Parse *pattern* and return ``(ast, number_of_groups)``."""
    parser = _Parser(pattern)
    ast = parser.parse()
    return ast, parser.ngroups
