"""AST node definitions.

All nodes are frozen dataclasses whose child collections are tuples, so every
node is hashable and structurally comparable.  That makes it possible to use
expression nodes as dictionary keys, e.g. mapping an aggregate call such as
``COUNT(DISTINCT x)`` to its computed value for a group, or matching a GROUP BY
expression against a select-list expression.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, fields

# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------


class Expr:
    """Base class for expression nodes."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class Literal(Expr):
    value: object  # int | float | str | None


@dataclass(frozen=True, slots=True)
class ColumnRef(Expr):
    name: str
    table: str | None = None  # qualifier (table name or alias), if any


@dataclass(frozen=True, slots=True)
class UnaryOp(Expr):
    op: str  # '-', '+', '~', 'NOT'
    operand: Expr


@dataclass(frozen=True, slots=True)
class BinaryOp(Expr):
    # Arithmetic: + - * / %   Concatenation: ||   Bitwise: & | << >>
    # Comparison: = != < <= > >=  ('==' normalised to '=', '<>' to '!=')
    # Logical: AND OR   Null-safe: IS, IS NOT
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True, slots=True)
class IsNull(Expr):
    operand: Expr
    negated: bool = False  # True for IS NOT NULL / NOTNULL


@dataclass(frozen=True, slots=True)
class InList(Expr):
    operand: Expr
    items: tuple[Expr, ...]
    negated: bool = False


@dataclass(frozen=True, slots=True)
class Between(Expr):
    operand: Expr
    low: Expr
    high: Expr
    negated: bool = False


@dataclass(frozen=True, slots=True)
class Like(Expr):
    operand: Expr
    pattern: Expr
    escape: Expr | None = None
    negated: bool = False
    op: str = "LIKE"  # 'LIKE' or 'GLOB'


@dataclass(frozen=True, slots=True)
class FunctionCall(Expr):
    """Scalar or aggregate function call.

    ``COUNT(*)`` is represented with ``star=True`` and empty ``args``.
    ``name`` is normalised to upper case.
    """

    name: str
    args: tuple[Expr, ...] = ()
    distinct: bool = False
    star: bool = False


@dataclass(frozen=True, slots=True)
class Case(Expr):
    operand: Expr | None  # CASE <operand> WHEN ... (simple form) or None
    whens: tuple[tuple[Expr, Expr], ...]
    else_: Expr | None = None


@dataclass(frozen=True, slots=True)
class Cast(Expr):
    operand: Expr
    type_name: str


AGGREGATE_FUNCTIONS = frozenset({"COUNT", "SUM", "AVG", "MIN", "MAX", "TOTAL", "GROUP_CONCAT"})


def is_aggregate_call(node: Expr) -> bool:
    """True if ``node`` is an aggregate function call.

    MIN/MAX with two or more arguments are scalar functions in SQLite.
    """
    if not isinstance(node, FunctionCall) or node.name not in AGGREGATE_FUNCTIONS:
        return False
    return not (node.name in ("MIN", "MAX") and len(node.args) != 1)


def iter_children(node: object) -> Iterator[Expr]:
    """Yield direct child expression nodes of an expression node."""
    if isinstance(node, Case):
        if node.operand is not None:
            yield node.operand
        for cond, result in node.whens:
            yield cond
            yield result
        if node.else_ is not None:
            yield node.else_
        return
    for f in fields(node):  # type: ignore[arg-type]
        value = getattr(node, f.name)
        if isinstance(value, Expr):
            yield value
        elif isinstance(value, tuple):
            for item in value:
                if isinstance(item, Expr):
                    yield item


def walk(node: Expr) -> Iterator[Expr]:
    """Pre-order traversal of an expression tree."""
    yield node
    for child in iter_children(node):
        yield from walk(child)


def find_aggregates(node: Expr) -> list[FunctionCall]:
    """Return the outermost aggregate calls in ``node`` (does not descend into them)."""
    found: list[FunctionCall] = []

    def visit(n: Expr) -> None:
        if is_aggregate_call(n):
            found.append(n)  # type: ignore[arg-type]
            return
        for child in iter_children(n):
            visit(child)

    visit(node)
    return found


def contains_aggregate(node: Expr) -> bool:
    return bool(find_aggregates(node))


# ---------------------------------------------------------------------------
# SELECT components
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StarItem:
    """``*`` (table is None) or ``alias.*``."""

    table: str | None = None


@dataclass(frozen=True, slots=True)
class ExprItem:
    expr: Expr
    alias: str | None = None


SelectItem = StarItem | ExprItem


@dataclass(frozen=True, slots=True)
class TableRef:
    name: str
    alias: str | None = None

    @property
    def ref_name(self) -> str:
        """Name used to qualify columns of this table in expressions."""
        return self.alias if self.alias is not None else self.name


@dataclass(frozen=True, slots=True)
class Join:
    kind: str  # 'INNER', 'LEFT' or 'CROSS' (comma joins are 'CROSS')
    table: TableRef
    on: Expr | None = None


@dataclass(frozen=True, slots=True)
class OrderItem:
    expr: Expr
    descending: bool = False


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


class Statement:
    __slots__ = ()


@dataclass(frozen=True, slots=True)
class Select(Statement):
    columns: tuple[SelectItem, ...]
    from_table: TableRef | None = None
    joins: tuple[Join, ...] = ()
    where: Expr | None = None
    group_by: tuple[Expr, ...] = ()
    having: Expr | None = None
    order_by: tuple[OrderItem, ...] = ()
    limit: Expr | None = None
    offset: Expr | None = None
    distinct: bool = False


@dataclass(frozen=True, slots=True)
class ColumnDef:
    name: str
    type_name: str  # as written, e.g. 'INTEGER', 'TEXT', 'VARCHAR(10)', or ''


@dataclass(frozen=True, slots=True)
class CreateTable(Statement):
    name: str
    columns: tuple[ColumnDef, ...]
    if_not_exists: bool = False


@dataclass(frozen=True, slots=True)
class DropTable(Statement):
    name: str
    if_exists: bool = False


@dataclass(frozen=True, slots=True)
class Insert(Statement):
    table: str
    columns: tuple[str, ...] | None  # None -> all columns in table order
    rows: tuple[tuple[Expr, ...], ...]


@dataclass(frozen=True, slots=True)
class Update(Statement):
    table: str
    assignments: tuple[tuple[str, Expr], ...]
    where: Expr | None = None


@dataclass(frozen=True, slots=True)
class Delete(Statement):
    table: str
    where: Expr | None = None
