"""Statement execution."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from operator import itemgetter
from typing import Any

from . import ast
from .aggregates import AGGREGATES, make_accumulator
from .errors import SQLError
from .functions import SCALAR_FUNCTIONS
from .parser import parse
from .values import (
    BLOB,
    INTEGER,
    NUMERIC_AFFINITIES,
    TEXT,
    affinity_of_type,
    apply_numeric_affinity,
    apply_text_affinity,
    arith,
    coerce_for_storage,
    compare,
    like_regex,
    negate,
    sort_key,
    text_to_number_strict,
    to_text,
    truth,
)

Row = Sequence[Any]
Evaluator = Callable[[Row], Any]


@dataclass
class ColumnInfo:
    name: str
    affinity: str
    not_null: bool = False
    primary_key: bool = False
    unique: bool = False
    default: ast.Expr | None = None


@dataclass
class Table:
    name: str
    columns: list[ColumnInfo]
    rows: list[list[Any]] = field(default_factory=list)

    def column_index(self, name: str) -> int:
        for i, col in enumerate(self.columns):
            if col.name == name:
                return i
        raise SQLError(f"table {self.name} has no column named {name}")

    @property
    def rowid_column(self) -> int | None:
        """Index of an INTEGER PRIMARY KEY column, which SQLite treats as the rowid."""
        for i, col in enumerate(self.columns):
            if col.primary_key and col.affinity == INTEGER:
                return i
        return None


@dataclass
class ScopeEntry:
    table: str
    name: str
    index: int
    affinity: str


class Scope:
    def __init__(self, entries: list[ScopeEntry] | None = None):
        self.entries = entries or []

    @property
    def width(self) -> int:
        return len(self.entries)

    def tables(self) -> list[str]:
        seen: list[str] = []
        for entry in self.entries:
            if entry.table not in seen:
                seen.append(entry.table)
        return seen

    def lookup(self, table: str | None, name: str) -> list[ScopeEntry]:
        return [e for e in self.entries if e.name == name and (table is None or e.table == table)]

    def resolve(self, col: ast.Column) -> ScopeEntry:
        matches = self.lookup(col.table, col.name)
        label = f"{col.table}.{col.name}" if col.table else col.name
        if not matches:
            raise SQLError(f"no such column: {label}")
        if len(matches) > 1:
            raise SQLError(f"ambiguous column name: {label}")
        return matches[0]


# ---------------------------------------------------------------- expression compilation


def _children(expr: ast.Expr) -> list[ast.Expr]:
    match expr:
        case ast.Unary(operand=o):
            return [o]
        case ast.Binary(left=left, right=right):
            return [left, right]
        case ast.InList(operand=o, items=items):
            return [o, *items]
        case ast.Between(operand=o, low=lo, high=hi):
            return [o, lo, hi]
        case ast.Like(operand=o, pattern=p, escape=esc):
            return [o, p] if esc is None else [o, p, esc]
        case ast.Func(args=args):
            return list(args)
    return []


def is_aggregate(expr: ast.Expr) -> bool:
    if not isinstance(expr, ast.Func) or expr.name not in AGGREGATES:
        return False
    # min(a, b, ...) and max(a, b, ...) with several arguments are scalar functions.
    return not (expr.name in ("min", "max") and len(expr.args) > 1)


class AggregateSet:
    """The distinct aggregate calls of a query; identical calls share one accumulator."""

    def __init__(self, compiler: Compiler):
        self.compiler = compiler
        self.funcs: list[ast.Func] = []
        self.keys: dict[tuple, int] = {}
        self.slots: dict[int, int] = {}  # id(Func node) -> index into funcs

    def collect(self, expr: ast.Expr) -> None:
        if is_aggregate(expr):
            assert isinstance(expr, ast.Func)
            for arg in expr.args:
                if contains_aggregate(arg):
                    raise SQLError(f"misuse of aggregate function {expr.name}()")
            key = self.compiler.expr_key(expr)
            if key not in self.keys:
                self.keys[key] = len(self.funcs)
                self.funcs.append(expr)
            self.slots[id(expr)] = self.keys[key]
            return
        for child in _children(expr):
            self.collect(child)


def contains_aggregate(expr: ast.Expr) -> bool:
    if is_aggregate(expr):
        return True
    return any(contains_aggregate(c) for c in _children(expr))


def substitute_aliases(expr: ast.Expr, scope: Scope, aliases: dict[str, ast.Expr]) -> ast.Expr:
    """Replace unqualified names that are not columns but are result aliases (SQLite extension)."""
    if not aliases:
        return expr

    def walk(e: ast.Expr) -> ast.Expr:
        match e:
            case ast.Column(table=None, name=name):
                if not scope.lookup(None, name) and name in aliases:
                    return aliases[name]
                return e
            case ast.Unary(op=op, operand=o):
                return ast.Unary(op, walk(o))
            case ast.Binary(op=op, left=left, right=right):
                return ast.Binary(op, walk(left), walk(right))
            case ast.InList(operand=o, items=items, negated=neg):
                return ast.InList(walk(o), [walk(i) for i in items], neg)
            case ast.Between(operand=o, low=lo, high=hi, negated=neg):
                return ast.Between(walk(o), walk(lo), walk(hi), neg)
            case ast.Like(operand=o, pattern=p, escape=esc, negated=neg):
                return ast.Like(walk(o), walk(p), None if esc is None else walk(esc), neg)
            case ast.Func(name=name, args=args, distinct=distinct, star=star):
                return ast.Func(name, [walk(a) for a in args], distinct, star)
        return e

    return walk(expr)


def _comparison_converters(
    left_aff: str | None, right_aff: str | None
) -> tuple[Callable[[Any], Any] | None, Callable[[Any], Any] | None]:
    """Conversions applied to comparison operands (SQLite datatype3 section 4.2)."""
    left_numeric = left_aff in NUMERIC_AFFINITIES
    right_numeric = right_aff in NUMERIC_AFFINITIES
    left_none = left_aff in (None, BLOB)
    right_none = right_aff in (None, BLOB)
    if left_numeric and not right_numeric:
        return None, apply_numeric_affinity
    if right_numeric and not left_numeric:
        return apply_numeric_affinity, None
    if left_aff == TEXT and right_none:
        return None, apply_text_affinity
    if right_aff == TEXT and left_none:
        return apply_text_affinity, None
    return None, None


_COMPARATORS: dict[str, Callable[[int], bool]] = {
    "=": lambda c: c == 0,
    "!=": lambda c: c != 0,
    "<": lambda c: c < 0,
    "<=": lambda c: c <= 0,
    ">": lambda c: c > 0,
    ">=": lambda c: c >= 0,
}


def _hash_key(f: Evaluator, conv: Callable[[Any], Any] | None) -> Evaluator:
    """Evaluate a join key; None for NULL (never matches), else a key equal iff compare() == 0."""

    def key(row: Row) -> Any:
        value = f(row)
        if value is None:
            return None
        if conv:
            value = conv(value)
        return sort_key(value)

    return key


class Compiler:
    """Compiles expression trees into closures that evaluate against a flat row."""

    def __init__(self, scope: Scope, agg_slots: dict[int, int] | None = None):
        self.scope = scope
        self.agg_slots = agg_slots

    def entry(self, col: ast.Column) -> ScopeEntry | None:
        """Resolve a column; None if it is a double-quoted string literal after all."""
        if col.fallback is not None and not self.scope.lookup(None, col.name):
            return None
        return self.scope.resolve(col)

    def affinity(self, expr: ast.Expr) -> str | None:
        if isinstance(expr, ast.Column):
            entry = self.entry(expr)
            return entry.affinity if entry else None
        return None

    def expr_key(self, expr: ast.Expr) -> tuple:
        """A structural key: equal keys mean the expressions always evaluate equally."""
        match expr:
            case ast.Literal(value=v):
                return ("lit", type(v).__name__, v)
            case ast.Column():
                entry = self.entry(expr)
                return ("col", entry.index) if entry else ("lit", "str", expr.fallback)
            case ast.Func(name=name, distinct=distinct, star=star):
                args = tuple(self.expr_key(a) for a in expr.args)
                return ("func", name, distinct, star, args)
        fields = tuple(getattr(expr, f) for f in ("op", "negated") if hasattr(expr, f))
        return (type(expr).__name__, fields, tuple(self.expr_key(c) for c in _children(expr)))

    def compile(self, expr: ast.Expr) -> Evaluator:
        method = getattr(self, "_compile_" + type(expr).__name__.lower())
        return method(expr)

    def _compile_literal(self, expr: ast.Literal) -> Evaluator:
        value = expr.value
        return lambda row: value

    def _compile_column(self, expr: ast.Column) -> Evaluator:
        entry = self.entry(expr)
        if entry is None:
            value = expr.fallback
            return lambda row: value
        return itemgetter(entry.index)

    def _compile_unary(self, expr: ast.Unary) -> Evaluator:
        if expr.op == "-" and isinstance(expr.operand, ast.Literal):
            value = negate(expr.operand.value)
            return lambda row: value
        f = self.compile(expr.operand)
        if expr.op == "-":
            # SQLite evaluates non-literal negation as 0 - x (so -(0.0) is 0.0, not -0.0).
            return lambda row: arith("-", 0, f(row))
        if expr.op == "+":
            return f

        def not_(row: Row) -> Any:
            t = truth(f(row))
            return None if t is None else int(not t)

        return not_

    def _compile_binary(self, expr: ast.Binary) -> Evaluator:
        op = expr.op
        fl, fr = self.compile(expr.left), self.compile(expr.right)
        if op == "AND":

            def and_(row: Row) -> Any:
                a = truth(fl(row))
                if a is False:
                    return 0
                b = truth(fr(row))
                if b is False:
                    return 0
                return None if a is None or b is None else 1

            return and_
        if op == "OR":

            def or_(row: Row) -> Any:
                a = truth(fl(row))
                if a is True:
                    return 1
                b = truth(fr(row))
                if b is True:
                    return 1
                return None if a is None or b is None else 0

            return or_
        if op in ("+", "-", "*", "/", "%"):
            return lambda row: arith(op, fl(row), fr(row))
        if op == "||":

            def concat(row: Row) -> Any:
                a, b = fl(row), fr(row)
                if a is None or b is None:
                    return None
                return to_text(a) + to_text(b)

            return concat
        conv_l, conv_r = _comparison_converters(self.affinity(expr.left), self.affinity(expr.right))
        if op in ("IS", "IS NOT"):
            want_equal = op == "IS"

            def is_(row: Row) -> Any:
                a, b = fl(row), fr(row)
                if a is None or b is None:
                    equal = a is None and b is None
                else:
                    if conv_l:
                        a = conv_l(a)
                    if conv_r:
                        b = conv_r(b)
                    equal = compare(a, b) == 0
                return int(equal == want_equal)

            return is_
        test = _COMPARATORS[op]

        def cmp(row: Row) -> Any:
            a, b = fl(row), fr(row)
            if a is None or b is None:
                return None
            if conv_l:
                a = conv_l(a)
            if conv_r:
                b = conv_r(b)
            return int(test(compare(a, b)))

        return cmp

    def _compile_inlist(self, expr: ast.InList) -> Evaluator:
        f = self.compile(expr.operand)
        items = [self.compile(i) for i in expr.items]
        # The list values are treated as having no affinity.
        _, conv = _comparison_converters(self.affinity(expr.operand), None)
        negated = expr.negated

        def in_(row: Row) -> Any:
            x = f(row)
            if not items:
                return int(negated)
            if x is None:
                return None
            saw_null = False
            for item in items:
                v = item(row)
                if v is None:
                    saw_null = True
                    continue
                if conv:
                    v = conv(v)
                if compare(x, v) == 0:
                    return int(not negated)
            if saw_null:
                return None
            return int(negated)

        return in_

    def _compile_between(self, expr: ast.Between) -> Evaluator:
        f = self.compile(expr.operand)
        flo, fhi = self.compile(expr.low), self.compile(expr.high)
        aff = self.affinity(expr.operand)
        conv_x_lo, conv_lo = _comparison_converters(aff, self.affinity(expr.low))
        conv_x_hi, conv_hi = _comparison_converters(aff, self.affinity(expr.high))
        negated = expr.negated

        def side(x: Any, y: Any, cx: Any, cy: Any, want: Callable[[int], bool]) -> bool | None:
            if x is None or y is None:
                return None
            if cx:
                x = cx(x)
            if cy:
                y = cy(y)
            return want(compare(x, y))

        def between(row: Row) -> Any:
            x = f(row)
            a = side(x, flo(row), conv_x_lo, conv_lo, lambda c: c >= 0)
            if a is False:
                result: bool | None = False
            else:
                b = side(x, fhi(row), conv_x_hi, conv_hi, lambda c: c <= 0)
                if b is False:
                    result = False
                elif a is None or b is None:
                    result = None
                else:
                    result = True
            if result is None:
                return None
            return int(result != negated)

        return between

    def _compile_like(self, expr: ast.Like) -> Evaluator:
        f, fp = self.compile(expr.operand), self.compile(expr.pattern)
        fe = self.compile(expr.escape) if expr.escape is not None else None
        negated = expr.negated

        def like(row: Row) -> Any:
            x, p = f(row), fp(row)
            esc = None
            if fe is not None:
                e = fe(row)
                if e is None:
                    return None
                esc = to_text(e)
                if len(esc) != 1:
                    raise SQLError("ESCAPE expression must be a single character")
            if x is None or p is None:
                return None
            matched = like_regex(to_text(p), esc).fullmatch(to_text(x)) is not None
            return int(matched != negated)

        return like

    def _compile_func(self, expr: ast.Func) -> Evaluator:
        if is_aggregate(expr):
            if self.agg_slots is None or id(expr) not in self.agg_slots:
                raise SQLError(f"misuse of aggregate function {expr.name}()")
            return itemgetter(self.agg_slots[id(expr)])
        spec = SCALAR_FUNCTIONS.get(expr.name)
        if spec is None:
            raise SQLError(f"no such function: {expr.name}")
        impl, min_args, max_args = spec
        if expr.star or expr.distinct or not min_args <= len(expr.args) <= max_args:
            raise SQLError(f"wrong number of arguments to function {expr.name}()")
        arg_fs = [self.compile(a) for a in expr.args]
        return lambda row: impl(*[f(row) for f in arg_fs])


# ---------------------------------------------------------------- database


class Database:
    """An in-memory SQL database."""

    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}

    def execute(self, sql: str) -> list[tuple]:
        stmt = parse(sql)
        match stmt:
            case ast.Select():
                return self._select(stmt)
            case ast.CreateTable():
                self._create(stmt)
            case ast.DropTable():
                self._drop(stmt)
            case ast.Insert():
                self._insert(stmt)
            case ast.Update():
                self._update(stmt)
            case ast.Delete():
                self._delete(stmt)
        return []

    def _table(self, name: str) -> Table:
        table = self.tables.get(name)
        if table is None:
            raise SQLError(f"no such table: {name}")
        return table

    # ------------------------------------------------------------ DDL

    def _create(self, stmt: ast.CreateTable) -> None:
        if stmt.name in self.tables:
            if stmt.if_not_exists:
                return
            raise SQLError(f"table {stmt.name} already exists")
        columns: list[ColumnInfo] = []
        for cdef in stmt.columns:
            if any(c.name == cdef.name for c in columns):
                raise SQLError(f"duplicate column name: {cdef.name}")
            columns.append(
                ColumnInfo(
                    cdef.name,
                    affinity_of_type(cdef.type_name),
                    cdef.not_null,
                    cdef.primary_key,
                    cdef.unique,
                    cdef.default,
                )
            )
        if sum(c.primary_key for c in columns) > 1:
            raise SQLError(f"table {stmt.name} has more than one primary key")
        self.tables[stmt.name] = Table(stmt.name, columns)

    def _drop(self, stmt: ast.DropTable) -> None:
        if stmt.name not in self.tables:
            if stmt.if_exists:
                return
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[stmt.name]

    # ------------------------------------------------------------ DML

    def _insert(self, stmt: ast.Insert) -> None:
        table = self._table(stmt.table)
        if stmt.columns is None:
            targets = list(range(len(table.columns)))
        else:
            targets = [table.column_index(c) for c in stmt.columns]
        empty = Compiler(Scope())
        defaults = [
            empty.compile(c.default)(()) if c.default is not None else None for c in table.columns
        ]
        new_rows = []
        for values in stmt.rows:
            if len(values) != len(targets):
                raise SQLError(
                    f"{len(targets)} values expected but {len(values)} values were supplied"
                )
            row = list(defaults)
            for index, expr in zip(targets, values, strict=True):
                row[index] = empty.compile(expr)(())
            new_rows.append(row)
        self._store(table, table.rows, new_rows)
        table.rows.extend(new_rows)

    def _update(self, stmt: ast.Update) -> None:
        table = self._table(stmt.table)
        scope = self._table_scope(table, table.name)
        compiler = Compiler(scope)
        where = compiler.compile(stmt.where) if stmt.where is not None else None
        assignments = [
            (table.column_index(col), compiler.compile(expr)) for col, expr in stmt.assignments
        ]
        keep, changed, originals = [], [], []
        for row in table.rows:
            if where is None or truth(where(row)):
                new_row = list(row)
                for index, f in assignments:
                    new_row[index] = f(row)
                changed.append(new_row)
                originals.append(row)
            else:
                keep.append(row)
        self._store(table, keep, changed)
        for row, new_row in zip(originals, changed, strict=True):
            row[:] = new_row

    def _delete(self, stmt: ast.Delete) -> None:
        table = self._table(stmt.table)
        if stmt.where is None:
            table.rows = []
            return
        where = Compiler(self._table_scope(table, table.name)).compile(stmt.where)
        table.rows = [row for row in table.rows if not truth(where(row))]

    def _store(self, table: Table, existing: list[list[Any]], new_rows: list[list[Any]]) -> None:
        """Coerce new rows to column affinities (in place) and enforce column constraints."""
        rowid = table.rowid_column
        next_id = None
        for row in new_rows:
            for i, col in enumerate(table.columns):
                row[i] = coerce_for_storage(row[i], col.affinity)
            if rowid is not None:
                if row[rowid] is None:
                    if next_id is None:
                        ids = [r[rowid] for r in existing] + [
                            r[rowid] for r in new_rows if r[rowid] is not None
                        ]
                        next_id = max(ids, default=0) + 1
                    row[rowid] = next_id
                    next_id += 1
                elif not isinstance(row[rowid], int):
                    raise SQLError("datatype mismatch")
            for i, col in enumerate(table.columns):
                if col.not_null and row[i] is None:
                    raise SQLError(f"NOT NULL constraint failed: {table.name}.{col.name}")
        for i, col in enumerate(table.columns):
            if not (col.primary_key or col.unique):
                continue
            seen = {r[i] for r in existing if r[i] is not None}
            for row in new_rows:
                value = row[i]
                if value is None:
                    continue
                if value in seen:
                    kind = "PRIMARY KEY" if col.primary_key else "UNIQUE"
                    raise SQLError(f"{kind} constraint failed: {table.name}.{col.name}")
                seen.add(value)

    @staticmethod
    def _table_scope(table: Table, qualifier: str, offset: int = 0) -> Scope:
        return Scope(
            [
                ScopeEntry(qualifier, col.name, offset + i, col.affinity)
                for i, col in enumerate(table.columns)
            ]
        )

    # ------------------------------------------------------------ SELECT

    def _select(self, sel: ast.Select) -> list[tuple]:
        scope, rows = self._from_clause(sel)

        # Expand the select list.
        items: list[tuple[ast.Expr, str | None]] = []
        for item in sel.items:
            if isinstance(item, ast.StarItem):
                if not scope.entries:
                    raise SQLError("no tables specified")
                if item.table is not None and item.table not in scope.tables():
                    raise SQLError(f"no such table: {item.table}")
                for entry in scope.entries:
                    if item.table is None or entry.table == item.table:
                        items.append((ast.Column(entry.table, entry.name), None))
            else:
                items.append((item.expr, item.alias))
        aliases: dict[str, ast.Expr] = {}
        for expr, alias in items:
            if alias is not None and alias not in aliases:
                aliases[alias] = expr

        where = substitute_aliases(sel.where, scope, aliases) if sel.where else None
        if where is not None and contains_aggregate(where):
            raise SQLError("misuse of aggregate function in WHERE clause")

        group_by = []
        for expr in sel.group_by:
            expr = self._positional(expr, items, "GROUP BY") or substitute_aliases(
                expr, scope, aliases
            )
            if contains_aggregate(expr):
                raise SQLError("aggregate functions are not allowed in the GROUP BY clause")
            group_by.append(expr)

        having = substitute_aliases(sel.having, scope, aliases) if sel.having else None

        order_by: list[tuple[ast.Expr, bool]] = []
        for term in sel.order_by:
            expr = self._positional(term.expr, items, "ORDER BY")
            if expr is None:
                if (
                    isinstance(term.expr, ast.Column)
                    and term.expr.table is None
                    and term.expr.name in aliases
                ):
                    expr = aliases[term.expr.name]
                else:
                    expr = substitute_aliases(term.expr, scope, aliases)
            order_by.append((expr, term.desc))

        base = Compiler(scope)
        # As in SQLite, only GROUP BY or aggregates in the result columns make a query an
        # aggregate query; aggregates in HAVING or ORDER BY alone are errors.
        is_aggregate_query = bool(group_by) or any(contains_aggregate(e) for e, _ in items)
        if having is not None and not is_aggregate_query:
            raise SQLError("HAVING clause on a non-aggregate query")
        if not is_aggregate_query and any(contains_aggregate(e) for e, _ in order_by):
            raise SQLError("misuse of aggregate function in ORDER BY clause")
        # Registration order matters for bare columns (see _aggregate): SQLite analyses the
        # result columns, then ORDER BY, then HAVING.
        aggs = AggregateSet(base)
        for expr, _ in items:
            aggs.collect(expr)
        for expr, _ in order_by:
            aggs.collect(expr)
        if having is not None:
            aggs.collect(having)

        if where is not None:
            where_f = base.compile(where)
            rows = [row for row in rows if truth(where_f(row))]

        if is_aggregate_query:
            envs = self._aggregate(scope, rows, group_by, aggs.funcs)
            slots = {node: scope.width + i for node, i in aggs.slots.items()}
            compiler = Compiler(scope, slots)
            if having is not None:
                having_f = compiler.compile(having)
                envs = [env for env in envs if truth(having_f(env))]
        else:
            envs = rows
            compiler = base

        item_fs = [compiler.compile(expr) for expr, _ in items]
        order_fs = [(compiler.compile(expr), desc) for expr, desc in order_by]

        results = []
        for env in envs:
            out = tuple(f(env) for f in item_fs)
            keys = [f(env) for f, _ in order_fs]
            results.append((out, keys))

        if sel.distinct:
            seen: set[tuple] = set()
            unique = []
            for out, keys in results:
                marker = tuple(sort_key(v) for v in out)
                if marker not in seen:
                    seen.add(marker)
                    unique.append((out, keys))
            results = unique

        for i in range(len(order_fs) - 1, -1, -1):
            desc = order_fs[i][1]
            results.sort(key=lambda r, i=i: sort_key(r[1][i]), reverse=desc)

        output = [out for out, _ in results]
        return self._limit(sel, output)

    @staticmethod
    def _positional(
        expr: ast.Expr, items: list[tuple[ast.Expr, str | None]], clause: str
    ) -> ast.Expr | None:
        """Integer constants in ORDER BY / GROUP BY refer to result columns (1-based)."""
        sign = 1
        while isinstance(expr, ast.Unary) and expr.op in ("-", "+"):
            sign = -sign if expr.op == "-" else sign
            expr = expr.operand
        if isinstance(expr, ast.Literal) and isinstance(expr.value, int):
            n = sign * expr.value
            if not 1 <= n <= len(items):
                raise SQLError(f"{clause} term out of range - should be between 1 and {len(items)}")
            return items[n - 1][0]
        return None

    def _from_clause(self, sel: ast.Select) -> tuple[Scope, list[Row]]:
        if sel.source is None:
            return Scope(), [()]
        table = self._table(sel.source.name)
        scope = self._table_scope(table, sel.source.alias or table.name)
        rows: list[Row] = [tuple(r) for r in table.rows]
        for join in sel.joins:
            right = self._table(join.table.name)
            qualifier = join.table.alias or right.name
            if qualifier in scope.tables():
                raise SQLError(f"ambiguous table name: {qualifier}")
            right_scope = self._table_scope(right, qualifier, scope.width)
            scope = Scope(scope.entries + right_scope.entries)
            right_rows = [tuple(r) for r in right.rows]
            compiler = Compiler(scope)
            on = compiler.compile(join.on) if join.on is not None else None
            left_width = right_scope.entries[0].index if right_scope.entries else scope.width
            probe = self._equi_join_keys(join.on, compiler, left_width)
            buckets: dict[Any, list[Row]] | None = None
            if probe is not None:
                left_key, right_key = probe
                buckets = {}
                left_pad = (None,) * left_width
                for right_row in right_rows:
                    key = right_key(left_pad + right_row)
                    if key is not None:
                        buckets.setdefault(key, []).append(right_row)
            joined: list[Row] = []
            pad = (None,) * len(right.columns)
            for left_row in rows:
                matched = False
                if buckets is None:
                    candidates: Sequence[Row] = right_rows
                else:
                    candidates = buckets.get(left_key(left_row), ())
                for right_row in candidates:
                    combined = left_row + right_row  # type: ignore[operator]
                    if on is None or truth(on(combined)):
                        joined.append(combined)
                        matched = True
                if not matched and join.kind == "LEFT":
                    joined.append(left_row + pad)  # type: ignore[operator]
            rows = joined
        return scope, rows

    @staticmethod
    def _equi_join_keys(
        on: ast.Expr | None, compiler: Compiler, left_width: int
    ) -> tuple[Evaluator, Evaluator] | None:
        """Find a top-level `left_expr = right_expr` conjunct usable as a hash-join key.

        The keys only prune candidate rows; the full ON condition is still evaluated.
        Keys are the comparison operands after affinity conversion, so two keys are equal
        exactly when the `=` comparison is true.
        """
        conjuncts = []
        stack = [on] if on is not None else []
        while stack:
            e = stack.pop()
            if isinstance(e, ast.Binary) and e.op == "AND":
                stack += [e.left, e.right]
            else:
                conjuncts.append(e)

        def side(e: ast.Expr) -> str | None:
            refs: list[ast.Column] = []
            todo = [e]
            while todo:
                node = todo.pop()
                if isinstance(node, ast.Column):
                    refs.append(node)
                elif isinstance(node, ast.Func):
                    return None
                todo += _children(node)
            entries = [compiler.entry(c) for c in refs]
            sides = {e.index < left_width for e in entries if e is not None}
            if len(sides) != 1:  # no columns, or columns from both sides
                return None
            return "left" if sides.pop() else "right"

        for e in conjuncts:
            if not (isinstance(e, ast.Binary) and e.op == "="):
                continue
            sides = (side(e.left), side(e.right))
            if sides == ("left", "right"):
                left_expr, right_expr = e.left, e.right
            elif sides == ("right", "left"):
                left_expr, right_expr = e.right, e.left
            else:
                continue
            conv_l, conv_r = _comparison_converters(
                compiler.affinity(e.left), compiler.affinity(e.right)
            )
            if left_expr is e.right:
                conv_l, conv_r = conv_r, conv_l
            return _hash_key(compiler.compile(left_expr), conv_l), _hash_key(
                compiler.compile(right_expr), conv_r
            )
        return None

    def _aggregate(
        self, scope: Scope, rows: list[Row], group_by: list[ast.Expr], aggs: list[ast.Func]
    ) -> list[Row]:
        base = Compiler(scope)
        key_fs = [base.compile(e) for e in group_by]
        arg_fs = []
        for agg in aggs:
            arg_fs.append([base.compile(a) for a in agg.args])
        # Bare (non-aggregate) columns take their values from the first row of the group,
        # unless min()/max() are used: then from the latest row on which the last min()/max()
        # accumulator took the row's value (SQLite resets its "hit" flag before each one).
        minmax = [i for i, a in enumerate(aggs) if a.name in ("min", "max")]
        decider = minmax[-1] if minmax else None

        groups: dict[tuple, list[Any]] = {}
        for row in rows:
            key = tuple(sort_key(f(row)) for f in key_fs)
            group = groups.get(key)
            if group is None:
                group = [row, [make_accumulator(a) for a in aggs]]
                groups[key] = group
            for i, (acc, fs) in enumerate(zip(group[1], arg_fs, strict=True)):
                took_value = acc.step([f(row) for f in fs])
                if i == decider and took_value:
                    group[0] = row
        if not groups and not group_by:
            groups[()] = [(None,) * scope.width, [make_accumulator(a) for a in aggs]]
        return [tuple(rep) + tuple(acc.final() for acc in accs) for rep, accs in groups.values()]

    def _limit(self, sel: ast.Select, output: list[tuple]) -> list[tuple]:
        if sel.limit is None:
            return output
        limit = self._integer_clause(sel.limit)
        offset = self._integer_clause(sel.offset) if sel.offset is not None else 0
        offset = max(offset, 0)
        if limit < 0:
            return output[offset:]
        return output[offset : offset + limit]

    @staticmethod
    def _integer_clause(expr: ast.Expr) -> int:
        value = Compiler(Scope()).compile(expr)(())
        if isinstance(value, str):
            converted = text_to_number_strict(value)
            value = converted if converted is not None else value
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if not isinstance(value, int):
            raise SQLError("datatype mismatch")
        return value
