"""Syntax tree node definitions produced by the parser."""

from __future__ import annotations

from dataclasses import dataclass

Value = int | float | str | None


# ---------------------------------------------------------------- expressions


@dataclass(frozen=True, slots=True)
class Literal:
    value: Value


@dataclass(frozen=True, slots=True)
class ColumnRef:
    table: str | None  # lower-cased qualifier, if any
    name: str  # lower-cased column name


@dataclass(frozen=True, slots=True)
class Unary:
    op: str  # "-", "+", "NOT"
    operand: Expr


@dataclass(frozen=True, slots=True)
class Binary:
    op: str  # arithmetic, comparison, "||", "AND", "OR", "IS", "IS NOT"
    left: Expr
    right: Expr


@dataclass(frozen=True, slots=True)
class IsNull:
    operand: Expr
    negated: bool


@dataclass(frozen=True, slots=True)
class InList:
    operand: Expr
    items: tuple[Expr, ...]
    negated: bool


@dataclass(frozen=True, slots=True)
class Between:
    operand: Expr
    low: Expr
    high: Expr
    negated: bool


@dataclass(frozen=True, slots=True)
class Like:
    operand: Expr
    pattern: Expr
    negated: bool


@dataclass(frozen=True, slots=True)
class FuncCall:
    name: str  # lower-cased
    args: tuple[Expr, ...]
    distinct: bool = False
    star: bool = False  # COUNT(*)


@dataclass(frozen=True, slots=True)
class Paren:
    """A parenthesised expression; kept so that column affinity survives ``(col)``."""

    inner: Expr


Expr = Literal | ColumnRef | Unary | Binary | IsNull | InList | Between | Like | FuncCall | Paren


# ----------------------------------------------------------------- statements


@dataclass(frozen=True, slots=True)
class ColumnDef:
    name: str
    type_name: str


@dataclass(frozen=True, slots=True)
class CreateTable:
    name: str
    columns: tuple[ColumnDef, ...]
    if_not_exists: bool = False


@dataclass(frozen=True, slots=True)
class DropTable:
    name: str
    if_exists: bool = False


@dataclass(frozen=True, slots=True)
class Insert:
    table: str
    columns: tuple[str, ...] | None
    rows: tuple[tuple[Expr, ...], ...]


@dataclass(frozen=True, slots=True)
class Update:
    table: str
    assignments: tuple[tuple[str, Expr], ...]
    where: Expr | None


@dataclass(frozen=True, slots=True)
class Delete:
    table: str
    where: Expr | None


@dataclass(frozen=True, slots=True)
class Star:
    """``*`` or ``alias.*`` in a select list."""

    table: str | None


@dataclass(frozen=True, slots=True)
class SelectItem:
    expr: Expr
    alias: str | None


@dataclass(frozen=True, slots=True)
class TableRef:
    name: str
    alias: str


@dataclass(frozen=True, slots=True)
class Join:
    kind: str  # "INNER", "LEFT", "CROSS"
    table: TableRef
    condition: Expr | None


@dataclass(frozen=True, slots=True)
class OrderItem:
    expr: Expr
    descending: bool


@dataclass(frozen=True, slots=True)
class Select:
    items: tuple[SelectItem | Star, ...]
    distinct: bool = False
    source: TableRef | None = None
    joins: tuple[Join, ...] = ()
    where: Expr | None = None
    group_by: tuple[Expr, ...] = ()
    having: Expr | None = None
    order_by: tuple[OrderItem, ...] = ()
    limit: Expr | None = None
    offset: Expr | None = None


Statement = CreateTable | DropTable | Insert | Update | Delete | Select
