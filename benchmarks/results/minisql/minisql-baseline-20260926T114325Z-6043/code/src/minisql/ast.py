"""Syntax tree node definitions."""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------- expressions


class Expr:
    __slots__ = ()


@dataclass(eq=False)
class Literal(Expr):
    value: object


@dataclass(eq=False)
class Column(Expr):
    table: str | None  # lower-cased qualifier, or None
    name: str  # lower-cased column name
    # Written as "name": SQLite treats it as a string literal if no such column exists.
    fallback: str | None = None


@dataclass(eq=False)
class Unary(Expr):
    op: str  # "-", "+", "NOT"
    operand: Expr


@dataclass(eq=False)
class Binary(Expr):
    op: str  # arithmetic, comparison, "||", "AND", "OR", "IS", "IS NOT"
    left: Expr
    right: Expr


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
    escape: Expr | None
    negated: bool


@dataclass(eq=False)
class Func(Expr):
    name: str  # lower-cased
    args: list[Expr]
    distinct: bool = False
    star: bool = False


# ---------------------------------------------------------------- statements


@dataclass
class ColumnDef:
    name: str
    type_name: str
    not_null: bool = False
    primary_key: bool = False
    unique: bool = False
    default: Expr | None = None


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
class Insert:
    table: str
    columns: list[str] | None
    rows: list[list[Expr]]


@dataclass
class Update:
    table: str
    assignments: list[tuple[str, Expr]]
    where: Expr | None


@dataclass
class Delete:
    table: str
    where: Expr | None


@dataclass
class TableRef:
    name: str
    alias: str | None


@dataclass
class Join:
    kind: str  # "INNER", "LEFT", "CROSS"
    table: TableRef
    on: Expr | None


@dataclass
class StarItem:
    table: str | None


@dataclass
class ExprItem:
    expr: Expr
    alias: str | None


@dataclass
class OrderItem:
    expr: Expr
    desc: bool


@dataclass
class Select:
    distinct: bool
    items: list[StarItem | ExprItem]
    source: TableRef | None
    joins: list[Join] = field(default_factory=list)
    where: Expr | None = None
    group_by: list[Expr] = field(default_factory=list)
    having: Expr | None = None
    order_by: list[OrderItem] = field(default_factory=list)
    limit: Expr | None = None
    offset: Expr | None = None


Statement = CreateTable | DropTable | Insert | Update | Delete | Select
