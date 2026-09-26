"""Pattern parser: turns a pattern string into a small AST.

The grammar and error rules follow CPython's ``sre_parse`` (``re._parser``)
for the supported syntax subset, so that the same patterns are accepted or
rejected and the resulting structure has the same meaning.

AST node shapes (plain tuples):

- ``("char", pred)``: match one character ``c`` for which ``pred(c)`` is true
- ``("bol",)``: start of string (``^``)
- ``("eol",)``: end of string, or before a final ``\\n`` (``$``)
- ``("seq", [node, ...])``: concatenation
- ``("alt", [node, ...])``: alternation, tried left to right
- ``("group", index, node)``: capturing group ``index`` (1-based)
- ``("repeat", node, min, max, greedy)``: ``max`` is ``None`` for unbounded
"""

from ._errors import RegexError

MAXREPEAT = 4294967295

_DIGITS = frozenset("0123456789")
_OCTDIGITS = frozenset("01234567")
_HEXDIGITS = frozenset("0123456789abcdefABCDEF")
_ASCIILETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

# Character-class predicates. These mirror the default (unicode str pattern)
# behaviour of Python's ``re``; for ASCII text they are exactly the ASCII sets
# (\d = 0-9, \w = [A-Za-z0-9_], \s includes space, \t, \n, \r, \f, \v).


def _is_digit(c):
    return c.isdecimal()


def _is_word(c):
    return c.isalnum() or c == "_"


def _is_space(c):
    return c.isspace()


def _not(pred):
    return lambda c: not pred(c)


_CATEGORIES = {
    "\\d": _is_digit,
    "\\D": _not(_is_digit),
    "\\w": _is_word,
    "\\W": _not(_is_word),
    "\\s": _is_space,
    "\\S": _not(_is_space),
}

# Simple escapes producing a literal character (valid in and out of sets).
_ESCAPES = {
    "\\a": "\a",
    "\\f": "\f",
    "\\n": "\n",
    "\\r": "\r",
    "\\t": "\t",
    "\\v": "\v",
    "\\\\": "\\",
}


def _dot(c):
    return c != "\n"


class _Source:
    """Tokenizer: yields single characters, or two-character escapes."""

    def __init__(self, pattern):
        self.pattern = pattern
        self.index = 0
        self.next = None
        self._advance()

    def _advance(self):
        p = self.pattern
        i = self.index
        if i >= len(p):
            self.next = None
            return
        c = p[i]
        if c == "\\":
            if i + 1 >= len(p):
                raise RegexError("bad escape (end of pattern)")
            c = p[i : i + 2]
        self.index = i + len(c)
        self.next = c

    def get(self):
        tok = self.next
        self._advance()
        return tok

    def match(self, tok):
        if self.next == tok:
            self._advance()
            return True
        return False

    def getwhile(self, n, charset):
        result = ""
        for _ in range(n):
            c = self.next
            if c not in charset:
                break
            result += c
            self._advance()
        return result

    def tell(self):
        return self.index - len(self.next or "")

    def seek(self, index):
        self.index = index
        self._advance()


def _unicode_escape(source, escape):
    """Handle \\x, \\u, \\U escapes. Returns a literal char or None."""
    c = escape[1:2]
    if c == "x":
        escape += source.getwhile(2, _HEXDIGITS)
        if len(escape) != 4:
            raise RegexError(f"incomplete escape {escape}")
        return chr(int(escape[2:], 16))
    if c == "u":
        escape += source.getwhile(4, _HEXDIGITS)
        if len(escape) != 6:
            raise RegexError(f"incomplete escape {escape}")
        return chr(int(escape[2:], 16))
    if c == "U":
        escape += source.getwhile(8, _HEXDIGITS)
        if len(escape) != 10:
            raise RegexError(f"incomplete escape {escape}")
        code = int(escape[2:], 16)
        if code > 0x10FFFF:
            raise RegexError(f"bad escape {escape}")
        return chr(code)
    return None


def _class_escape(source, escape):
    """Escape inside a character set. Returns ("lit", ch) or ("cat", pred)."""
    if escape in _ESCAPES:
        return ("lit", _ESCAPES[escape])
    if escape == "\\b":
        return ("lit", "\b")
    if escape in _CATEGORIES:
        return ("cat", _CATEGORIES[escape])
    ch = _unicode_escape(source, escape)
    if ch is not None:
        return ("lit", ch)
    c = escape[1:2]
    if c in _OCTDIGITS:
        escape += source.getwhile(2, _OCTDIGITS)
        code = int(escape[1:], 8)
        if code > 0o377:
            raise RegexError(f"octal escape value {escape} outside of range 0-0o377")
        return ("lit", chr(code))
    if c in _DIGITS or c in _ASCIILETTERS:
        raise RegexError(f"bad escape {escape}")
    return ("lit", escape[1])


def _escape(source, escape):
    """Escape outside a character set. Returns an AST node."""
    if escape in _CATEGORIES:
        return ("char", _CATEGORIES[escape])
    if escape in _ESCAPES:
        return _literal(_ESCAPES[escape])
    ch = _unicode_escape(source, escape)
    if ch is not None:
        return _literal(ch)
    c = escape[1:2]
    if c == "0":
        escape += source.getwhile(2, _OCTDIGITS)
        return _literal(chr(int(escape[1:], 8)))
    if c in _DIGITS:
        # Octal escape (three octal digits) or a group reference.
        if source.next is not None and source.next in _DIGITS:
            escape += source.get()
            if (
                escape[1] in _OCTDIGITS
                and escape[2] in _OCTDIGITS
                and source.next is not None
                and source.next in _OCTDIGITS
            ):
                escape += source.get()
                code = int(escape[1:], 8)
                if code > 0o377:
                    raise RegexError(
                        f"octal escape value {escape} outside of range 0-0o377"
                    )
                return _literal(chr(code))
        raise RegexError(f"backreferences are not supported: {escape}")
    if c in _ASCIILETTERS:
        raise RegexError(f"bad escape {escape}")
    return _literal(escape[1])


def _literal(ch):
    return ("char", lambda c, ch=ch: c == ch)


def _make_set_pred(items, negate):
    lits = frozenset(v for kind, v in items if kind == "lit")
    ranges = tuple(v for kind, v in items if kind == "range")
    cats = tuple(v for kind, v in items if kind == "cat")

    def contains(c):
        if c in lits:
            return True
        o = ord(c)
        for lo, hi in ranges:
            if lo <= o <= hi:
                return True
        for pred in cats:
            if pred(c):
                return True
        return False

    if negate:
        return lambda c: not contains(c)
    return contains


class _Parser:
    def __init__(self, pattern):
        self.source = _Source(pattern)
        self.ngroups = 0
        self.open_depth = 0

    def parse(self):
        node = self.parse_alt()
        if self.source.next is not None:
            # Only an unmatched ")" can stop the top-level parse early.
            raise RegexError("unbalanced parenthesis")
        return node

    def parse_alt(self):
        branches = [self.parse_seq()]
        while self.source.match("|"):
            branches.append(self.parse_seq())
        if len(branches) == 1:
            return branches[0]
        return ("alt", branches)

    def parse_seq(self):
        source = self.source
        items = []
        while True:
            this = source.next
            if this is None or this == "|" or this == ")":
                break
            source.get()
            if this[0] == "\\":
                items.append(_escape(source, this))
            elif this == "[":
                items.append(self.parse_set())
            elif this == "(":
                items.append(self.parse_group())
            elif this == ".":
                items.append(("char", _dot))
            elif this == "^":
                items.append(("bol",))
            elif this == "$":
                items.append(("eol",))
            elif this in "*+?{":
                self.parse_repeat(this, items)
            else:
                items.append(_literal(this))
        if len(items) == 1:
            return items[0]
        return ("seq", items)

    def parse_repeat(self, this, items):
        source = self.source
        if this == "?":
            lo, hi = 0, 1
        elif this == "*":
            lo, hi = 0, None
        elif this == "+":
            lo, hi = 1, None
        else:  # "{"
            if source.next == "}":
                items.append(_literal(this))
                return
            here = source.tell()
            lo_s = hi_s = ""
            while source.next is not None and source.next in _DIGITS:
                lo_s += source.get()
            if source.match(","):
                while source.next is not None and source.next in _DIGITS:
                    hi_s += source.get()
            else:
                hi_s = lo_s
            if not source.match("}"):
                items.append(_literal(this))
                source.seek(here)
                return
            lo, hi = 0, None
            if lo_s:
                lo = int(lo_s)
                if lo >= MAXREPEAT:
                    raise RegexError("the repetition number is too large")
            if hi_s:
                hi = int(hi_s)
                if hi >= MAXREPEAT:
                    raise RegexError("the repetition number is too large")
                if hi < lo:
                    raise RegexError("min repeat greater than max repeat")
        if not items or items[-1][0] in ("bol", "eol"):
            raise RegexError("nothing to repeat")
        item = items[-1]
        if item[0] == "repeat":
            raise RegexError("multiple repeat")
        greedy = True
        if source.match("?"):
            greedy = False
        elif source.next == "+":
            raise RegexError("possessive quantifiers are not supported")
        items[-1] = ("repeat", item, lo, hi, greedy)

    def parse_group(self):
        source = self.source
        capture = True
        if source.match("?"):
            if not source.match(":"):
                if source.next is None:
                    raise RegexError("unexpected end of pattern")
                raise RegexError(f"unknown extension ?{source.next}")
            capture = False
        index = 0
        if capture:
            self.ngroups += 1
            index = self.ngroups
        body = self.parse_alt()
        if not source.match(")"):
            raise RegexError("missing ), unterminated subpattern")
        if capture:
            return ("group", index, body)
        # Wrap so that a quantifier after "(?:a*)" is not a "multiple repeat".
        return ("seq", [body])

    def parse_set(self):
        source = self.source
        items = []
        negate = source.match("^")
        while True:
            this = source.get()
            if this is None:
                raise RegexError("unterminated character set")
            if this == "]" and items:
                break
            if this[0] == "\\":
                code1 = _class_escape(source, this)
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
                    code2 = _class_escape(source, that)
                else:
                    code2 = ("lit", that)
                if code1[0] != "lit" or code2[0] != "lit":
                    raise RegexError(f"bad character range {this}-{that}")
                lo = ord(code1[1])
                hi = ord(code2[1])
                if hi < lo:
                    raise RegexError(f"bad character range {this}-{that}")
                items.append(("range", (lo, hi)))
            else:
                items.append(code1)
        return ("char", _make_set_pred(items, negate))


def parse(pattern):
    """Parse ``pattern``; return ``(ast, number_of_groups)``."""
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a str")
    parser = _Parser(pattern)
    ast = parser.parse()
    return ast, parser.ngroups
