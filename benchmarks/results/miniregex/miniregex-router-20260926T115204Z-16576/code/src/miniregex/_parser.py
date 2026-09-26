"""Pattern parser: turns a pattern string into a small tuple-based AST.

AST node shapes (all plain tuples so they compare structurally):

    ("lit", ch)
    ("any",)
    ("set", negate, ranges, classes)   ranges: ((lo, hi), ...) classes: ("d", "W", ...)
    ("bol",)                            ^
    ("eol",)                            $
    ("cat", (node, ...))
    ("alt", (node, ...))
    ("group", index_or_None, node)
    ("repeat", min, max_or_None, lazy, node)

The parser mirrors CPython's ``sre_parse`` decisions on edge cases (which
``{`` form quantifiers, when ``]`` and ``-`` are literal inside sets, what is
"nothing to repeat" vs "multiple repeat", ...). Constructs that ``re`` accepts
but this engine does not implement raise ``RegexError`` instead of silently
misbehaving.
"""

from __future__ import annotations

from string import ascii_letters, digits

from ._errors import RegexError

# sre refuses repeat counts at or above this value.
MAXREPEAT = 4_294_967_295

_CLASS_ESCAPES = "dDwWsS"
_CONTROL_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v", "a": "\a"}
_ALNUM = ascii_letters + digits


class _Parser:
    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self.pos = 0
        self.ngroups = 0

    # -- low level -------------------------------------------------------

    def _peek(self, offset: int = 0) -> str | None:
        i = self.pos + offset
        return self.pattern[i] if i < len(self.pattern) else None

    def _get(self) -> str | None:
        ch = self._peek()
        if ch is not None:
            self.pos += 1
        return ch

    def _error(self, msg: str, pos: int | None = None) -> RegexError:
        where = self.pos if pos is None else pos
        return RegexError(f"{msg} at position {where}")

    # -- grammar ---------------------------------------------------------

    def parse(self) -> tuple:
        node = self._parse_alt()
        if self.pos < len(self.pattern):
            # The only way to stop early at top level is an unmatched ')'.
            raise self._error("unbalanced parenthesis")
        return node

    def _parse_alt(self) -> tuple:
        alternatives = [self._parse_seq()]
        while self._peek() == "|":
            self.pos += 1
            alternatives.append(self._parse_seq())
        if len(alternatives) == 1:
            return alternatives[0]
        return ("alt", tuple(alternatives))

    def _parse_seq(self) -> tuple:
        items: list[tuple] = []
        while True:
            ch = self._peek()
            if ch is None or ch == "|" or ch == ")":
                break
            if ch == "*":
                self.pos += 1
                self._apply_quantifier(items, 0, None)
            elif ch == "+":
                self.pos += 1
                self._apply_quantifier(items, 1, None)
            elif ch == "?":
                self.pos += 1
                self._apply_quantifier(items, 0, 1)
            elif ch == "{":
                bounds = self._try_brace_quantifier()
                if bounds is None:
                    # Like re: a '{' that does not form a quantifier is a literal.
                    self.pos += 1
                    items.append(("lit", "{"))
                else:
                    self._apply_quantifier(items, bounds[0], bounds[1])
            else:
                items.append(self._parse_atom())
        if len(items) == 1:
            return items[0]
        return ("cat", tuple(items))

    def _try_brace_quantifier(self) -> tuple[int, int | None] | None:
        """Parse ``{n}``, ``{n,}``, ``{,m}``, ``{n,m}``, ``{,}`` at ``self.pos``.

        Returns ``None`` (without consuming anything) when the text does not form
        a quantifier, mirroring ``sre_parse`` which then treats ``{`` literally.
        """
        start = self.pos
        text = self.pattern
        i = start + 1
        if i < len(text) and text[i] == "}":
            return None
        lo_start = i
        while i < len(text) and text[i] in digits:
            i += 1
        lo = text[lo_start:i]
        if i < len(text) and text[i] == ",":
            i += 1
            hi_start = i
            while i < len(text) and text[i] in digits:
                i += 1
            hi = text[hi_start:i]
            has_comma = True
        else:
            hi = lo
            has_comma = False
        if i >= len(text) or text[i] != "}":
            return None
        self.pos = i + 1
        mn = int(lo) if lo else 0
        if hi:
            mx: int | None = int(hi)
        else:
            mx = None if has_comma else mn
        if mn >= MAXREPEAT or (mx is not None and mx >= MAXREPEAT):
            raise self._error("the repetition number is too large", start)
        if mx is not None and mx < mn:
            raise self._error("min repeat greater than max repeat", start)
        return mn, mx

    def _apply_quantifier(self, items: list[tuple], mn: int, mx: int | None) -> None:
        here = self.pos - 1
        if not items:
            raise self._error("nothing to repeat", here)
        last = items[-1]
        if last[0] in ("bol", "eol"):
            raise self._error("nothing to repeat", here)
        if last[0] == "repeat":
            raise self._error("multiple repeat", here)
        lazy = False
        nxt = self._peek()
        if nxt == "?":
            self.pos += 1
            lazy = True
        elif nxt == "+":
            raise self._error("possessive quantifiers are not supported")
        items[-1] = ("repeat", mn, mx, lazy, last)

    def _parse_atom(self) -> tuple:
        ch = self._get()
        assert ch is not None
        if ch == "(":
            start = self.pos - 1
            if self._peek() == "?":
                if self._peek(1) == ":":
                    self.pos += 2
                    index: int | None = None
                else:
                    raise self._error("unsupported group construct", start)
            else:
                self.ngroups += 1
                index = self.ngroups
            inner = self._parse_alt()
            if self._peek() != ")":
                raise self._error("missing ), unterminated subpattern", start)
            self.pos += 1
            return ("group", index, inner)
        if ch == "[":
            return self._parse_set()
        if ch == ".":
            return ("any",)
        if ch == "^":
            return ("bol",)
        if ch == "$":
            return ("eol",)
        if ch == "\\":
            return self._parse_escape()
        return ("lit", ch)

    def _parse_escape(self) -> tuple:
        ch = self._get()
        if ch is None:
            raise self._error("bad escape (end of pattern)", self.pos - 1)
        if ch in _CLASS_ESCAPES:
            return ("set", False, (), (ch,))
        if ch in _CONTROL_ESCAPES:
            return ("lit", _CONTROL_ESCAPES[ch])
        if ch in _ALNUM:
            # Covers \b \B \A \Z, backreferences, \x.. \u.. \N{..}, octal, ...
            raise self._error(f"bad escape \\{ch}", self.pos - 2)
        return ("lit", ch)

    def _parse_set_escape(self) -> tuple:
        """Escape inside ``[...]``; returns ("lit", ch) or ("class", name)."""
        ch = self._get()
        if ch is None:
            raise self._error("bad escape (end of pattern)", self.pos - 1)
        if ch in _CLASS_ESCAPES:
            return ("class", ch)
        if ch in _CONTROL_ESCAPES:
            return ("lit", _CONTROL_ESCAPES[ch])
        if ch in _ALNUM:
            raise self._error(f"bad escape \\{ch}", self.pos - 2)
        return ("lit", ch)

    def _parse_set(self) -> tuple:
        start = self.pos - 1
        negate = False
        if self._peek() == "^":
            self.pos += 1
            negate = True
        ranges: list[tuple[str, str]] = []
        classes: list[str] = []

        def add(code: tuple) -> None:
            if code[0] == "lit":
                ranges.append((code[1], code[1]))
            else:
                classes.append(code[1])

        empty = True
        while True:
            ch = self._get()
            if ch is None:
                raise self._error("unterminated character set", start)
            if ch == "]" and not empty:
                break
            empty = False
            code1 = self._parse_set_escape() if ch == "\\" else ("lit", ch)
            if self._peek() == "-":
                self.pos += 1
                that = self._get()
                if that is None:
                    raise self._error("unterminated character set", start)
                if that == "]":
                    add(code1)
                    ranges.append(("-", "-"))
                    break
                code2 = self._parse_set_escape() if that == "\\" else ("lit", that)
                if code1[0] != "lit" or code2[0] != "lit":
                    raise self._error("bad character range", start)
                if code2[1] < code1[1]:
                    raise self._error(f"bad character range {code1[1]}-{code2[1]}", start)
                ranges.append((code1[1], code2[1]))
            else:
                add(code1)
        return ("set", negate, tuple(ranges), tuple(classes))


def parse(pattern: str) -> tuple[tuple, int]:
    """Parse ``pattern``; return ``(ast, number_of_capturing_groups)``."""
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a str")
    parser = _Parser(pattern)
    node = parser.parse()
    return node, parser.ngroups
