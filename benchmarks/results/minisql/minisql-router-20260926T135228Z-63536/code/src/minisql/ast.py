"""AST node definitions."""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Expressions


class Expr:
    __slots__ = ()


@dataclass(eq=False)
class Literal(Expr):
    value: object


@dataclass(eq=False)
class BoolLiteral(Literal):
    """TRUE / FALSE keyword (value 1 or 0); ``x IS TRUE`` tests truthiness."""


@dataclass(eq=False)
class ColumnRef(Expr):
    table: str | None
    name: str


@dataclass(eq=False)
class BoundColumn(Expr):
    """A column already resolved to a row index (used for * expansion)."""

    index: int
    affinity: str | None


@dataclass(eq=False)
class Unary(Expr):
    op: str  # '-', '+', '~', 'NOT'
    operand: Expr


@dataclass(eq=False)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(eq=False)
class Like(Expr):
    expr: Expr
    pattern: Expr
    escape: Expr | None
    negated: bool


@dataclass(eq=False)
class Between(Expr):
    expr: Expr
    low: Expr
    high: Expr
    negated: bool


@dataclass(eq=False)
class InList(Expr):
    expr: Expr
    items: list[Expr]
    negated: bool


@dataclass(eq=False)
class FuncCall(Expr):
    name: str
    args: list[Expr]
    distinct: bool = False
    star: bool = False


@dataclass(eq=False)
class Case(Expr):
    base: Expr | None
    whens: list[tuple[Expr, Expr]]
    else_: Expr | None


@dataclass(eq=False)
class Cast(Expr):
    expr: Expr
    type_name: str


@dataclass(eq=False)
class Star(Expr):
    table: str | None


# ---------------------------------------------------------------------------
# Statements


@dataclass
class ColumnDef:
    name: str
    type_name: str | None
    not_null: bool = False
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
class SelectItem:
    expr: Expr
    alias: str | None


@dataclass
class TableRef:
    name: str
    alias: str | None
    join: str  # 'FIRST', 'INNER', 'LEFT', 'CROSS'
    on: Expr | None = None


@dataclass
class OrderTerm:
    expr: Expr
    desc: bool


@dataclass
class Select:
    distinct: bool
    items: list[SelectItem]
    sources: list[TableRef] = field(default_factory=list)
    where: Expr | None = None
    group_by: list[Expr] = field(default_factory=list)
    having: Expr | None = None
    order_by: list[OrderTerm] = field(default_factory=list)
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
