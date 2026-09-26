"""Character sets used by ``[...]`` and the class escapes."""

from __future__ import annotations


class CharSet:
    """A set of characters: literal characters, ranges and nested classes, optionally negated.

    Membership is precomputed for ASCII; other characters fall back to the definition.
    """

    __slots__ = ("chars", "ranges", "classes", "negate", "_ascii")

    def __init__(self, chars=(), ranges=(), classes=(), negate=False):
        self.chars = frozenset(chars)
        self.ranges = tuple(ranges)
        self.classes = tuple(classes)
        self.negate = negate
        self._ascii = tuple(self._compute(chr(i)) for i in range(128))

    def _compute(self, ch: str) -> bool:
        found = (
            ch in self.chars
            or any(lo <= ch <= hi for lo, hi in self.ranges)
            or any(cls.contains(ch) for cls in self.classes)
        )
        return found != self.negate

    def contains(self, ch: str) -> bool:
        code = ord(ch)
        if code < 128:
            return self._ascii[code]
        return self._compute(ch)

    __contains__ = contains


DIGIT = CharSet(ranges=[("0", "9")])
NOT_DIGIT = CharSet(ranges=[("0", "9")], negate=True)
_WORD_RANGES = [("a", "z"), ("A", "Z"), ("0", "9")]
WORD = CharSet(chars="_", ranges=_WORD_RANGES)
NOT_WORD = CharSet(chars="_", ranges=_WORD_RANGES, negate=True)
_SPACE_CHARS = " \t\n\r\f\v"
SPACE = CharSet(chars=_SPACE_CHARS)
NOT_SPACE = CharSet(chars=_SPACE_CHARS, negate=True)
