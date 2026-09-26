"""Statement execution: expression compilation, joins, grouping, ordering."""

import functools
from collections.abc import Callable
from dataclasses import dataclass

from . import ast
from . import values as V
from .errors import SQLError
from .parser import parse

AGGREGATES = frozenset({"count", "sum", "avg", "min", "max", "total"})

# A compiled expression: fn(row, aggregate_values) -> value.
Fn = Callable[[list, list | None], object]


@dataclass
class Table:
    name: str
    columns: list[ast.ColumnDef]
    rows: list[list]

    def column_index(self, name: str) -> int | None:
        for i, col in enumerate(self.columns):
            if col.name == name:
                return i
        return None


@dataclass(eq=False)
class BoundColumn(ast.Expr):
    """A column already resolved to a position in the joined row."""

    index: int
    affinity: str


@dataclass
class Source:
    alias: str
    table: Table
    offset: int


@dataclass
class AggSpec:
    name: str
    arg: Fn | None  # None for COUNT(*)
    distinct: bool


class Context:
    """Name-resolution environment for compiling expressions."""

    def __init__(self, sources=(), aggs=None, aliases=None):
        self.sources: list[Source] = list(sources)
        self.aggs: list[AggSpec] | None = aggs
        self.aliases: dict[str, ast.Expr] = aliases or {}
        self.resolving: set[str] = set()

    def without_aggs(self) -> "Context":
        ctx = Context(self.sources, None, self.aliases)
        ctx.resolving = self.resolving
        return ctx


def is_aggregate_call(expr: ast.Expr) -> bool:
    return (
        isinstance(expr, ast.Func)
        and expr.name in AGGREGATES
        and not (expr.name in ("min", "max") and len(expr.args) != 1)
    )


def contains_aggregate(expr) -> bool:
    if expr is None:
        return False
    if is_aggregate_call(expr):
        return True
    for child in _children(expr):
        if contains_aggregate(child):
            return True
    return False


def _children(expr):
    if isinstance(expr, ast.Unary):
        return [expr.operand]
    if isinstance(expr, ast.Binary):
        return [expr.left, expr.right]
    if isinstance(expr, (ast.IsNull, ast.Cast)):
        return [expr.operand]
    if isinstance(expr, ast.InList):
        return [expr.operand, *expr.items]
    if isinstance(expr, ast.Between):
        return [expr.operand, expr.low, expr.high]
    if isinstance(expr, ast.Like):
        return [expr.operand, expr.pattern]
    if isinstance(expr, ast.Func):
        return list(expr.args)
    return []


# ------------------------------------------------------------------ compiler


def compile_expr(expr: ast.Expr, ctx: Context) -> tuple[Fn, str | None]:
    """Compile an expression to a closure; also return its affinity."""
    if isinstance(expr, ast.Literal):
        value = expr.value
        return (lambda row, aggs: value), None

    if isinstance(expr, BoundColumn):
        index = expr.index
        return (lambda row, aggs: row[index]), expr.affinity

    if isinstance(expr, ast.Column):
        return _compile_column(expr, ctx)

    if isinstance(expr, ast.Unary):
        operand, aff = compile_expr(expr.operand, ctx)
        if expr.op == "-":
            return (lambda row, aggs: V.negate(operand(row, aggs))), None
        if expr.op == "+":
            return operand, aff

        def not_(row, aggs):
            t = V.truth(operand(row, aggs))
            return None if t is None else (0 if t else 1)

        return not_, None

    if isinstance(expr, ast.Binary):
        return _compile_binary(expr, ctx), None

    if isinstance(expr, ast.IsNull):
        operand, _ = compile_expr(expr.operand, ctx)
        if expr.negated:
            return (lambda row, aggs: 0 if operand(row, aggs) is None else 1), None
        return (lambda row, aggs: 1 if operand(row, aggs) is None else 0), None

    if isinstance(expr, ast.InList):
        return _compile_in(expr, ctx), None

    if isinstance(expr, ast.Between):
        return _compile_between(expr, ctx), None

    if isinstance(expr, ast.Like):
        operand, _ = compile_expr(expr.operand, ctx)
        pattern, _ = compile_expr(expr.pattern, ctx)
        negated = expr.negated

        def like(row, aggs):
            result = V.like(operand(row, aggs), pattern(row, aggs))
            if result is None or not negated:
                return result
            return 1 - result

        return like, None

    if isinstance(expr, ast.Cast):
        return _compile_cast(expr, ctx)

    if isinstance(expr, ast.Func):
        return _compile_func(expr, ctx), None

    raise SQLError(f"unsupported expression: {expr!r}")


def _compile_column(expr: ast.Column, ctx: Context) -> tuple[Fn, str | None]:
    matches = []
    if expr.table is not None:
        sources = [s for s in ctx.sources if s.alias == expr.table]
        if not sources:
            raise SQLError(f"no such column: {expr.table}.{expr.name}")
    else:
        sources = ctx.sources
    for source in sources:
        idx = source.table.column_index(expr.name)
        if idx is not None:
            matches.append((source.offset + idx, source.table.columns[idx].type_name))
    if len(matches) > 1:
        raise SQLError(f"ambiguous column name: {_display(expr)}")
    if matches:
        index, affinity = matches[0]
        return (lambda row, aggs: row[index]), affinity
    if expr.table is None and expr.name in ctx.aliases and expr.name not in ctx.resolving:
        # SQLite lets result-column aliases be used in WHERE, GROUP BY, etc.
        ctx.resolving.add(expr.name)
        try:
            return compile_expr(ctx.aliases[expr.name], ctx)
        finally:
            ctx.resolving.discard(expr.name)
    raise SQLError(f"no such column: {_display(expr)}")


def _display(expr: ast.Column) -> str:
    return f"{expr.table}.{expr.name}" if expr.table else expr.name


def _comparison(op: str) -> Callable[[int], int]:
    return {
        "=": lambda c: c == 0,
        "!=": lambda c: c != 0,
        "<": lambda c: c < 0,
        "<=": lambda c: c <= 0,
        ">": lambda c: c > 0,
        ">=": lambda c: c >= 0,
    }[op]


def _compile_binary(expr: ast.Binary, ctx: Context) -> Fn:
    op = expr.op
    left, aff_l = compile_expr(expr.left, ctx)
    right, aff_r = compile_expr(expr.right, ctx)

    if op == "AND":

        def and_(row, aggs):
            a = V.truth(left(row, aggs))
            if a is False:
                return 0
            b = V.truth(right(row, aggs))
            if b is False:
                return 0
            if a is None or b is None:
                return None
            return 1

        return and_

    if op == "OR":

        def or_(row, aggs):
            a = V.truth(left(row, aggs))
            if a is True:
                return 1
            b = V.truth(right(row, aggs))
            if b is True:
                return 1
            if a is None or b is None:
                return None
            return 0

        return or_

    if op in ("=", "!=", "<", "<=", ">", ">="):
        test = _comparison(op)

        def cmp(row, aggs):
            a, b = left(row, aggs), right(row, aggs)
            if a is None or b is None:
                return None
            a, b = V.coerce_for_compare(a, b, aff_l, aff_r)
            return 1 if test(V.compare(a, b)) else 0

        return cmp

    if op in ("IS", "IS NOT"):
        want_equal = op == "IS"

        def is_(row, aggs):
            a, b = left(row, aggs), right(row, aggs)
            if a is None or b is None:
                equal = a is None and b is None
            else:
                a, b = V.coerce_for_compare(a, b, aff_l, aff_r)
                equal = V.compare(a, b) == 0
            return 1 if equal == want_equal else 0

        return is_

    if op == "||":
        return lambda row, aggs: V.concat(left(row, aggs), right(row, aggs))

    return lambda row, aggs: V.arith(op, left(row, aggs), right(row, aggs))


def _compile_in(expr: ast.InList, ctx: Context) -> Fn:
    operand, aff = compile_expr(expr.operand, ctx)
    # Values in an IN list have no affinity ("a IN (x, y)" means "a = +x OR a = +y").
    items = [(compile_expr(item, ctx)[0], None) for item in expr.items]
    negated = expr.negated

    def in_(row, aggs):
        value = operand(row, aggs)
        if not items:
            return 1 if negated else 0
        if value is None:
            return None
        has_null = False
        for item, item_aff in items:
            candidate = item(row, aggs)
            if candidate is None:
                has_null = True
                continue
            a, b = V.coerce_for_compare(value, candidate, aff, item_aff)
            if V.compare(a, b) == 0:
                return 0 if negated else 1
        if has_null:
            return None
        return 1 if negated else 0

    return in_


def _compile_between(expr: ast.Between, ctx: Context) -> Fn:
    operand, aff = compile_expr(expr.operand, ctx)
    low, aff_low = compile_expr(expr.low, ctx)
    high, aff_high = compile_expr(expr.high, ctx)
    negated = expr.negated

    def check(value, bound, bound_aff, test):
        if bound is None:
            return None
        a, b = V.coerce_for_compare(value, bound, aff, bound_aff)
        return test(V.compare(a, b))

    def between(row, aggs):
        value = operand(row, aggs)
        if value is None:
            return None
        lo = check(value, low(row, aggs), aff_low, lambda c: c >= 0)
        hi = check(value, high(row, aggs), aff_high, lambda c: c <= 0)
        if lo is False or hi is False:
            result = False
        elif lo is None or hi is None:
            return None
        else:
            result = True
        return 1 if result != negated else 0

    return between


def _compile_cast(expr: ast.Cast, ctx: Context) -> tuple[Fn, str | None]:
    operand, _ = compile_expr(expr.operand, ctx)
    target = expr.type_name
    if target == "INTEGER":
        convert = V.to_integer
    elif target == "REAL":
        convert = V.to_real
    elif target == "TEXT":
        convert = V.to_text
    elif target == "NUMERIC":

        def convert(value):
            if isinstance(value, str):
                value = V.text_to_number(value)
            return V.apply_affinity(value, "NUMERIC")

    else:

        def convert(value):
            return value

    return (lambda row, aggs: convert(operand(row, aggs))), target


def _scalar_min_max(pick_max: bool):
    def fn(*args):
        if any(a is None for a in args):
            return None
        best = args[0]
        for a in args[1:]:
            # Like SQLite: max() keeps the first of equal values, min() takes the last.
            c = V.compare(a, best)
            if (c > 0) if pick_max else (c <= 0):
                best = a
        return best

    return fn


def _abs(value):
    if value is None:
        return None
    if isinstance(value, str):
        return abs(float(V.text_to_number(value)))
    if value == V.INT64_MIN:
        raise SQLError("integer overflow")
    return abs(value)


def _length(value):
    return None if value is None else len(V.to_text(value))


def _upper(value):
    return None if value is None else V.to_text(value).translate(_ASCII_UPPER)


def _lower(value):
    return None if value is None else V.to_text(value).translate(V._ASCII_LOWER)


_ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _typeof(value):
    if value is None:
        return "null"
    if isinstance(value, str):
        return "text"
    return "integer" if isinstance(value, int) else "real"


def _coalesce(*args):
    for a in args:
        if a is not None:
            return a
    return None


def _nullif(a, b):
    if a is not None and b is not None and V.compare(a, b) == 0:
        return None
    return a


# name -> (implementation, min args, max args or None for variadic)
SCALAR_FUNCTIONS = {
    "abs": (_abs, 1, 1),
    "length": (_length, 1, 1),
    "upper": (_upper, 1, 1),
    "lower": (_lower, 1, 1),
    "typeof": (_typeof, 1, 1),
    "coalesce": (_coalesce, 2, None),
    "ifnull": (_coalesce, 2, 2),
    "nullif": (_nullif, 2, 2),
    "min": (_scalar_min_max(False), 2, None),
    "max": (_scalar_min_max(True), 2, None),
}


def _compile_func(expr: ast.Func, ctx: Context) -> Fn:
    name = expr.name
    if is_aggregate_call(expr):
        if ctx.aggs is None:
            raise SQLError(f"misuse of aggregate function {name}()")
        if expr.star:
            if name != "count":
                raise SQLError(f"wrong number of arguments to function {name}()")
            arg = None
        else:
            if len(expr.args) != 1:
                raise SQLError(f"wrong number of arguments to function {name}()")
            arg, _ = compile_expr(expr.args[0], ctx.without_aggs())
        index = len(ctx.aggs)
        ctx.aggs.append(AggSpec(name, arg, expr.distinct))
        return lambda row, aggs: aggs[index]

    if name == "count" and not expr.args and not expr.star:
        raise SQLError("wrong number of arguments to function count()")
    if name not in SCALAR_FUNCTIONS:
        raise SQLError(f"no such function: {name}")
    impl, min_args, max_args = SCALAR_FUNCTIONS[name]
    if expr.star or expr.distinct:
        raise SQLError(f"wrong number of arguments to function {name}()")
    if len(expr.args) < min_args or (max_args is not None and len(expr.args) > max_args):
        raise SQLError(f"wrong number of arguments to function {name}()")
    args = [compile_expr(a, ctx)[0] for a in expr.args]
    return lambda row, aggs: impl(*[a(row, aggs) for a in args])


# ------------------------------------------------------------------ aggregates


class _KBNSum:
    """Replicates SQLite's sum(): exact integer sum, Kahan-Babuska-Neumaier for reals."""

    BIG = 4503599627370496  # 2**52

    def __init__(self):
        self.int_sum = 0
        self.approx = False
        self.overflow = False
        self.r_sum = 0.0
        self.r_err = 0.0

    def _step(self, r: float) -> None:
        s = self.r_sum
        t = s + r
        if abs(s) > abs(r):
            self.r_err += (s - t) + r
        else:
            self.r_err += (r - t) + s
        self.r_sum = t

    def _split(self, value: int) -> tuple[int, int] | None:
        if value <= -self.BIG or value >= self.BIG:
            rem = abs(value) % 16384
            big = value - (rem if value >= 0 else -rem)
            return big, value - big
        return None

    def _init(self, value: int) -> None:
        parts = self._split(value)
        if parts:
            self.r_sum, self.r_err = float(parts[0]), float(parts[1])
        else:
            self.r_sum, self.r_err = float(value), 0.0

    def _step_int(self, value: int) -> None:
        parts = self._split(value)
        if parts:
            self._step(float(parts[0]))
            self._step(float(parts[1]))
        else:
            self._step(float(value))

    def add(self, value) -> None:
        if isinstance(value, str):
            number = V._numeric_from_text(value)
            value = number if number is not None else float(V.text_to_number(value))
        if not self.approx:
            if isinstance(value, int):
                total = self.int_sum + value
                if V.INT64_MIN <= total <= V.INT64_MAX:
                    self.int_sum = total
                else:
                    self.overflow = True
                    self._init(self.int_sum)
                    self.approx = True
                    self._step_int(value)
            else:
                self._init(self.int_sum)
                self.approx = True
                self._step(float(value))
        elif isinstance(value, int):
            self._step_int(value)
        else:
            self.overflow = False
            self._step(float(value))

    def real(self) -> float:
        if not self.approx:
            return float(self.int_sum)
        if abs(self.r_err) == float("inf"):
            return self.r_sum
        return self.r_sum + self.r_err

    def result(self):
        if not self.approx:
            return self.int_sum
        if self.overflow:
            raise SQLError("integer overflow")
        return self.real()


def compute_aggregate(spec: AggSpec, rows: list[list]):
    """Return (value, index of the row that produced a min/max) for a group."""
    if spec.arg is None:
        return len(rows), None
    arg = spec.arg
    items = [(v, i) for i, row in enumerate(rows) if (v := arg(row, None)) is not None]
    if spec.distinct:
        seen: dict = {}
        for v, i in items:
            seen.setdefault(v, i)
        items = [(v, i) for v, i in seen.items()]
    name = spec.name
    if name == "count":
        return len(items), None
    if name in ("min", "max"):
        if not items:
            return None, None
        best, best_i = items[0]
        for v, i in items[1:]:
            c = V.compare(v, best)
            if (c > 0) if name == "max" else (c < 0):
                best, best_i = v, i
        return best, best_i
    acc = _KBNSum()
    for v, _ in items:
        acc.add(v)
    if name == "sum":
        return (acc.result() if items else None), None
    if name == "total":
        return acc.real(), None
    # avg
    return (acc.real() / len(items) if items else None), None


# ------------------------------------------------------------------ database


def _constant(expr: ast.Expr) -> object:
    fn, _ = compile_expr(expr, Context())
    return fn([], None)


class Database:
    """An in-memory SQL database."""

    def __init__(self):
        self.tables: dict[str, Table] = {}

    def execute(self, sql: str) -> list[tuple]:
        if not isinstance(sql, str):
            raise SQLError("SQL must be a string")
        try:
            stmt = parse(sql)
        except RecursionError:
            raise SQLError("expression tree is too large") from None
        handler = {
            ast.Select: self._select,
            ast.Insert: self._insert,
            ast.Update: self._update,
            ast.Delete: self._delete,
            ast.CreateTable: self._create,
            ast.DropTable: self._drop,
        }[type(stmt)]
        return handler(stmt)

    def _table(self, name: str) -> Table:
        table = self.tables.get(name)
        if table is None:
            raise SQLError(f"no such table: {name}")
        return table

    # -------------------------------------------------------------- DDL

    def _create(self, stmt: ast.CreateTable) -> list[tuple]:
        if stmt.name in self.tables:
            if stmt.if_not_exists:
                return []
            raise SQLError(f"table {stmt.name} already exists")
        names = [c.name for c in stmt.columns]
        if len(set(names)) != len(names):
            raise SQLError(f"duplicate column name in table {stmt.name}")
        self.tables[stmt.name] = Table(stmt.name, list(stmt.columns), [])
        return []

    def _drop(self, stmt: ast.DropTable) -> list[tuple]:
        if stmt.name not in self.tables:
            if stmt.if_exists:
                return []
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[stmt.name]
        return []

    # -------------------------------------------------------------- DML

    def _insert(self, stmt: ast.Insert) -> list[tuple]:
        table = self._table(stmt.table)
        if stmt.columns is None:
            positions = list(range(len(table.columns)))
        else:
            positions = []
            for name in stmt.columns:
                idx = table.column_index(name)
                if idx is None:
                    raise SQLError(f"table {table.name} has no column named {name}")
                positions.append(idx)
        new_rows = []
        for exprs in stmt.rows:
            if len(exprs) != len(positions):
                raise SQLError(
                    f"{len(exprs)} values for {len(positions)} columns"
                    if stmt.columns
                    else f"table {table.name} has {len(positions)} columns "
                    f"but {len(exprs)} values were supplied"
                )
            row = [None] * len(table.columns)
            for pos, expr in zip(positions, exprs, strict=True):
                row[pos] = V.apply_affinity(_constant(expr), table.columns[pos].type_name)
            new_rows.append(row)
        table.rows.extend(new_rows)
        return []

    def _update(self, stmt: ast.Update) -> list[tuple]:
        table = self._table(stmt.table)
        ctx = Context([Source(table.name, table, 0)])
        where = compile_expr(stmt.where, ctx)[0] if stmt.where is not None else None
        assignments = []
        for name, expr in stmt.assignments:
            idx = table.column_index(name)
            if idx is None:
                raise SQLError(f"no such column: {name}")
            assignments.append((idx, compile_expr(expr, ctx)[0]))
        updates = []
        for row in table.rows:
            if where is None or V.truth(where(row, None)):
                new_values = [(idx, fn(row, None)) for idx, fn in assignments]
                updates.append((row, new_values))
        for row, new_values in updates:
            for idx, value in new_values:
                row[idx] = V.apply_affinity(value, table.columns[idx].type_name)
        return []

    def _delete(self, stmt: ast.Delete) -> list[tuple]:
        table = self._table(stmt.table)
        if stmt.where is None:
            table.rows = []
            return []
        where = compile_expr(stmt.where, Context([Source(table.name, table, 0)]))[0]
        table.rows = [row for row in table.rows if not V.truth(where(row, None))]
        return []

    # -------------------------------------------------------------- SELECT

    def _select(self, stmt: ast.Select) -> list[tuple]:
        sources: list[Source] = []
        width = 0

        def add_source(ref: ast.TableRef) -> Source:
            nonlocal width
            table = self._table(ref.name)
            source = Source(ref.alias, table, width)
            sources.append(source)
            width += len(table.columns)
            return source

        # FROM and joins (nested loops).
        if stmt.from_table is None:
            rows: list[list] = [[]]
        else:
            first = add_source(stmt.from_table)
            rows = [list(r) for r in first.table.rows]
        for join in stmt.joins:
            source = add_source(join.table)
            on = None
            if join.on is not None:
                on = compile_expr(join.on, Context(sources))[0]
            right_rows = source.table.rows
            pad = [None] * len(source.table.columns)
            probe = _equi_join_probe(join.on, sources[:-1], source)
            index: dict[object, list[list]] = {}
            if probe is not None:
                right_key = probe[1]
                for right in right_rows:
                    key = right_key(right, None)
                    if key is not None:
                        index.setdefault(key, []).append(right)
            joined = []
            for left in rows:
                matched = False
                if probe is not None:
                    key = probe[0](left, None)
                    candidates = index.get(key, ()) if key is not None else ()
                else:
                    candidates = right_rows
                for right in candidates:
                    combined = left + right
                    if on is None or V.truth(on(combined, None)):
                        joined.append(combined)
                        matched = True
                if not matched and join.kind == "LEFT":
                    joined.append(left + pad)
            rows = joined

        # Result columns (with * expanded).
        items: list[ast.Expr] = []
        aliases: dict[str, ast.Expr] = {}
        alias_positions: dict[str, int] = {}
        for item in stmt.items:
            if item.is_star:
                if item.star_table is not None:
                    chosen = [s for s in sources if s.alias == item.star_table]
                    if not chosen:
                        raise SQLError(f"no such table: {item.star_table}")
                elif not sources:
                    raise SQLError("no tables specified")
                else:
                    chosen = sources
                for s in chosen:
                    for i, col in enumerate(s.table.columns):
                        items.append(BoundColumn(s.offset + i, col.type_name))
            else:
                if item.alias is not None and item.alias not in aliases:
                    aliases[item.alias] = item.expr
                    alias_positions[item.alias] = len(items)
                items.append(item.expr)

        is_aggregate = (
            bool(stmt.group_by)
            or stmt.having is not None
            or any(contains_aggregate(e) for e in items)
            or any(contains_aggregate(t.expr) for t in stmt.order_by)
        )

        plain_ctx = Context(sources, None, aliases)
        if stmt.where is not None:
            where = compile_expr(stmt.where, plain_ctx)[0]
            rows = [row for row in rows if V.truth(where(row, None))]

        aggs: list[AggSpec] | None = [] if is_aggregate else None
        out_ctx = Context(sources, aggs, aliases)
        item_fns = [compile_expr(e, out_ctx)[0] for e in items]

        # ORDER BY terms refer to a result column or are expressions of their own.
        order_keys: list[tuple[str, object]] = []
        for term in stmt.order_by:
            expr = term.expr
            if isinstance(expr, ast.Literal) and isinstance(expr.value, int):
                if not 1 <= expr.value <= len(items):
                    raise SQLError(
                        f"1st ORDER BY term out of range - should be between 1 and {len(items)}"
                    )
                order_keys.append(("out", expr.value - 1))
                continue
            if isinstance(expr, ast.Column) and expr.table is None:
                if expr.name in alias_positions:
                    order_keys.append(("out", alias_positions[expr.name]))
                    continue
            order_keys.append(("expr", compile_expr(expr, out_ctx)[0]))

        results: list[tuple[tuple, list]] = []

        def emit(row, agg_values):
            out = tuple(fn(row, agg_values) for fn in item_fns)
            keys = [
                out[ref] if kind == "out" else ref(row, agg_values)  # type: ignore[operator]
                for kind, ref in order_keys
            ]
            results.append((out, keys))

        if not is_aggregate:
            for row in rows:
                emit(row, None)
        else:
            group_fns = []
            for expr in stmt.group_by:
                if isinstance(expr, ast.Literal) and isinstance(expr.value, int):
                    if not 1 <= expr.value <= len(items):
                        raise SQLError(
                            f"GROUP BY term out of range - should be between 1 and {len(items)}"
                        )
                    expr = items[expr.value - 1]
                    if contains_aggregate(expr):
                        raise SQLError("aggregate functions are not allowed in the GROUP BY clause")
                group_fns.append(compile_expr(expr, plain_ctx)[0])
            having = compile_expr(stmt.having, out_ctx)[0] if stmt.having is not None else None

            if group_fns:
                groups: dict[tuple, list[list]] = {}
                for row in rows:
                    key = tuple(fn(row, None) for fn in group_fns)
                    groups.setdefault(key, []).append(row)
                group_rows = list(groups.values())
            else:
                group_rows = [rows]

            minmax = [i for i, spec in enumerate(aggs) if spec.name in ("min", "max")]
            for grp in group_rows:
                computed = [compute_aggregate(spec, grp) for spec in aggs]
                agg_values = [value for value, _ in computed]
                if not grp:
                    representative = [None] * width
                elif len(minmax) == 1 and computed[minmax[0]][1] is not None:
                    # Bare columns come from the row holding the single min()/max().
                    representative = grp[computed[minmax[0]][1]]
                else:
                    # Otherwise SQLite takes bare columns from the group's first row.
                    representative = grp[0]
                if having is not None and not V.truth(having(representative, agg_values)):
                    continue
                emit(representative, agg_values)

        if stmt.distinct:
            seen = set()
            unique = []
            for out, keys in results:
                if out not in seen:
                    seen.add(out)
                    unique.append((out, keys))
            results = unique

        if stmt.order_by:
            terms = stmt.order_by

            def cmp(a, b):
                for i, term in enumerate(terms):
                    va, vb = a[1][i], b[1][i]
                    if va is None or vb is None:
                        if va is None and vb is None:
                            continue
                        nulls_first = term.nulls_first
                        if nulls_first is None:
                            nulls_first = not term.descending
                        return (-1 if va is None else 1) * (1 if nulls_first else -1)
                    c = V.compare(va, vb)
                    if c:
                        return -c if term.descending else c
                return 0

            results.sort(key=functools.cmp_to_key(cmp))

        output = [out for out, _ in results]
        if stmt.limit is not None or stmt.offset is not None:
            offset = _limit_value(stmt.offset) if stmt.offset is not None else 0
            offset = max(offset, 0)
            limit = _limit_value(stmt.limit) if stmt.limit is not None else -1
            output = output[offset:] if limit < 0 else output[offset : offset + limit]
        return output


def _equi_join_probe(on, left_sources: list[Source], right: Source):
    """For ``ON l = r`` (possibly one conjunct of an AND), return functions computing
    the left-row and right-row hash keys, or None if a hash lookup is not safe.

    The full ON expression is still evaluated for every candidate pair; the index only
    narrows the candidates, so it is used only when Python equality of the stored values
    agrees with SQL equality (both columns numeric, or both TEXT).
    """
    conjuncts = []

    def flatten(expr):
        if isinstance(expr, ast.Binary) and expr.op == "AND":
            flatten(expr.left)
            flatten(expr.right)
        else:
            conjuncts.append(expr)

    if on is None:
        return None
    flatten(on)
    right_alone = Context([Source(right.alias, right.table, 0)])
    left_ctx = Context(left_sources)
    numeric = ("INTEGER", "REAL", "NUMERIC")
    for expr in conjuncts:
        if not (isinstance(expr, ast.Binary) and expr.op == "="):
            continue
        for a, b in ((expr.left, expr.right), (expr.right, expr.left)):
            if not (isinstance(a, ast.Column) and isinstance(b, ast.Column)):
                continue
            try:
                left_fn, left_aff = compile_expr(a, left_ctx)
                right_fn, right_aff = compile_expr(b, right_alone)
            except SQLError:
                continue
            if _resolves(a, right_alone) or _resolves(b, left_ctx):
                continue
            if (left_aff in numeric and right_aff in numeric) or left_aff == right_aff == "TEXT":
                return left_fn, right_fn
    return None


def _resolves(expr: ast.Column, ctx: Context) -> bool:
    try:
        compile_expr(expr, ctx)
    except SQLError:
        return False
    return True


def _limit_value(expr: ast.Expr) -> int:
    value = _constant(expr)
    if isinstance(value, str):
        number = V._numeric_from_text(value)
        value = number if number is not None else value
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int):
        raise SQLError("datatype mismatch")
    return value
