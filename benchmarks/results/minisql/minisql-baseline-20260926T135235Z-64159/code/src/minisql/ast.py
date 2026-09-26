"""Syntax tree node types."""

from __future__ import annotations

from dataclasses import dataclass, field

# ---- expressions ----


class Expr:
    pass


@dataclass
class Literal(Expr):
    value: object


@dataclass
class Column(Expr):
    table: str | None
    name: str
    quoted: bool = False  # "name" falls back to a string literal if no such column


@dataclass
class Unary(Expr):
    op: str  # '-', '+', 'NOT'
    operand: Expr


@dataclass
class Binary(Expr):
    op: str  # arithmetic, '||', comparisons, 'AND', 'OR', 'IS', 'IS NOT'
    left: Expr
    right: Expr


@dataclass
class InList(Expr):
    expr: Expr
    items: list[Expr]
    negated: bool


@dataclass
class Between(Expr):
    expr: Expr
    low: Expr
    high: Expr
    negated: bool


@dataclass
class Like(Expr):
    expr: Expr
    pattern: Expr
    negated: bool


@dataclass
class Func(Expr):
    name: str  # upper case
    args: list[Expr]
    distinct: bool = False
    star: bool = False


@dataclass
class Case(Expr):
    base: Expr | None
    whens: list[tuple[Expr, Expr]]
    else_: Expr | None


@dataclass
class Cast(Expr):
    expr: Expr
    type_name: str


# ---- statements ----


@dataclass
class CreateTable:
    name: str
    columns: list[tuple[str, str]]
    if_not_exists: bool = False


@dataclass
class DropTable:
    name: str
    if_exists: bool = False


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
class SelectItem:
    expr: Expr | None  # None for '*' / 'alias.*'
    alias: str | None = None
    star_table: str | None = None


@dataclass
class OrderItem:
    expr: Expr
    desc: bool


@dataclass
class Select:
    items: list[SelectItem]
    distinct: bool = False
    from_: TableRef | None = None
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
