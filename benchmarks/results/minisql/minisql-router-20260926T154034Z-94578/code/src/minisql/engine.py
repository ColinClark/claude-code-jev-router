"""Query execution: name resolution, expression compilation and statement evaluation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from . import ast
from . import values as V
from .aggregates import AGGREGATES, Aggregate
from .errors import SQLError
from .parser import parse

Row = tuple
Fn = Callable[[Row], object]


@dataclass
class Table:
    name: str
    columns: list[str]  # names as declared
    affinities: list[str]
    rows: list[tuple]

    def column_index(self, name: str) -> int | None:
        lname = name.lower()
        for i, c in enumerate(self.columns):
            if c.lower() == lname:
                return i
        return None


@dataclass(eq=False)
class _Resolved(ast.Expr):
    """A column reference already bound to a position in the row."""

    index: int


class Scope:
    """The columns visible to an expression, laid out as one flat row."""

    def __init__(self):
        self.entries: list[tuple[str, str, str]] = []  # (qualifier, name, affinity), lower-case
        self.qualifiers: list[tuple[str, int, int]] = []  # (qualifier, start, end)
        self.names: list[str] = []  # original column names

    def add(self, qualifier: str, table: Table):
        q = qualifier.lower()
        if any(existing == q for existing, _, _ in self.qualifiers):
            raise SQLError(f"ambiguous table name: {qualifier}")
        start = len(self.entries)
        for name, aff in zip(table.columns, table.affinities, strict=True):
            self.entries.append((q, name.lower(), aff))
            self.names.append(name)
        self.qualifiers.append((q, start, len(self.entries)))

    def __len__(self):
        return len(self.entries)

    def lookup(self, table: str | None, name: str) -> int | None:
        lname = name.lower()
        ltable = table.lower() if table is not None else None
        matches = [
            i
            for i, (q, n, _) in enumerate(self.entries)
            if n == lname and (ltable is None or q == ltable)
        ]
        if len(matches) > 1:
            raise SQLError(f"ambiguous column name: {name}")
        return matches[0] if matches else None

    def star(self, table: str | None) -> list[int]:
        if table is None:
            return list(range(len(self.entries)))
        lt = table.lower()
        for q, start, end in self.qualifiers:
            if q == lt:
                return list(range(start, end))
        raise SQLError(f"no such table: {table}")


class AggSpec:
    __slots__ = ("kind", "distinct", "arg_fns")

    def __init__(self, kind: str, distinct: bool, arg_fns: list[Fn]):
        self.kind = kind
        self.distinct = distinct
        self.arg_fns = arg_fns


def _cmp_test(op: str) -> Callable[[int], bool]:
    return {
        "=": lambda c: c == 0,
        "!=": lambda c: c != 0,
        "<": lambda c: c < 0,
        "<=": lambda c: c <= 0,
        ">": lambda c: c > 0,
        ">=": lambda c: c >= 0,
    }[op]


_ARITH = {"+": V.add, "-": V.sub, "*": V.mul, "/": V.div, "%": V.mod, "||": V.concat}


class Compiler:
    """Compiles expression trees to Python closures taking a flat row tuple."""

    def __init__(
        self,
        scope: Scope,
        aliases: dict[str, ast.Expr] | None = None,
        aggs: list[AggSpec] | None = None,
        clause: str = "",
    ):
        self.scope = scope
        self.aliases = aliases or {}
        self.aggs = aggs
        self.agg_values: list = []
        self.clause = clause
        self._expanding: set[str] = set()

    def compile(self, e: ast.Expr) -> Fn:
        return self.compile_aff(e)[0]

    def compile_aff(self, e: ast.Expr) -> tuple[Fn, str | None]:
        """Compile e, returning its closure and its affinity (for comparisons)."""
        if isinstance(e, ast.Literal):
            v = e.value
            return (lambda row: v), None
        if isinstance(e, _Resolved):
            i = e.index
            return (lambda row: row[i]), self.scope.entries[i][2]
        if isinstance(e, ast.Column):
            return self._column(e)
        if isinstance(e, ast.Unary):
            f = self.compile(e.operand)
            if e.op == "-":
                return (lambda row: V.negate(f(row))), None
            if e.op == "+":
                return self.compile_aff(e.operand)
            return self._not(f), None
        if isinstance(e, ast.Binary):
            return self._binary(e), None
        if isinstance(e, ast.IsNull):
            f = self.compile(e.operand)
            if e.negated:
                return (lambda row: 0 if f(row) is None else 1), None
            return (lambda row: 1 if f(row) is None else 0), None
        if isinstance(e, ast.Is):
            return self._is(e), None
        if isinstance(e, ast.InList):
            return self._in(e), None
        if isinstance(e, ast.Between):
            return self._between(e), None
        if isinstance(e, ast.Like):
            f, p = self.compile(e.operand), self.compile(e.pattern)
            if e.negated:

                def not_like(row):
                    r = V.like(f(row), p(row))
                    return None if r is None else 1 - r

                return not_like, None
            return (lambda row: V.like(f(row), p(row))), None
        if isinstance(e, ast.Case):
            return self._case(e), None
        if isinstance(e, ast.Func):
            return self._func(e), None
        if isinstance(e, ast.Star):
            raise SQLError("syntax error near '*'")
        raise SQLError(f"unsupported expression {e!r}")  # pragma: no cover

    # -- columns --------------------------------------------------------------

    def _column(self, e: ast.Column):
        idx = self.scope.lookup(e.table, e.name)
        if idx is not None:
            return self.compile_aff(_Resolved(idx))
        key = e.name.lower()
        if e.table is None and key in self.aliases and key not in self._expanding:
            self._expanding.add(key)
            try:
                return self.compile_aff(self.aliases[key])
            finally:
                self._expanding.discard(key)
        full = f"{e.table}.{e.name}" if e.table else e.name
        raise SQLError(f"no such column: {full}")

    # -- operators ------------------------------------------------------------

    @staticmethod
    def _not(f: Fn) -> Fn:
        def fn(row):
            t = V.truth(f(row))
            return None if t is None else (0 if t else 1)

        return fn

    def _comparison(self, op: str, lf: Fn, la, rf: Fn, ra) -> Fn:
        test = _cmp_test(op)
        needs_coerce = la is not None or ra is not None

        def fn(row):
            a = lf(row)
            if a is None:
                return None
            b = rf(row)
            if b is None:
                return None
            if needs_coerce:
                a, b = V.coerce_for_comparison(a, b, la, ra)
            return 1 if test(V.compare(a, b)) else 0

        return fn

    def _binary(self, e: ast.Binary) -> Fn:
        op = e.op
        if op == "AND":
            lf, rf = self.compile(e.left), self.compile(e.right)

            def and_(row):
                a = V.truth(lf(row))
                if a is False:
                    return 0
                b = V.truth(rf(row))
                if b is False:
                    return 0
                if a is None or b is None:
                    return None
                return 1

            return and_
        if op == "OR":
            lf, rf = self.compile(e.left), self.compile(e.right)

            def or_(row):
                a = V.truth(lf(row))
                if a is True:
                    return 1
                b = V.truth(rf(row))
                if b is True:
                    return 1
                if a is None or b is None:
                    return None
                return 0

            return or_
        lf, la = self.compile_aff(e.left)
        rf, ra = self.compile_aff(e.right)
        if op in _ARITH:
            f = _ARITH[op]
            return lambda row: f(lf(row), rf(row))
        return self._comparison(op, lf, la, rf, ra)

    def _is(self, e: ast.Is) -> Fn:
        lf, la = self.compile_aff(e.left)
        rf, ra = self.compile_aff(e.right)
        neg = e.negated

        def fn(row):
            a, b = lf(row), rf(row)
            if a is None or b is None:
                same = a is None and b is None
            else:
                a, b = V.coerce_for_comparison(a, b, la, ra)
                same = V.compare(a, b) == 0
            return int(same != neg)

        return fn

    def _in(self, e: ast.InList) -> Fn:
        # Only the left operand's affinity applies to the comparisons in an IN list.
        lf, la = self.compile_aff(e.operand)
        items = [self.compile(i) for i in e.items]
        neg = e.negated

        def fn(row):
            if not items:
                return 1 if neg else 0
            a = lf(row)
            if a is None:
                return None
            a = V.apply_comparison_affinity(a, la)
            saw_null = False
            for f in items:
                b = f(row)
                if b is None:
                    saw_null = True
                    continue
                if V.compare(a, V.apply_comparison_affinity(b, la)) == 0:
                    return 0 if neg else 1
            if saw_null:
                return None
            return 1 if neg else 0

        return fn

    def _between(self, e: ast.Between) -> Fn:
        f, fa = self.compile_aff(e.operand)
        lo = self._comparison(">=", f, fa, *self.compile_aff(e.low))
        hi = self._comparison("<=", f, fa, *self.compile_aff(e.high))
        neg = e.negated

        def fn(row):
            a = lo(row)
            if a == 0:
                r = 0
            else:
                b = hi(row)
                if b == 0:
                    r = 0
                elif a is None or b is None:
                    return None
                else:
                    r = 1
            return 1 - r if neg else r

        return fn

    def _case(self, e: ast.Case) -> Fn:
        default = self.compile(e.default) if e.default is not None else (lambda row: None)
        if e.operand is not None:
            of, oa = self.compile_aff(e.operand)
            whens = [
                (self._comparison("=", of, oa, *self.compile_aff(w)), self.compile(t))
                for w, t in e.whens
            ]
        else:
            whens = [(self.compile(w), self.compile(t)) for w, t in e.whens]

        def fn(row):
            for cond, then in whens:
                if V.truth(cond(row)):
                    return then(row)
            return default(row)

        return fn

    # -- functions ------------------------------------------------------------

    def _func(self, e: ast.Func) -> Fn:
        name = e.name
        nargs = len(e.args)
        is_agg = name in AGGREGATES and not (name in ("MIN", "MAX") and nargs > 1)
        if is_agg:
            return self._aggregate(e)
        if e.star or e.distinct:
            raise SQLError(f"wrong number of arguments to function {name.lower()}()")
        args = [self.compile(a) for a in e.args]

        def check(lo: int, hi: int):
            if not lo <= nargs <= hi:
                raise SQLError(f"wrong number of arguments to function {name.lower()}()")

        if name in ("COALESCE", "IFNULL"):
            check(2, 1000 if name == "COALESCE" else 2)

            def coalesce(row):
                for f in args:
                    v = f(row)
                    if v is not None:
                        return v
                return None

            return coalesce
        if name == "NULLIF":
            check(2, 2)
            a, b = args

            def nullif(row):
                x, y = a(row), b(row)
                if x is not None and y is not None and V.compare(x, y) == 0:
                    return None
                return x

            return nullif
        if name in ("MIN", "MAX"):
            pick = min if name == "MIN" else max

            def minmax(row):
                vals = [f(row) for f in args]
                if any(v is None for v in vals):
                    return None
                return pick(vals, key=V.sort_key)

            return minmax
        if name in ("ABS", "LOWER", "UPPER", "LENGTH", "TYPEOF"):
            check(1, 1)
            f = args[0]
            impl = _SCALAR1[name]
            return lambda row: impl(f(row))
        raise SQLError(f"no such function: {name}")

    def _aggregate(self, e: ast.Func) -> Fn:
        name = e.name
        if self.aggs is None:
            where = f" in {self.clause}" if self.clause else ""
            raise SQLError(f"misuse of aggregate function {name.lower()}(){where}")
        if e.star:
            if name != "COUNT":
                raise SQLError(f"wrong number of arguments to function {name.lower()}()")
            arg_fns: list[Fn] = []
        else:
            lo, hi = (1, 2) if name == "GROUP_CONCAT" else (1, 1)
            if not lo <= len(e.args) <= hi or (e.distinct and len(e.args) != 1):
                raise SQLError(f"wrong number of arguments to function {name.lower()}()")
            inner = Compiler(self.scope, self.aliases, None, "aggregate argument")
            arg_fns = [inner.compile(a) for a in e.args]
        idx = len(self.aggs)
        self.aggs.append(AggSpec(name, e.distinct, arg_fns))
        vals = self.agg_values
        return lambda row: vals[idx]


def _abs(v):
    if v is None:
        return None
    if isinstance(v, int):
        if v == V.INT_MIN:
            raise SQLError("integer overflow")
        return abs(v)
    if isinstance(v, str):
        return abs(float(V.text_to_numeric(v)))
    return abs(v)


def _ascii_case(fn):
    def impl(v):
        if v is None:
            return None
        return "".join(fn(c) if c.isascii() else c for c in V.to_text(v))

    return impl


_SCALAR1 = {
    "ABS": _abs,
    "LOWER": _ascii_case(str.lower),
    "UPPER": _ascii_case(str.upper),
    "LENGTH": lambda v: None if v is None else len(V.to_text(v)),
    "TYPEOF": V.typeof,
}


def _contains_aggregate(e) -> bool:
    if isinstance(e, ast.Func):
        if e.name in AGGREGATES and not (e.name in ("MIN", "MAX") and len(e.args) > 1):
            return True
        return any(_contains_aggregate(a) for a in e.args)
    if isinstance(e, ast.Expr):
        for v in vars(e).values():
            if isinstance(v, ast.Expr) and _contains_aggregate(v):
                return True
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, tuple):
                        if any(_contains_aggregate(x) for x in item):
                            return True
                    elif _contains_aggregate(item):
                        return True
    return False


def _expr_key(e, scope: Scope, aliases: dict[str, ast.Expr], depth: int = 0):
    """A hashable structural key for e, with column references resolved to row positions."""
    if depth > 50:
        return None
    if isinstance(e, _Resolved):
        return ("col", e.index)
    if isinstance(e, ast.Column):
        try:
            idx = scope.lookup(e.table, e.name)
        except SQLError:
            return None
        if idx is not None:
            return ("col", idx)
        alias = aliases.get(e.name.lower()) if e.table is None else None
        return _expr_key(alias, scope, aliases, depth + 1) if alias is not None else None
    if isinstance(e, ast.Literal):
        return ("lit", type(e.value).__name__, e.value)
    if isinstance(e, ast.Expr):
        parts: list = [type(e).__name__]
        for v in vars(e).values():
            if isinstance(v, ast.Expr):
                parts.append(_expr_key(v, scope, aliases, depth + 1))
            elif isinstance(v, list):
                parts.append(tuple(_expr_key(x, scope, aliases, depth + 1) for x in v))
            elif isinstance(v, tuple):
                parts.append(tuple(_expr_key(x, scope, aliases, depth + 1) for x in v))
            else:
                parts.append(v)
        return tuple(parts)
    if e is None:
        return None
    return ("?", id(e))


def _affinity_class(affinity: str) -> str:
    return "num" if affinity in V.NUMERIC_AFFINITIES else affinity


def _equi_join_columns(on, scope: Scope, split: int) -> tuple[int, int] | None:
    """Find an ON conjunct `left_col = right_col` usable for a hash join.

    Returns (index in the left row, index in the right table row). Only columns of the same
    affinity class qualify, so that comparison equals Python equality on non-NULL values.
    """
    if on is None:
        return None
    if isinstance(on, ast.Binary) and on.op == "AND":
        return _equi_join_columns(on.left, scope, split) or _equi_join_columns(
            on.right, scope, split
        )
    if not (isinstance(on, ast.Binary) and on.op == "="):
        return None
    if not (isinstance(on.left, ast.Column) and isinstance(on.right, ast.Column)):
        return None
    try:
        a = scope.lookup(on.left.table, on.left.name)
        b = scope.lookup(on.right.table, on.right.name)
    except SQLError:
        return None
    if a is None or b is None:
        return None
    if a >= split > b:
        a, b = b, a
    if not (a < split <= b):
        return None
    if _affinity_class(scope.entries[a][2]) != _affinity_class(scope.entries[b][2]):
        return None
    return a, b - split


def _truthy_filter(f: Fn) -> Callable[[Row], bool]:
    return lambda row: V.truth(f(row)) is True


def _sort_rows(rows: list, keys_of: Callable, descs: list[bool]):
    """Stable multi-key sort using SQLite ordering (NULLs first ascending)."""
    for k in range(len(descs) - 1, -1, -1):
        rows.sort(key=lambda r, k=k: V.sort_key(keys_of(r)[k]), reverse=descs[k])


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
            raise SQLError("expression too deeply nested") from None
        if isinstance(stmt, ast.Select):
            return self._select(stmt)
        if isinstance(stmt, ast.Insert):
            self._insert(stmt)
        elif isinstance(stmt, ast.Update):
            self._update(stmt)
        elif isinstance(stmt, ast.Delete):
            self._delete(stmt)
        elif isinstance(stmt, ast.CreateTable):
            self._create(stmt)
        elif isinstance(stmt, ast.DropTable):
            self._drop(stmt)
        return []

    # -- DDL ------------------------------------------------------------------

    def _table(self, name: str) -> Table:
        t = self.tables.get(name.lower())
        if t is None:
            raise SQLError(f"no such table: {name}")
        return t

    def _create(self, stmt: ast.CreateTable):
        key = stmt.name.lower()
        if key in self.tables:
            if stmt.if_not_exists:
                return
            raise SQLError(f"table {stmt.name} already exists")
        seen = set()
        for c in stmt.columns:
            if c.name.lower() in seen:
                raise SQLError(f"duplicate column name: {c.name}")
            seen.add(c.name.lower())
        self.tables[key] = Table(
            stmt.name,
            [c.name for c in stmt.columns],
            [V.affinity_of(c.type_name) for c in stmt.columns],
            [],
        )

    def _drop(self, stmt: ast.DropTable):
        if stmt.name.lower() not in self.tables:
            if stmt.if_exists:
                return
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[stmt.name.lower()]

    # -- DML ------------------------------------------------------------------

    def _table_scope(self, table: Table) -> Scope:
        scope = Scope()
        scope.add(table.name, table)
        return scope

    def _insert(self, stmt: ast.Insert):
        table = self._table(stmt.table)
        if stmt.columns is None:
            targets = list(range(len(table.columns)))
        else:
            targets = []
            for c in stmt.columns:
                idx = table.column_index(c)
                if idx is None:
                    raise SQLError(f"table {table.name} has no column named {c}")
                targets.append(idx)
        if stmt.select is not None:
            source_rows = self._select(stmt.select)
        else:
            compiler = Compiler(Scope(), clause="VALUES")
            source_rows = []
            for exprs in stmt.rows:
                if len(exprs) != len(targets):
                    raise SQLError(f"{len(exprs)} values for {len(targets)} columns")
                source_rows.append(tuple(compiler.compile(e)(()) for e in exprs))
        new_rows = []
        for src in source_rows:
            if len(src) != len(targets):
                raise SQLError(f"{len(src)} values for {len(targets)} columns")
            row = [None] * len(table.columns)
            for idx, v in zip(targets, src, strict=True):
                row[idx] = V.apply_storage_affinity(v, table.affinities[idx])
            new_rows.append(tuple(row))
        table.rows.extend(new_rows)

    def _update(self, stmt: ast.Update):
        table = self._table(stmt.table)
        compiler = Compiler(self._table_scope(table), clause="UPDATE")
        sets = []
        for col, e in stmt.assignments:
            idx = table.column_index(col)
            if idx is None:
                raise SQLError(f"no such column: {col}")
            sets.append((idx, compiler.compile(e)))
        pred = _truthy_filter(compiler.compile(stmt.where)) if stmt.where else None
        new_rows = []
        for row in table.rows:
            if pred is None or pred(row):
                new = list(row)
                for idx, f in sets:
                    new[idx] = V.apply_storage_affinity(f(row), table.affinities[idx])
                new_rows.append(tuple(new))
            else:
                new_rows.append(row)
        table.rows = new_rows

    def _delete(self, stmt: ast.Delete):
        table = self._table(stmt.table)
        if stmt.where is None:
            table.rows = []
            return
        compiler = Compiler(self._table_scope(table), clause="WHERE")
        pred = _truthy_filter(compiler.compile(stmt.where))
        table.rows = [r for r in table.rows if not pred(r)]

    # -- SELECT ---------------------------------------------------------------

    def _from_rows(self, sel: ast.Select, scope: Scope) -> list[Row]:
        if sel.from_table is None:
            return [()]
        base = self._table(sel.from_table.name)
        scope.add(sel.from_table.alias or base.name, base)
        rows: list[Row] = list(base.rows)
        for join in sel.joins:
            right = self._table(join.table.name)
            scope.add(join.table.alias or right.name, right)
            on = None
            if join.on is not None:
                on = _truthy_filter(Compiler(scope, clause="ON").compile(join.on))
            null_right = (None,) * len(right.columns)
            probe = _equi_join_columns(join.on, scope, len(scope) - len(right.columns))
            index: dict | None = None
            if probe is not None:
                index = {}
                for r in right.rows:
                    v = r[probe[1]]
                    if v is not None:
                        index.setdefault(v, []).append(r)
            out = []
            for left in rows:
                matched = False
                if index is None:
                    candidates = right.rows
                else:
                    v = left[probe[0]]
                    candidates = index.get(v, ()) if v is not None else ()
                for r in candidates:
                    combined = left + r
                    if on is None or on(combined):
                        out.append(combined)
                        matched = True
                if not matched and join.kind == "LEFT":
                    out.append(left + null_right)
            rows = out
        return rows

    def _constant(self, e: ast.Expr, what: str) -> int:
        v = Compiler(Scope(), clause=what).compile(e)(())
        v = V.apply_numeric_affinity(v)
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if not isinstance(v, int):
            raise SQLError("datatype mismatch")
        return v

    def _select(self, sel: ast.Select) -> list[tuple]:
        scope = Scope()
        rows = self._from_rows(sel, scope)

        # Expand the select list.
        items: list[tuple[ast.Expr, str | None]] = []
        for item in sel.items:
            if isinstance(item.expr, ast.Star):
                if sel.from_table is None:
                    raise SQLError("no tables specified")
                items.extend((_Resolved(i), None) for i in scope.star(item.expr.table))
            else:
                items.append((item.expr, item.alias))
        aliases = {alias.lower(): e for e, alias in items if alias is not None}

        if sel.where is not None:
            where = Compiler(scope, aliases, clause="WHERE").compile(sel.where)
            rows = [r for r in rows if V.truth(where(r)) is True]

        group_exprs: list[ast.Expr] = []
        for g in sel.group_by:
            if isinstance(g, ast.Literal) and isinstance(g.value, int):
                if not 1 <= g.value <= len(items):
                    raise SQLError(
                        f"GROUP BY term out of range - should be between 1 and {len(items)}"
                    )
                g = items[g.value - 1][0]
                if _contains_aggregate(g):
                    raise SQLError("aggregate functions are not allowed in the GROUP BY clause")
            group_exprs.append(g)
        group_compiler = Compiler(scope, aliases, clause="GROUP BY")
        group_fns = [group_compiler.compile(g) for g in group_exprs]
        group_keys = [_expr_key(g, scope, aliases) for g in group_exprs]
        group_values: list = []

        aggs: list[AggSpec] = []
        compiler = Compiler(scope, aliases, aggs)

        def compile_output(e: ast.Expr) -> Fn:
            # A result expression identical to a GROUP BY term yields the group's key value.
            fn = compiler.compile(e)
            key = _expr_key(e, scope, aliases) if group_keys else None
            if key is not None and key in group_keys:
                i = group_keys.index(key)
                return lambda row: group_values[i]
            return fn

        out_fns = [compile_output(e) for e, _ in items]

        # ORDER BY terms: either an output column position or an expression.
        order: list[tuple[int | None, Fn | None]] = []
        for oi in sel.order_by:
            e = oi.expr
            if isinstance(e, ast.Literal) and isinstance(e.value, int):
                if not 1 <= e.value <= len(items):
                    raise SQLError(
                        f"ORDER BY term out of range - should be between 1 and {len(items)}"
                    )
                order.append((e.value - 1, None))
            elif isinstance(e, ast.Column) and e.table is None and e.name.lower() in aliases:
                name = e.name.lower()
                pos = next(i for i, (_, a) in enumerate(items) if a and a.lower() == name)
                order.append((pos, None))
            else:
                order.append((None, compile_output(e)))

        having = compiler.compile(sel.having) if sel.having is not None else None

        def emit(row) -> tuple[tuple, list]:
            out = tuple(f(row) for f in out_fns)
            keys = [out[pos] if pos is not None else fn(row) for pos, fn in order]
            return out, keys

        if having is not None and not aggs and not sel.group_by:
            raise SQLError("HAVING clause on a non-aggregate query")
        results: list[tuple[tuple, list]] = []
        if aggs or sel.group_by:
            groups: dict[tuple, list] = {}
            for row in rows:
                key = tuple(g(row) for g in group_fns)
                grp = groups.get(key)
                if grp is None:
                    grp = groups[key] = [row, [Aggregate(a.kind, a.distinct) for a in aggs]]
                for spec, state in zip(aggs, grp[1], strict=True):
                    state.step([f(row) for f in spec.arg_fns], row)
            if not sel.group_by and not groups:
                groups[()] = [(None,) * len(scope), [Aggregate(a.kind, a.distinct) for a in aggs]]
            minmax = [i for i, a in enumerate(aggs) if a.kind in ("MIN", "MAX")]
            for key, (rep, states) in groups.items():
                group_values[:] = key
                compiler.agg_values[:] = [s.result() for s in states]
                if len(minmax) == 1 and states[minmax[0]].best_row is not None:
                    rep = states[minmax[0]].best_row
                if having is not None and V.truth(having(rep)) is not True:
                    continue
                results.append(emit(rep))
        else:
            results = [emit(row) for row in rows]

        if sel.distinct:
            seen = set()
            unique = []
            for out, keys in results:
                if out not in seen:
                    seen.add(out)
                    unique.append((out, keys))
            results = unique

        if order:
            _sort_rows(results, lambda r: r[1], [oi.desc for oi in sel.order_by])

        out_rows = [out for out, _ in results]
        if sel.limit is not None:
            limit = self._constant(sel.limit, "LIMIT")
            offset = self._constant(sel.offset, "OFFSET") if sel.offset is not None else 0
            offset = max(offset, 0)
            out_rows = out_rows[offset:] if limit < 0 else out_rows[offset : offset + limit]
        return out_rows
