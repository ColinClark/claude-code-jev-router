"""AST node types produced by the parser and consumed by the matcher compiler."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Literal:
    """A literal string (one or more characters)."""

    text: str


@dataclass(frozen=True)
class AnyChar:
    """``.``: any character except ``\\n``."""


@dataclass(frozen=True)
class CharClass:
    """A character set such as ``[a-z\\d]``, ``[^x]`` or a bare ``\\d``.

    ``classes`` holds shorthand class letters (``d D w W s S``).
    ``ranges`` holds inclusive code-point ranges.
    """

    chars: frozenset[str] = frozenset()
    ranges: tuple[tuple[int, int], ...] = ()
    classes: tuple[str, ...] = ()
    negated: bool = False


@dataclass(frozen=True)
class Anchor:
    """Zero-width assertion.

    kind is one of ``"bol"`` (``^``), ``"eol"`` (``$``), ``"A"`` (``\\A``),
    ``"Z"`` (``\\Z``), ``"b"`` (``\\b``), ``"B"`` (``\\B``).
    """

    kind: str


@dataclass(frozen=True)
class Group:
    """A group. ``index`` is the 1-based capture number, or ``None`` for ``(?:...)``."""

    index: int | None
    body: Node


@dataclass(frozen=True)
class Sequence:
    """Concatenation of nodes (possibly empty)."""

    items: tuple[Node, ...]


@dataclass(frozen=True)
class Alternation:
    """``a|b|c``: branches tried left to right."""

    branches: tuple[Node, ...]


@dataclass(frozen=True)
class Repeat:
    """Quantified node. ``max`` is ``None`` for unbounded repetition."""

    body: Node
    min: int
    max: int | None
    greedy: bool = True


Node = Literal | AnyChar | CharClass | Anchor | Group | Sequence | Alternation | Repeat
