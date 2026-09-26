"""AST node types produced by ``_parser.parse`` and consumed by ``_matcher``.

Nodes are frozen dataclasses (structural equality is used by the parser's
alternation optimisations, mirroring CPython's ``sre_parse``):

- ``Literal(ch)``                 one exact character
- ``Any()``                       ``.``: any character except ``\\n``
- ``CharSet(negated, items)``     items are ``(lo, hi)`` code-point ranges or a
                                  category letter ``"d" "D" "w" "W" "s" "S"`` (ASCII)
- ``At(kind)``                    ``"begin"`` (``^``) or ``"end"`` (``$``)
- ``Group(index, body)``          ``index`` is the 1-based group number, or ``None``
                                  for a non-capturing group
- ``Seq(items)``                  concatenation
- ``Alt(branches)``               alternation, branches tried left to right
- ``Repeat(body, min, max, greedy)``  ``max is None`` means unbounded

``Pattern`` is the parse result: the root node plus the number of capturing groups.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Literal:
    ch: str


@dataclass(frozen=True)
class Any:
    pass


@dataclass(frozen=True)
class CharSet:
    negated: bool
    items: tuple  # of (lo: int, hi: int) or category letter str


@dataclass(frozen=True)
class At:
    kind: str  # "begin" | "end"


@dataclass(frozen=True)
class Group:
    index: int | None
    body: Node


@dataclass(frozen=True)
class Seq:
    items: tuple


@dataclass(frozen=True)
class Alt:
    branches: tuple


@dataclass(frozen=True)
class Repeat:
    body: Node
    min: int
    max: int | None
    greedy: bool


Node = Literal | Any | CharSet | At | Group | Seq | Alt | Repeat


@dataclass(frozen=True)
class Pattern:
    root: Node
    groups: int
    source: str
