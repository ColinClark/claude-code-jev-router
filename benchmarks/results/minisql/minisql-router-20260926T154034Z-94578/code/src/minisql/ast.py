"""Syntax tree node definitions."""

from __future__ import annotations

from dataclasses import dataclass, field


class Expr:
    __slots__ = ()


@dataclass(eq=False)
class Literal(Expr):
    value: object


@dataclass(eq=False)
class Column(Expr):
    table: str | None
    name: str


@dataclass(eq=False)
class Unary(Expr):
    op: str  # '-', '+', 'NOT'
    operand: Expr


@dataclass(eq=False)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(eq=False)
class IsNull(Expr):
    operand: Expr
    negated: bool


@dataclass(eq=False)
class Is(Expr):
    left: Expr
    right: Expr
    negated: bool


@dataclass(eq=False)
class InList(Expr):
    operand: Expr
    items: list[Expr]
    negated: bool


@dataclass(eq=False)
class Between(Expr):
    operand: Expr
    low: Expr
    high: Expr
    negated: bool


@dataclass(eq=False)
class Like(Expr):
    operand: Expr
    pattern: Expr
    negated: bool


@dataclass(eq=False)
class Case(Expr):
    operand: Expr | None
    whens: list[tuple[Expr, Expr]]
    default: Expr | None


@dataclass(eq=False)
class Func(Expr):
    name: str  # upper-case
    args: list[Expr]
    distinct: bool = False
    star: bool = False


@dataclass(eq=False)
class Star(Expr):
    table: str | None


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


@dataclass
class ColumnDef:
    name: str
    type_name: str


@dataclass
class CreateTable:
    name: str
    columns: list[ColumnDef]
    if_not_exists: bool = False


@dataclass
class DropTable:
    name: str
    if_exists: bool = False


@dataclass
class SelectItem:
    expr: Expr
    alias: str | None


@dataclass
class TableRef:
    name: str
    alias: str | None


@dataclass
class Join:
    kind: str  # 'INNER' or 'LEFT'
    table: TableRef
    on: Expr | None


@dataclass
class OrderItem:
    expr: Expr
    desc: bool


@dataclass
class Select:
    distinct: bool
    items: list[SelectItem]
    from_table: TableRef | None
    joins: list[Join] = field(default_factory=list)
    where: Expr | None = None
    group_by: list[Expr] = field(default_factory=list)
    having: Expr | None = None
    order_by: list[OrderItem] = field(default_factory=list)
    limit: Expr | None = None
    offset: Expr | None = None


@dataclass
class Insert:
    table: str
    columns: list[str] | None
    rows: list[list[Expr]] | None
    select: Select | None = None


@dataclass
class Update:
    table: str
    assignments: list[tuple[str, Expr]]
    where: Expr | None


@dataclass
class Delete:
    table: str
    where: Expr | None
