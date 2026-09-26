"""AST node definitions."""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------- expressions


class Expr:
    __slots__ = ()


@dataclass(slots=True)
class Literal(Expr):
    value: object


@dataclass(slots=True)
class Column(Expr):
    table: str | None
    name: str


@dataclass(slots=True)
class Unary(Expr):
    op: str  # '-', '+', '~', 'NOT'
    operand: Expr


@dataclass(slots=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(slots=True)
class InList(Expr):
    operand: Expr
    items: list[Expr]
    negated: bool


@dataclass(slots=True)
class Between(Expr):
    operand: Expr
    low: Expr
    high: Expr
    negated: bool


@dataclass(slots=True)
class Like(Expr):
    operand: Expr
    pattern: Expr
    escape: Expr | None
    negated: bool


@dataclass(slots=True)
class Func(Expr):
    name: str  # upper-case
    args: list[Expr]
    distinct: bool = False
    star: bool = False


@dataclass(slots=True)
class Case(Expr):
    operand: Expr | None
    whens: list[tuple[Expr, Expr]]
    else_: Expr | None


@dataclass(slots=True)
class Cast(Expr):
    operand: Expr
    type_name: str


# ---------------------------------------------------------------- statements


@dataclass(slots=True)
class Star:
    table: str | None


@dataclass(slots=True)
class SelectItem:
    expr: Expr | Star
    alias: str | None


@dataclass(slots=True)
class TableRef:
    name: str
    alias: str | None


@dataclass(slots=True)
class Join:
    kind: str  # 'INNER', 'LEFT', 'CROSS'
    table: TableRef
    on: Expr | None


@dataclass(slots=True)
class OrderTerm:
    expr: Expr
    desc: bool
    nulls_first: bool | None = None


@dataclass(slots=True)
class Select:
    distinct: bool
    items: list[SelectItem]
    from_: TableRef | None
    joins: list[Join] = field(default_factory=list)
    where: Expr | None = None
    group_by: list[Expr] = field(default_factory=list)
    having: Expr | None = None
    order_by: list[OrderTerm] = field(default_factory=list)
    limit: Expr | None = None
    offset: Expr | None = None


@dataclass(slots=True)
class ColumnDef:
    name: str
    type_name: str


@dataclass(slots=True)
class CreateTable:
    name: str
    columns: list[ColumnDef]
    if_not_exists: bool


@dataclass(slots=True)
class DropTable:
    name: str
    if_exists: bool


@dataclass(slots=True)
class Insert:
    table: str
    columns: list[str] | None
    rows: list[list[Expr]] | None
    select: Select | None


@dataclass(slots=True)
class Update:
    table: str
    assignments: list[tuple[str, Expr]]
    where: Expr | None


@dataclass(slots=True)
class Delete:
    table: str
    where: Expr | None
