from __future__ import annotations

from dataclasses import dataclass, field

# ---- Expressions ----


class Expr:
    pass


@dataclass
class Literal(Expr):
    value: object  # int, float, str, or None


@dataclass
class ColumnRef(Expr):
    table: str | None
    name: str


@dataclass
class Star(Expr):
    table: str | None = None


@dataclass
class UnaryOp(Expr):
    op: str  # '-', 'NOT'
    operand: Expr


@dataclass
class BinaryOp(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class IsNull(Expr):
    operand: Expr
    negated: bool


@dataclass
class InList(Expr):
    operand: Expr
    items: list[Expr]
    negated: bool


@dataclass
class Between(Expr):
    operand: Expr
    low: Expr
    high: Expr
    negated: bool


@dataclass
class Like(Expr):
    operand: Expr
    pattern: Expr
    negated: bool


@dataclass
class FunctionCall(Expr):
    name: str
    args: list[Expr]
    distinct: bool = False


# ---- SELECT ----


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
    on: Expr


@dataclass
class OrderItem:
    expr: Expr
    desc: bool


@dataclass
class Select:
    distinct: bool
    items: list[SelectItem]
    from_table: TableRef
    joins: list[Join] = field(default_factory=list)
    where: Expr | None = None
    group_by: list[Expr] = field(default_factory=list)
    having: Expr | None = None
    order_by: list[OrderItem] = field(default_factory=list)
    limit: int | None = None
    offset: int | None = None


# ---- DDL / DML ----


@dataclass
class ColumnDef:
    name: str
    type: str  # 'INTEGER', 'REAL', 'TEXT'


@dataclass
class CreateTable:
    name: str
    columns: list[ColumnDef]


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
