"""AST node definitions."""

from __future__ import annotations

from dataclasses import dataclass, field


class Expr:
    """Base class for expression nodes."""

    __slots__ = ()


@dataclass(slots=True)
class Literal(Expr):
    value: object
    int_text: str | None = None  # original text of an integer-ish literal


@dataclass(slots=True)
class Column(Expr):
    table: str | None
    name: str
    dquoted: bool = False  # written as "name" (may fall back to a string literal)


@dataclass(slots=True)
class BoundColumn(Expr):
    """A column reference already resolved to (source index, column index)."""

    source: int
    index: int
    affinity: str | None


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
    op: str  # 'LIKE' or 'GLOB'
    operand: Expr
    pattern: Expr
    escape: Expr | None
    negated: bool


@dataclass(slots=True)
class Func(Expr):
    name: str  # lower-case
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


def children(node: Expr) -> list[Expr]:
    if isinstance(node, Unary):
        return [node.operand]
    if isinstance(node, Binary):
        return [node.left, node.right]
    if isinstance(node, InList):
        return [node.operand, *node.items]
    if isinstance(node, Between):
        return [node.operand, node.low, node.high]
    if isinstance(node, Like):
        out = [node.operand, node.pattern]
        if node.escape is not None:
            out.append(node.escape)
        return out
    if isinstance(node, Func):
        return list(node.args)
    if isinstance(node, Case):
        out = [] if node.operand is None else [node.operand]
        for cond, res in node.whens:
            out.append(cond)
            out.append(res)
        if node.else_ is not None:
            out.append(node.else_)
        return out
    if isinstance(node, Cast):
        return [node.operand]
    return []


# ---------------------------------------------------------------- statements


@dataclass(slots=True)
class ColumnDef:
    name: str
    type_name: str


@dataclass(slots=True)
class CreateTable:
    name: str
    columns: list[ColumnDef]
    if_not_exists: bool = False


@dataclass(slots=True)
class DropTable:
    name: str
    if_exists: bool = False


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
class SelectItem:
    expr: Expr | None  # None for a star item
    alias: str | None = None
    star_table: str | None = None  # for "t.*"
    is_star: bool = False


@dataclass(slots=True)
class OrderTerm:
    expr: Expr
    desc: bool = False
    nulls_first: bool | None = None


@dataclass(slots=True)
class Select:
    items: list[SelectItem]
    distinct: bool = False
    from_table: TableRef | None = None
    joins: list[Join] = field(default_factory=list)
    where: Expr | None = None
    group_by: list[Expr] = field(default_factory=list)
    having: Expr | None = None
    order_by: list[OrderTerm] = field(default_factory=list)
    limit: Expr | None = None
    offset: Expr | None = None


@dataclass(slots=True)
class Insert:
    table: str
    columns: list[str] | None
    rows: list[list[Expr]] | None
    select: Select | None = None


@dataclass(slots=True)
class Update:
    table: str
    assignments: list[tuple[str, Expr]]
    where: Expr | None


@dataclass(slots=True)
class Delete:
    table: str
    where: Expr | None


Statement = CreateTable | DropTable | Insert | Update | Delete | Select
