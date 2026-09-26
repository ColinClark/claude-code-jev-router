"""AST node types produced by the parser."""

from __future__ import annotations

from dataclasses import dataclass

# Character class categories (ASCII semantics).
DIGITS = frozenset("0123456789")
WORD = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
SPACE = frozenset(" \t\n\r\f\v")

CATEGORIES: dict[str, tuple[frozenset[str], bool]] = {
    # letter -> (member set, negated)
    "d": (DIGITS, False),
    "D": (DIGITS, True),
    "w": (WORD, False),
    "W": (WORD, True),
    "s": (SPACE, False),
    "S": (SPACE, True),
}


class Node:
    """Base class for all AST nodes."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class Char(Node):
    """A single literal character."""

    ch: str


@dataclass(frozen=True, slots=True)
class Any(Node):
    """``.``: any character except newline."""


@dataclass(frozen=True, slots=True)
class CharSet(Node):
    """A character set ``[...]`` or a class escape such as ``\\d``.

    ``chars`` holds single literal members, ``ranges`` inclusive (lo, hi) pairs and
    ``categories`` class letters from :data:`CATEGORIES`.
    """

    chars: frozenset[str]
    ranges: tuple[tuple[str, str], ...]
    categories: tuple[str, ...]
    negated: bool

    def contains(self, ch: str) -> bool:
        found = ch in self.chars
        if not found:
            for lo, hi in self.ranges:
                if lo <= ch <= hi:
                    found = True
                    break
        if not found:
            for cat in self.categories:
                members, neg = CATEGORIES[cat]
                if (ch in members) != neg:
                    found = True
                    break
        return found != self.negated


@dataclass(frozen=True, slots=True)
class Bol(Node):
    """``^``: start of string."""


@dataclass(frozen=True, slots=True)
class Eol(Node):
    """``$``: end of string, or just before a final newline."""


@dataclass(frozen=True, slots=True)
class Seq(Node):
    """Concatenation of nodes."""

    items: tuple[Node, ...]


@dataclass(frozen=True, slots=True)
class Alt(Node):
    """Alternation, tried left to right."""

    branches: tuple[Node, ...]


@dataclass(frozen=True, slots=True)
class Group(Node):
    """Capturing group number ``index`` (1-based)."""

    index: int
    body: Node


@dataclass(frozen=True, slots=True)
class Repeat(Node):
    """Quantified node. ``max`` is None for unbounded."""

    body: Node
    min: int
    max: int | None
    greedy: bool
