"""Compile expression trees into Python closures bound to a row layout.

Name resolution happens here, before any row is read, so unknown or ambiguous
columns raise :class:`SQLError` even when a table is empty.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from . import ast
from . import values as v
from .aggregates import AGGREGATES
from .errors import SQLError
from .values import Affinity, Value


class Env:
    """Evaluation environment: the current (joined) row and computed aggregate values."""

    __slots__ = ("aggs", "key", "row")

    def __init__(
        self,
        row: tuple[Value, ...] = (),
        aggs: list[Value] | None = None,
        key: tuple[Value, ...] = (),
    ) -> None:
        self.row = row
        self.aggs = aggs if aggs is not None else []
        self.key = key  # GROUP BY key values of the current group


Evaluator = Callable[[Env], Value]


@dataclass(frozen=True, slots=True)
class Compiled:
    fn: Evaluator
    affinity: Affinity | None = None  # None: an expression without affinity


@dataclass(slots=True)
class Column:
    name: str
    affinity: Affinity


@dataclass(slots=True)
class Table:
    name: str
    columns: list[Column]
    rows: list[list[Value]] = field(default_factory=list)

    def column_index(self, name: str) -> int | None:
        for index, column in enumerate(self.columns):
            if column.name == name:
                return index
        return None


@dataclass(frozen=True, slots=True)
class Source:
    alias: str
    table: Table
    offset: int


class Scope:
    """The tables visible to an expression, laid out left to right in a combined row."""

    def __init__(self, sources: list[Source] | None = None) -> None:
        self.sources = sources or []

    @property
    def width(self) -> int:
        if not self.sources:
            return 0
        last = self.sources[-1]
        return last.offset + len(last.table.columns)

    def find_source(self, alias: str) -> Source | None:
        for source in self.sources:
            if source.alias == alias:
                return source
        return None

    def resolve(self, ref: ast.ColumnRef) -> tuple[int, Affinity] | None:
        """Return (row index, affinity) or None when the column does not exist."""
        if ref.table is not None:
            source = self.find_source(ref.table)
            if source is None:
                return None
            index = source.table.column_index(ref.name)
            if index is None:
                return None
            return source.offset + index, source.table.columns[index].affinity
        matches = []
        for source in self.sources:
            index = source.table.column_index(ref.name)
            if index is not None:
                matches.append((source.offset + index, source.table.columns[index].affinity))
        if len(matches) > 1:
            raise SQLError(f"ambiguous column name: {ref.name}")
        return matches[0] if matches else None


def is_aggregate_call(expr: ast.FuncCall) -> bool:
    return expr.name in AGGREGATES and (expr.star or len(expr.args) == 1)


def contains_aggregate(expr: ast.Expr | None) -> bool:
    if expr is None:
        return False
    if isinstance(expr, ast.FuncCall):
        return is_aggregate_call(expr) or any(contains_aggregate(a) for a in expr.args)
    return any(contains_aggregate(child) for child in children(expr))


def children(expr: ast.Expr) -> tuple[ast.Expr, ...]:
    match expr:
        case ast.Unary(operand=operand) | ast.IsNull(operand=operand):
            return (operand,)
        case ast.Paren(inner=inner):
            return (inner,)
        case ast.Binary(left=left, right=right):
            return (left, right)
        case ast.InList(operand=operand, items=items):
            return (operand, *items)
        case ast.Between(operand=operand, low=low, high=high):
            return (operand, low, high)
        case ast.Like(operand=operand, pattern=pattern):
            return (operand, pattern)
        case ast.FuncCall(args=args):
            return args
    return ()


@dataclass(slots=True)
class AggregateSpec:
    name: str
    star: bool
    distinct: bool
    arg: Evaluator | None


class AggregateRegistry:
    """Collects the distinct aggregate calls of a query; each gets a slot in ``Env.aggs``."""

    def __init__(self) -> None:
        self.specs: list[AggregateSpec] = []
        self._index: dict[ast.FuncCall, int] = {}

    def register(self, call: ast.FuncCall, arg: Evaluator | None) -> int:
        if call not in self._index:
            self._index[call] = len(self.specs)
            self.specs.append(AggregateSpec(call.name, call.star, call.distinct, arg))
        return self._index[call]


def _scalar_functions() -> dict[str, tuple[int, int, Callable[..., Value]]]:
    def coalesce(*args: Value) -> Value:
        return next((a for a in args if a is not None), None)

    def nullif(a: Value, b: Value) -> Value:
        return None if v.is_op(a, b) and a is not None else a

    def typeof(a: Value) -> Value:
        if a is None:
            return "null"
        return {int: "integer", float: "real", str: "text"}[type(a)]

    def length(a: Value) -> Value:
        return None if a is None else len(v.to_text(a))  # type: ignore[arg-type]

    def lower(a: Value) -> Value:
        return None if a is None else v.to_text(a).lower()  # type: ignore[union-attr]

    def upper(a: Value) -> Value:
        return None if a is None else v.to_text(a).upper()  # type: ignore[union-attr]

    def abs_(a: Value) -> Value:
        if a is None:
            return None
        if isinstance(a, int):
            return abs(a)
        return abs(v.to_real(a))

    return {
        "coalesce": (2, 1000, coalesce),
        "ifnull": (2, 2, coalesce),
        "nullif": (2, 2, nullif),
        "typeof": (1, 1, typeof),
        "length": (1, 1, length),
        "lower": (1, 1, lower),
        "upper": (1, 1, upper),
        "abs": (1, 1, abs_),
    }


SCALAR_FUNCTIONS = _scalar_functions()


class ExprCompiler:
    """Compiles expressions for one clause of a statement.

    ``aliases`` maps result-column aliases to their expressions; they are used when a
    name does not match any table column (SQLite extension). ``aggregates`` is None in
    clauses where aggregate functions are not allowed.
    """

    def __init__(
        self,
        scope: Scope,
        *,
        aliases: dict[str, ast.Expr] | None = None,
        aggregates: AggregateRegistry | None = None,
        group_terms: list[ast.Expr] | None = None,
    ) -> None:
        self.scope = scope
        self.aliases = aliases or {}
        self.aggregates = aggregates
        # Expressions identical to a GROUP BY term read the group's key value.
        self.group_terms: dict[ast.Expr, int] = {}
        for index, term in enumerate(group_terms or []):
            term = _strip_parens(term)
            if not isinstance(term, ast.Literal):
                self.group_terms.setdefault(term, index)
        self._expanding: set[str] = set()

    def compile(self, expr: ast.Expr) -> Compiled:
        if self.group_terms:
            slot = self.group_terms.get(_strip_parens(expr))
            if slot is not None:
                affinity = self._affinity_of(expr)
                return Compiled(lambda env: env.key[slot], affinity)
        match expr:
            case ast.Literal(value=value):
                return Compiled(lambda env: value)
            case ast.Paren(inner=inner):
                return self.compile(inner)
            case ast.ColumnRef():
                return self._column(expr)
            case ast.Unary():
                return self._unary(expr)
            case ast.Binary():
                return self._binary(expr)
            case ast.IsNull(operand=operand, negated=negated):
                fn = self.compile(operand).fn
                return Compiled(lambda env: int((fn(env) is None) != negated))
            case ast.InList():
                return self._in_list(expr)
            case ast.Between():
                return self._between(expr)
            case ast.Like(operand=operand, pattern=pattern, negated=negated):
                value_fn = self.compile(operand).fn
                pattern_fn = self.compile(pattern).fn

                def like(env: Env) -> Value:
                    result = v.like(value_fn(env), pattern_fn(env))
                    return result if result is None or not negated else 1 - result

                return Compiled(like)
            case ast.FuncCall():
                return self._call(expr)
        raise SQLError(f"unsupported expression: {expr!r}")

    def _affinity_of(self, expr: ast.Expr) -> Affinity | None:
        expr = _strip_parens(expr)
        if isinstance(expr, ast.ColumnRef):
            resolved = self.scope.resolve(expr)
            if resolved is not None:
                return resolved[1]
        return None

    def fn(self, expr: ast.Expr) -> Evaluator:
        return self.compile(expr).fn

    # ------------------------------------------------------------------ nodes

    def _column(self, ref: ast.ColumnRef) -> Compiled:
        resolved = self.scope.resolve(ref)
        if resolved is not None:
            index, affinity = resolved
            return Compiled(lambda env: env.row[index], affinity)
        if ref.table is None and ref.name in self.aliases and ref.name not in self._expanding:
            self._expanding.add(ref.name)
            try:
                return self.compile(self.aliases[ref.name])
            finally:
                self._expanding.discard(ref.name)
        name = f"{ref.table}.{ref.name}" if ref.table else ref.name
        raise SQLError(f"no such column: {name}")

    def _unary(self, expr: ast.Unary) -> Compiled:
        fn = self.compile(expr.operand).fn
        if expr.op == "-":
            return Compiled(lambda env: v.negate(fn(env)))
        if expr.op == "+":
            return Compiled(fn)
        return Compiled(lambda env: v.from_bool(_not(v.truth(fn(env)))))

    def _binary(self, expr: ast.Binary) -> Compiled:
        left = self.compile(expr.left)
        right = self.compile(expr.right)
        lf, rf = left.fn, right.fn
        la, ra = left.affinity, right.affinity
        op = expr.op
        if op == "AND":
            return Compiled(lambda env: _and(lf, rf, env))
        if op == "OR":
            return Compiled(lambda env: _or(lf, rf, env))
        if op in ("+", "-", "*", "/", "%"):
            return Compiled(lambda env: v.arithmetic(op, lf(env), rf(env)))
        if op == "||":
            return Compiled(lambda env: v.concat(lf(env), rf(env)))
        if op == "IS":
            return Compiled(lambda env: v.is_op(lf(env), rf(env), la, ra))
        if op == "IS NOT":
            return Compiled(lambda env: 1 - v.is_op(lf(env), rf(env), la, ra))
        return Compiled(lambda env: v.compare_op(op, lf(env), rf(env), la, ra))

    def _in_list(self, expr: ast.InList) -> Compiled:
        operand = self.compile(expr.operand)
        items = [self.compile(item) for item in expr.items]
        negated = expr.negated

        def evaluate(env: Env) -> Value:
            if not items:
                return int(negated)
            value = operand.fn(env)
            if value is None:
                return None
            saw_null = False
            for item in items:
                # SQLite applies only the left operand's affinity for IN (list).
                result = v.compare_op("=", value, item.fn(env), operand.affinity, None)
                if result is None:
                    saw_null = True
                elif result:
                    return int(not negated)
            return None if saw_null else int(negated)

        return Compiled(evaluate)

    def _between(self, expr: ast.Between) -> Compiled:
        operand = self.compile(expr.operand)
        low = self.compile(expr.low)
        high = self.compile(expr.high)
        negated = expr.negated

        def evaluate(env: Env) -> Value:
            value = operand.fn(env)
            ge = v.compare_op(">=", value, low.fn(env), operand.affinity, low.affinity)
            le = v.compare_op("<=", value, high.fn(env), operand.affinity, high.affinity)
            result = _and3(v.truth(ge), v.truth(le))
            return v.from_bool(_not(result) if negated else result)

        return Compiled(evaluate)

    def _call(self, call: ast.FuncCall) -> Compiled:
        if call.name in AGGREGATES:
            if not is_aggregate_call(call):
                raise SQLError(f"wrong number of arguments to function {call.name}()")
            if self.aggregates is None:
                raise SQLError(f"misuse of aggregate function {call.name}()")
            arg = None
            if not call.star:
                inner = ExprCompiler(self.scope, aliases=self.aliases)
                arg = inner.fn(call.args[0])
            slot = self.aggregates.register(call, arg)
            return Compiled(lambda env: env.aggs[slot])
        if call.star:
            raise SQLError(f"wrong number of arguments to function {call.name}()")
        if call.name not in SCALAR_FUNCTIONS:
            raise SQLError(f"no such function: {call.name}")
        low, high, func = SCALAR_FUNCTIONS[call.name]
        if not low <= len(call.args) <= high or call.distinct:
            raise SQLError(f"wrong number of arguments to function {call.name}()")
        arg_fns = [self.fn(arg) for arg in call.args]
        return Compiled(lambda env: func(*(f(env) for f in arg_fns)))


def _strip_parens(expr: ast.Expr) -> ast.Expr:
    while isinstance(expr, ast.Paren):
        expr = expr.inner
    return expr


# ------------------------------------------------------------ three-valued logic


def _not(value: bool | None) -> bool | None:
    return None if value is None else not value


def _and3(a: bool | None, b: bool | None) -> bool | None:
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def _and(lf: Evaluator, rf: Evaluator, env: Env) -> Value:
    a = v.truth(lf(env))
    if a is False:
        return 0
    return v.from_bool(_and3(a, v.truth(rf(env))))


def _or(lf: Evaluator, rf: Evaluator, env: Env) -> Value:
    a = v.truth(lf(env))
    if a is True:
        return 1
    b = v.truth(rf(env))
    if b is True:
        return 1
    if a is None or b is None:
        return None
    return 0
