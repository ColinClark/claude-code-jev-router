"""Syntax tree nodes produced by the parser."""

from dataclasses import dataclass, field

# ---------------------------------------------------------------- expressions


@dataclass(eq=False)
class Expr:
    pass


@dataclass(eq=False)
class Literal(Expr):
    value: object


@dataclass(eq=False)
class Column(Expr):
    table: str | None  # lower-cased qualifier, if any
    name: str  # lower-cased column name


@dataclass(eq=False)
class Unary(Expr):
    op: str  # "-", "+", "NOT"
    operand: Expr


@dataclass(eq=False)
class Binary(Expr):
    op: str  # arithmetic, "||", comparisons, "AND", "OR", "IS", "IS NOT"
    left: Expr
    right: Expr


@dataclass(eq=False)
class IsNull(Expr):
    operand: Expr
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
class Func(Expr):
    name: str  # lower-cased
    args: list[Expr]
    distinct: bool = False
    star: bool = False  # COUNT(*)


@dataclass(eq=False)
class Cast(Expr):
    operand: Expr
    type_name: str  # canonical: INTEGER, REAL, TEXT, NUMERIC


# ---------------------------------------------------------------- statements


@dataclass
class ColumnDef:
    name: str
    type_name: str  # INTEGER, REAL, TEXT or NUMERIC


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
class SelectItem:
    expr: Expr | None  # None for a star item
    alias: str | None = None
    star_table: str | None = None  # "t" for "t.*"
    is_star: bool = False


@dataclass
class TableRef:
    name: str
    alias: str


@dataclass
class Join:
    kind: str  # "INNER" or "LEFT"
    table: TableRef
    on: Expr | None


@dataclass
class OrderTerm:
    expr: Expr
    descending: bool = False
    nulls_first: bool | None = None


@dataclass
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
