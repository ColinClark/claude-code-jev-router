from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------


class Expr:
    pass


@dataclass
class Literal(Expr):
    value: object  # int, float, str, or None


@dataclass
class ColumnRef(Expr):
    table: str | None  # qualifier (alias/table name), or None if unqualified
    name: str  # '*' for star


@dataclass
class UnaryOp(Expr):
    op: str  # '-' or '+'
    expr: Expr


@dataclass
class BinOp(Expr):
    op: str  # + - * / % || = == != <> < <= > >=
    left: Expr
    right: Expr


@dataclass
class And(Expr):
    left: Expr
    right: Expr


@dataclass
class Or(Expr):
    left: Expr
    right: Expr


@dataclass
class Not(Expr):
    expr: Expr


@dataclass
class IsNull(Expr):
    expr: Expr
    negated: bool


@dataclass
class InList(Expr):
    expr: Expr
    negated: bool
    values: list[Expr]


@dataclass
class Between(Expr):
    expr: Expr
    negated: bool
    low: Expr
    high: Expr


@dataclass
class Like(Expr):
    expr: Expr
    negated: bool
    pattern: Expr


@dataclass
class FuncCall(Expr):
    name: str  # lowercase function name
    distinct: bool
    star: bool  # COUNT(*)
    args: list[Expr]


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


@dataclass
class ColumnDefAst:
    name: str
    type: str  # INTEGER, REAL, TEXT


@dataclass
class CreateTable:
    name: str
    columns: list[ColumnDefAst]


@dataclass
class Insert:
    table: str
    columns: list[str] | None
    rows: list[list[Expr]]


@dataclass
class Assignment:
    column: str
    expr: Expr


@dataclass
class Update:
    table: str
    assignments: list[Assignment]
    where: Expr | None


@dataclass
class Delete:
    table: str
    where: Expr | None


@dataclass
class SelectItem:
    expr: Expr
    alias: str | None


@dataclass
class JoinClause:
    kind: str  # 'INNER' or 'LEFT'
    table: str
    alias: str | None
    on: Expr


@dataclass
class OrderTerm:
    expr: Expr
    desc: bool


@dataclass
class Select:
    distinct: bool
    select_list: list[SelectItem]
    from_table: str
    from_alias: str | None
    joins: list[JoinClause] = field(default_factory=list)
    where: Expr | None = None
    group_by: list[Expr] = field(default_factory=list)
    having: Expr | None = None
    order_by: list[OrderTerm] = field(default_factory=list)
    limit: int | None = None
    offset: int | None = None
