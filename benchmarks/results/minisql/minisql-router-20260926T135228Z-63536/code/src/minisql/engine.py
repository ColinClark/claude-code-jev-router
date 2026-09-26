"""Query compilation and execution."""

from __future__ import annotations

from collections.abc import Callable

from . import ast
from . import values as V
from .errors import SQLError
from .parser import parse

Row = tuple
CompiledFn = Callable[[Row, list | None], object]

_KNOWN_TYPES = {
    "INTEGER",
    "INT",
    "BIGINT",
    "SMALLINT",
    "TINYINT",
    "MEDIUMINT",
    "REAL",
    "FLOAT",
    "DOUBLE",
    "DOUBLE PRECISION",
    "TEXT",
    "VARCHAR",
    "CHAR",
    "CHARACTER",
    "CLOB",
    "NUMERIC",
    "DECIMAL",
    "BOOLEAN",
    "BLOB",
}

AGGREGATES = {"count", "sum", "avg", "min", "max", "total"}


# ---------------------------------------------------------------------------
# Storage


class Column:
    __slots__ = ("name", "lname", "affinity", "not_null", "default")

    def __init__(self, name, affinity, not_null=False, default=None):
        self.name = name
        self.lname = name.lower()
        self.affinity = affinity
        self.not_null = not_null
        self.default = default


class Table:
    def __init__(self, name: str, columns: list[Column]):
        self.name = name
        self.columns = columns
        self.index = {c.lname: i for i, c in enumerate(columns)}
        self.rows: list[Row] = []


class Source:
    __slots__ = ("name", "table", "offset")

    def __init__(self, name: str, table: Table, offset: int):
        self.name = name.lower()
        self.table = table
        self.offset = offset


# ---------------------------------------------------------------------------
# Aggregates


class CountAgg:
    __slots__ = ("n",)

    def __init__(self):
        self.n = 0

    def step(self, v):
        if v is not None:
            self.n += 1
        return False

    def final(self):
        return self.n


class CountStarAgg(CountAgg):
    __slots__ = ()

    def step(self, v):
        self.n += 1
        return False


def _cmod(a: int, b: int) -> int:
    r = abs(a) % abs(b)
    return -r if a < 0 else r


class SumAgg:
    """SUM / AVG / TOTAL following SQLite's Kahan-Babuska-Neumaier summation."""

    __slots__ = ("kind", "cnt", "isum", "approx", "rsum", "rerr")

    def __init__(self, kind: str):
        self.kind = kind
        self.cnt = 0
        self.isum = 0
        self.approx = False
        self.rsum = 0.0
        self.rerr = 0.0

    def _kbn(self, r: float) -> None:
        s = self.rsum
        t = s + r
        if abs(s) > abs(r):
            self.rerr += (s - t) + r
        else:
            self.rerr += (r - t) + s
        self.rsum = t

    def _kbn_int(self, v: int) -> None:
        if v <= -4503599627370496 or v >= 4503599627370496:
            sm = _cmod(v, 16384)
            self._kbn(float(v - sm))
            self._kbn(float(sm))
        else:
            self._kbn(float(v))

    def _init_approx(self) -> None:
        v = self.isum
        if v <= -4503599627370496 or v >= 4503599627370496:
            sm = _cmod(v, 16384)
            self.rsum = float(v - sm)
            self.rerr = float(sm)
        else:
            self.rsum = float(v)
            self.rerr = 0.0
        self.approx = True

    def step(self, v):
        if v is None:
            return False
        if isinstance(v, str):
            n = V.text_numeric_value(v)
            if n is None:
                v = float(V.to_number(v))
            else:
                v = n
        self.cnt += 1
        if not self.approx:
            if isinstance(v, int):
                s = self.isum + v
                if V.INT_MIN <= s <= V.INT_MAX:
                    self.isum = s
                else:
                    if self.kind == "sum":
                        raise SQLError("integer overflow")
                    self._init_approx()
                    self._kbn_int(v)
            else:
                self._init_approx()
                self._kbn(float(v))
        elif isinstance(v, int):
            self._kbn_int(v)
        else:
            self._kbn(float(v))
        return False

    def _real(self) -> float:
        r = self.rsum
        if self.rerr == self.rerr and abs(self.rerr) != float("inf"):
            r += self.rerr
        return r

    def final(self):
        if self.kind == "total":
            return self._real() if self.approx else float(self.isum)
        if self.cnt == 0:
            return None
        if self.kind == "sum":
            return self._real() if self.approx else self.isum
        total = self._real() if self.approx else float(self.isum)
        return total / float(self.cnt)


class MinMaxAgg:
    __slots__ = ("is_max", "best")

    def __init__(self, is_max: bool):
        self.is_max = is_max
        self.best = None

    def step(self, v):
        """Returns True when this row should become the group's representative row."""
        if v is None:
            return self.best is None
        if self.best is None:
            self.best = v
            return True
        c = V.compare(v, self.best)
        if (c > 0) if self.is_max else (c < 0):
            self.best = v
            return True
        return False

    def final(self):
        return self.best


class DistinctWrapper:
    __slots__ = ("inner", "seen")

    def __init__(self, inner):
        self.inner = inner
        self.seen = set()

    def step(self, v):
        if v is None:
            return False
        if v in self.seen:
            return False
        self.seen.add(v)
        return self.inner.step(v)

    def final(self):
        return self.inner.final()


class AggSpec:
    __slots__ = ("name", "arg", "distinct", "star", "key")

    def __init__(self, name, arg, distinct, star, key=None):
        self.key = key
        self.name = name
        self.arg = arg
        self.distinct = distinct
        self.star = star

    def new_state(self):
        if self.star:
            return CountStarAgg()
        if self.name == "count":
            st = CountAgg()
        elif self.name in ("min", "max"):
            st = MinMaxAgg(self.name == "max")
        else:
            st = SumAgg(self.name)
        if self.distinct:
            st = DistinctWrapper(st)
        return st


# ---------------------------------------------------------------------------
# Compilation


class Ctx:
    def __init__(self, sources, aliases=None, aggs=None, clause="", group_keys=None):
        self.sources: list[Source] = sources
        self.aliases: dict[str, ast.Expr] | None = aliases
        self.aggs: list[AggSpec] | None = aggs
        self.clause = clause
        # Structural key of a GROUP BY term -> negative index into the aggregate values.
        self.group_keys: dict | None = group_keys

    def without_aggs(self, clause=None) -> Ctx:
        return Ctx(self.sources, self.aliases, None, clause or self.clause)

    def without_aliases(self) -> Ctx:
        return Ctx(self.sources, None, self.aggs, self.clause, self.group_keys)


def _resolve_column(ref: ast.ColumnRef, ctx: Ctx):
    lname = ref.name.lower()
    hits = []
    if ref.table is not None:
        ltable = ref.table.lower()
        matches = [s for s in ctx.sources if s.name == ltable]
        if not matches:
            raise SQLError(f"no such column: {ref.table}.{ref.name}")
        for s in matches:
            idx = s.table.index.get(lname)
            if idx is not None:
                hits.append((s, idx))
        if not hits:
            raise SQLError(f"no such column: {ref.table}.{ref.name}")
    else:
        for s in ctx.sources:
            idx = s.table.index.get(lname)
            if idx is not None:
                hits.append((s, idx))
    if len(hits) > 1:
        name = f"{ref.table}.{ref.name}" if ref.table else ref.name
        raise SQLError(f"ambiguous column name: {name}")
    if hits:
        s, idx = hits[0]
        return s.offset + idx, s.table.columns[idx].affinity
    return None


def _cmp_fn(op: str):
    if op == "<":
        return lambda c: c < 0
    if op == "<=":
        return lambda c: c <= 0
    if op == ">":
        return lambda c: c > 0
    if op == ">=":
        return lambda c: c >= 0
    if op == "=":
        return lambda c: c == 0
    if op == "!=":
        return lambda c: c != 0
    raise AssertionError(op)


def _make_compare(lf, rf, op, caff):
    test = _cmp_fn(op)
    conv = V.converter_for(caff)
    compare = V.compare

    if conv is None:

        def fn(r, a):
            x = lf(r, a)
            if x is None:
                return None
            y = rf(r, a)
            if y is None:
                return None
            return 1 if test(compare(x, y)) else 0

    else:

        def fn(r, a):
            x = lf(r, a)
            if x is None:
                return None
            y = rf(r, a)
            if y is None:
                return None
            return 1 if test(compare(conv(x), conv(y))) else 0

    return fn


def _make_is(lf, rf, caff, negated):
    conv = V.converter_for(caff) or (lambda v: v)

    def fn(r, a):
        x = lf(r, a)
        y = rf(r, a)
        if x is None or y is None:
            eq = x is None and y is None
        else:
            eq = V.compare(conv(x), conv(y)) == 0
        return 0 if eq == negated else 1

    return fn


_ARITH = {
    "+": V.add,
    "-": V.sub,
    "*": V.mul,
    "/": V.div,
    "%": V.mod,
    "||": V.concat,
    "&": V.bit_and,
    "|": V.bit_or,
    "<<": V.shift_left,
    ">>": V.shift_right,
}


def _three_and(x, y):
    if x is False or y is False:
        return 0
    if x is None or y is None:
        return None
    return 1


def compile_expr(expr: ast.Expr, ctx: Ctx) -> tuple[CompiledFn, str | None]:
    if ctx.group_keys and not isinstance(
        expr, (ast.ColumnRef, ast.BoundColumn, ast.Literal)
    ):
        # A non-column expression identical to a GROUP BY term yields the group's key
        # value (taken from the group's first row), as in SQLite.
        idx = ctx.group_keys.get(_expr_key(expr))
        if idx is not None:
            return (lambda r, a: a[idx]), None
    if isinstance(expr, ast.Literal):
        v = expr.value
        return (lambda r, a: v), None

    if isinstance(expr, ast.BoundColumn):
        idx = expr.index
        return (lambda r, a: r[idx]), expr.affinity

    if isinstance(expr, ast.ColumnRef):
        res = _resolve_column(expr, ctx)
        if res is not None:
            idx, aff = res
            return (lambda r, a: r[idx]), aff
        if expr.table is None and ctx.aliases is not None:
            target = ctx.aliases.get(expr.name.lower())
            if target is not None:
                return compile_expr(target, ctx.without_aliases())
        if expr.table is not None:
            raise SQLError(f"no such column: {expr.table}.{expr.name}")
        raise SQLError(f"no such column: {expr.name}")

    if isinstance(expr, ast.Star):
        raise SQLError('near "*": syntax error')

    if isinstance(expr, ast.Unary):
        f, aff = compile_expr(expr.operand, ctx)
        if expr.op == "+":
            return f, None
        if expr.op == "-":
            neg = V.negate
            return (lambda r, a: neg(f(r, a))), None
        if expr.op == "~":
            bn = V.bit_not
            return (lambda r, a: bn(f(r, a))), None
        if expr.op == "NOT":
            truth = V.truth

            def not_fn(r, a):
                t = truth(f(r, a))
                if t is None:
                    return None
                return 0 if t else 1

            return not_fn, None
        raise AssertionError(expr.op)

    if isinstance(expr, ast.Binary):
        op = expr.op
        lf, laff = compile_expr(expr.left, ctx)
        rf, raff = compile_expr(expr.right, ctx)
        if op in _ARITH:
            func = _ARITH[op]
            return (lambda r, a: func(lf(r, a), rf(r, a))), None
        if op in ("<", "<=", ">", ">=", "=", "!="):
            return _make_compare(lf, rf, op, V.comparison_affinity(laff, raff)), None
        if op in ("IS", "ISNOT") and isinstance(expr.right, ast.BoolLiteral):
            want = bool(expr.right.value)
            negated = op == "ISNOT"
            truth = V.truth

            def is_truth_fn(r, a):
                t = truth(lf(r, a))
                return 1 if ((t is want) != negated) else 0

            return is_truth_fn, None
        if op in ("IS", "ISNOT"):
            caff = V.comparison_affinity(laff, raff)
            return _make_is(lf, rf, caff, op == "ISNOT"), None
        truth = V.truth
        if op == "AND":

            def and_fn(r, a):
                x = truth(lf(r, a))
                if x is False:
                    return 0
                y = truth(rf(r, a))
                if y is False:
                    return 0
                if x is None or y is None:
                    return None
                return 1

            return and_fn, None
        if op == "OR":

            def or_fn(r, a):
                x = truth(lf(r, a))
                if x is True:
                    return 1
                y = truth(rf(r, a))
                if y is True:
                    return 1
                if x is None or y is None:
                    return None
                return 0

            return or_fn, None
        raise AssertionError(op)

    if isinstance(expr, ast.Like):
        vf, _ = compile_expr(expr.expr, ctx)
        pf, _ = compile_expr(expr.pattern, ctx)
        ef = compile_expr(expr.escape, ctx)[0] if expr.escape is not None else None
        like = V.like
        negated = expr.negated

        def like_fn(r, a):
            if ef is not None:
                res = like(vf(r, a), pf(r, a), ef(r, a))
            else:
                res = like(vf(r, a), pf(r, a))
            if res is None or not negated:
                return res
            return 1 - res

        return like_fn, None

    if isinstance(expr, ast.Between):
        xf, xaff = compile_expr(expr.expr, ctx)
        lof, loaff = compile_expr(expr.low, ctx)
        hif, hiaff = compile_expr(expr.high, ctx)
        ge = _make_compare(xf, lof, ">=", V.comparison_affinity(xaff, loaff))
        le = _make_compare(xf, hif, "<=", V.comparison_affinity(xaff, hiaff))
        negated = expr.negated
        truth = V.truth

        def between_fn(r, a):
            res = _three_and(truth(ge(r, a)), truth(le(r, a)))
            if res is None or not negated:
                return res
            return 1 - res

        return between_fn, None

    if isinstance(expr, ast.InList):
        xf, xaff = compile_expr(expr.expr, ctx)
        item_fns = [compile_expr(it, ctx)[0] for it in expr.items]
        conv = V.converter_for(V.comparison_affinity(xaff, None)) or (lambda v: v)
        negated = expr.negated
        compare = V.compare

        def in_fn(r, a):
            if not item_fns:
                return 1 if negated else 0
            x = xf(r, a)
            if x is None:
                return None
            x = conv(x)
            has_null = False
            for itf in item_fns:
                y = itf(r, a)
                if y is None:
                    has_null = True
                    continue
                if compare(x, conv(y)) == 0:
                    return 0 if negated else 1
            if has_null:
                return None
            return 1 if negated else 0

        return in_fn, None

    if isinstance(expr, ast.Case):
        return _compile_case(expr, ctx), None

    if isinstance(expr, ast.Cast):
        f, _ = compile_expr(expr.expr, ctx)
        aff = V.affinity_for_type(expr.type_name)
        cast = V.cast_value
        return (lambda r, a: cast(f(r, a), aff)), aff

    if isinstance(expr, ast.FuncCall):
        return _compile_func(expr, ctx), None

    raise SQLError("unsupported expression")


def _compile_case(expr: ast.Case, ctx: Ctx) -> CompiledFn:
    else_f = compile_expr(expr.else_, ctx)[0] if expr.else_ is not None else (lambda r, a: None)
    truth = V.truth
    if expr.base is None:
        branches = [(compile_expr(c, ctx)[0], compile_expr(t, ctx)[0]) for c, t in expr.whens]

        def case_fn(r, a):
            for cf, tf in branches:
                if truth(cf(r, a)):
                    return tf(r, a)
            return else_f(r, a)

        return case_fn
    bf, baff = compile_expr(expr.base, ctx)
    branches = []
    for c, t in expr.whens:
        cf, caff = compile_expr(c, ctx)
        branches.append((_make_compare(bf, cf, "=", V.comparison_affinity(baff, caff)), t))
    branches = [(eqf, compile_expr(t, ctx)[0]) for eqf, t in branches]

    def simple_case_fn(r, a):
        for eqf, tf in branches:
            if eqf(r, a) == 1:
                return tf(r, a)
        return else_f(r, a)

    return simple_case_fn


def _expr_key(node):
    """Structural key of an expression (identifiers compared case-insensitively)."""
    if isinstance(node, ast.ColumnRef):
        return ("col", node.table.lower() if node.table else None, node.name.lower())
    if isinstance(node, (list, tuple)):
        return tuple(_expr_key(x) for x in node)
    if isinstance(node, ast.Expr):
        return (type(node).__name__,) + tuple(
            _expr_key(getattr(node, f)) for f in node.__dataclass_fields__
        )
    return (type(node).__name__, node)


def _check_args(name: str, args, lo: int, hi: int | None = None):
    n = len(args)
    if n < lo or (hi is not None and n > hi):
        raise SQLError(f"wrong number of arguments to function {name}()")


def _compile_func(expr: ast.FuncCall, ctx: Ctx) -> CompiledFn:
    name = expr.name
    nargs = len(expr.args)
    is_agg = name in AGGREGATES and not (name in ("min", "max") and nargs > 1)
    if is_agg:
        if ctx.aggs is None:
            raise SQLError(f"misuse of aggregate function {name}()")
        if expr.star:
            if name != "count":
                raise SQLError(f"wrong number of arguments to function {name}()")
            arg = None
        else:
            if name == "count" and nargs == 0:
                spec = AggSpec("count", None, False, True, ("count*",))
                ctx.aggs.append(spec)
                i = len(ctx.aggs) - 1
                return lambda r, a: a[i]
            _check_args(name, expr.args, 1, 1)
            arg = compile_expr(expr.args[0], ctx.without_aggs())[0]
        key = _expr_key(expr)
        for i, existing in enumerate(ctx.aggs):
            if existing.key == key:  # identical aggregates share one accumulator
                return lambda r, a, i=i: a[i]
        spec = AggSpec(name, arg, expr.distinct, expr.star, key)
        ctx.aggs.append(spec)
        i = len(ctx.aggs) - 1
        return lambda r, a: a[i]

    if expr.star:
        raise SQLError(f"wrong number of arguments to function {name}()")
    if expr.distinct:
        raise SQLError(f"DISTINCT is not allowed for function {name}()")
    fns = [compile_expr(arg, ctx)[0] for arg in expr.args]

    if name in ("min", "max"):
        want = 1 if name == "max" else -1

        def minmax_fn(r, a):
            best = None
            for f in fns:
                v = f(r, a)
                if v is None:
                    return None
                if best is None or V.compare(v, best) * want > 0:
                    best = v
            return best

        return minmax_fn
    if name == "coalesce":
        _check_args(name, fns, 2)

        def coalesce_fn(r, a):
            for f in fns:
                v = f(r, a)
                if v is not None:
                    return v
            return None

        return coalesce_fn
    if name == "ifnull":
        _check_args(name, fns, 2, 2)
        f0, f1 = fns

        def ifnull_fn(r, a):
            v = f0(r, a)
            return f1(r, a) if v is None else v

        return ifnull_fn
    if name == "nullif":
        _check_args(name, fns, 2, 2)
        f0, f1 = fns

        def nullif_fn(r, a):
            x = f0(r, a)
            y = f1(r, a)
            if x is not None and y is not None and V.compare(x, y) == 0:
                return None
            return x

        return nullif_fn
    if name == "typeof":
        _check_args(name, fns, 1, 1)
        f0 = fns[0]
        return lambda r, a: V.type_name(f0(r, a))
    if name == "abs":
        _check_args(name, fns, 1, 1)
        f0 = fns[0]

        def abs_fn(r, a):
            v = f0(r, a)
            if v is None:
                return None
            if isinstance(v, int):
                if v == V.INT_MIN:
                    raise SQLError("integer overflow")
                return abs(v)
            if isinstance(v, float):
                return abs(v)
            return abs(float(V.to_number(v)))

        return abs_fn
    if name == "length":
        _check_args(name, fns, 1, 1)
        f0 = fns[0]

        def length_fn(r, a):
            v = f0(r, a)
            if v is None:
                return None
            return len(V.to_text(v))

        return length_fn
    if name in ("lower", "upper"):
        _check_args(name, fns, 1, 1)
        f0 = fns[0]
        table = (
            {c: c + 32 for c in range(65, 91)}
            if name == "lower"
            else {c: c - 32 for c in range(97, 123)}
        )

        def case_conv_fn(r, a):
            v = f0(r, a)
            if v is None:
                return None
            return V.to_text(v).translate(table)

        return case_conv_fn
    raise SQLError(f"no such function: {name}")


def _contains_aggregate(expr) -> bool:
    if isinstance(expr, ast.FuncCall):
        if expr.name in AGGREGATES and not (expr.name in ("min", "max") and len(expr.args) > 1):
            return True
        return any(_contains_aggregate(a) for a in expr.args)
    if isinstance(expr, ast.Unary):
        return _contains_aggregate(expr.operand)
    if isinstance(expr, ast.Binary):
        return _contains_aggregate(expr.left) or _contains_aggregate(expr.right)
    if isinstance(expr, ast.Like):
        return any(
            _contains_aggregate(e) for e in (expr.expr, expr.pattern, expr.escape) if e is not None
        )
    if isinstance(expr, ast.Between):
        return any(_contains_aggregate(e) for e in (expr.expr, expr.low, expr.high))
    if isinstance(expr, ast.InList):
        return _contains_aggregate(expr.expr) or any(_contains_aggregate(e) for e in expr.items)
    if isinstance(expr, ast.Case):
        parts = [expr.base, expr.else_] + [x for w in expr.whens for x in w]
        return any(_contains_aggregate(e) for e in parts if e is not None)
    if isinstance(expr, ast.Cast):
        return _contains_aggregate(expr.expr)
    return False


def _const_int(expr: ast.Expr, what: str) -> int:
    f, _ = compile_expr(expr, Ctx([], None, None, what))
    v = f((), None)
    if isinstance(v, str):
        n = V.text_numeric_value(v)
        if n is None:
            raise SQLError("datatype mismatch")
        v = n
    if isinstance(v, float):
        if not v.is_integer():
            raise SQLError("datatype mismatch")
        v = int(v)
    if v is None:
        raise SQLError("datatype mismatch")
    return v


def _ordinal(expr: ast.Expr) -> int | None:
    if (
        isinstance(expr, ast.Literal)
        and not isinstance(expr, ast.BoolLiteral)
        and isinstance(expr.value, int)
    ):
        return expr.value
    return None


def _ordinal_name(i: int) -> str:
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(i if i < 20 else i % 10, "th")
    return f"{i}{suffix}"


# ---------------------------------------------------------------------------
# Database


class Database:
    """An in-memory SQL database."""

    def __init__(self):
        self.tables: dict[str, Table] = {}

    def execute(self, sql: str) -> list[tuple]:
        try:
            stmt = parse(sql)
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
        except RecursionError:
            raise SQLError("expression too complex") from None

    # -- DDL ----------------------------------------------------------------
    def _get_table(self, name: str) -> Table:
        t = self.tables.get(name.lower())
        if t is None:
            raise SQLError(f"no such table: {name}")
        return t

    def _create(self, stmt: ast.CreateTable) -> None:
        key = stmt.name.lower()
        if key in self.tables:
            if stmt.if_not_exists:
                return
            raise SQLError(f"table {stmt.name} already exists")
        cols = []
        seen = set()
        for cd in stmt.columns:
            if cd.name.lower() in seen:
                raise SQLError(f"duplicate column name: {cd.name}")
            seen.add(cd.name.lower())
            if cd.type_name is not None:
                norm = " ".join(cd.type_name.upper().split())
                if norm not in _KNOWN_TYPES:
                    raise SQLError(f"unknown type: {cd.type_name}")
            aff = V.affinity_for_type(cd.type_name)
            default = None
            if cd.default is not None:
                if _contains_aggregate(cd.default):
                    raise SQLError("default value of column is not constant")
                f, _ = compile_expr(cd.default, Ctx([], None, None, "DEFAULT"))
                default = f((), None)
            cols.append(Column(cd.name, aff, cd.not_null, default))
        self.tables[key] = Table(stmt.name, cols)

    def _drop(self, stmt: ast.DropTable) -> None:
        key = stmt.name.lower()
        if key not in self.tables:
            if stmt.if_exists:
                return
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[key]

    # -- DML ----------------------------------------------------------------
    def _finish_row(self, table: Table, values: list) -> Row:
        out = []
        for col, v in zip(table.columns, values, strict=True):
            v = V.apply_affinity(v, col.affinity)
            if v is None and col.not_null:
                raise SQLError(f"NOT NULL constraint failed: {table.name}.{col.name}")
            out.append(v)
        return tuple(out)

    def _insert(self, stmt: ast.Insert) -> None:
        table = self._get_table(stmt.table)
        ncols = len(table.columns)
        if stmt.columns is not None:
            targets = []
            for c in stmt.columns:
                idx = table.index.get(c.lower())
                if idx is None:
                    raise SQLError(f"table {table.name} has no column named {c}")
                targets.append(idx)
        else:
            targets = list(range(ncols))
        if stmt.select is not None:
            value_rows = self._select(stmt.select)
            if value_rows and len(value_rows[0]) != len(targets):
                raise SQLError(
                    f"table {table.name} has {ncols} columns but "
                    f"{len(value_rows[0])} values were supplied"
                )
            if not value_rows and self._select_width(stmt.select) != len(targets):
                raise SQLError(f"{len(targets)} values expected")
        else:
            value_rows = []
            ctx = Ctx([], None, None, "VALUES")
            width = len(stmt.rows[0])
            for row_exprs in stmt.rows:
                if len(row_exprs) != width:
                    raise SQLError("all VALUES must have the same number of terms")
            if width != len(targets):
                if stmt.columns is None:
                    raise SQLError(
                        f"table {table.name} has {ncols} columns but {width} values were supplied"
                    )
                raise SQLError(f"{width} values for {len(targets)} columns")
            for row_exprs in stmt.rows:
                fns = [compile_expr(e, ctx)[0] for e in row_exprs]
                value_rows.append(tuple(f((), None) for f in fns))
        new_rows = []
        for vals in value_rows:
            full = [c.default for c in table.columns]
            for idx, v in zip(targets, vals, strict=True):
                full[idx] = v
            new_rows.append(self._finish_row(table, full))
        table.rows.extend(new_rows)

    def _select_width(self, sel: ast.Select) -> int:
        n = 0
        for item in sel.items:
            if isinstance(item.expr, ast.Star):
                if item.expr.table is None:
                    n += sum(len(self._get_table(r.name).columns) for r in sel.sources)
                else:
                    for r in sel.sources:
                        if (r.alias or r.name).lower() == item.expr.table.lower():
                            n += len(self._get_table(r.name).columns)
            else:
                n += 1
        return n

    def _update(self, stmt: ast.Update) -> None:
        table = self._get_table(stmt.table)
        ctx = Ctx([Source(table.name, table, 0)], None, None, "UPDATE")
        assigns = []
        for col, e in stmt.assignments:
            idx = table.index.get(col.lower())
            if idx is None:
                raise SQLError(f"no such column: {col}")
            assigns.append((idx, compile_expr(e, ctx)[0]))
        where = compile_expr(stmt.where, ctx)[0] if stmt.where is not None else None
        new_rows = []
        for row in table.rows:
            if where is None or V.truth(where(row, None)):
                vals = list(row)
                for idx, f in assigns:
                    vals[idx] = f(row, None)
                new_rows.append(self._finish_row(table, vals))
            else:
                new_rows.append(row)
        table.rows = new_rows

    def _delete(self, stmt: ast.Delete) -> None:
        table = self._get_table(stmt.table)
        if stmt.where is None:
            table.rows = []
            return
        ctx = Ctx([Source(table.name, table, 0)], None, None, "WHERE")
        where = compile_expr(stmt.where, ctx)[0]
        table.rows = [r for r in table.rows if not V.truth(where(r, None))]

    # -- SELECT -------------------------------------------------------------
    def _select(self, sel: ast.Select) -> list[tuple]:
        # FROM clause: sources and join plan
        sources: list[Source] = []
        plan = []
        offset = 0
        for ref in sel.sources:
            table = self._get_table(ref.name)
            src = Source(ref.alias or ref.name, table, offset)
            sources.append(src)
            on_fn = None
            if ref.on is not None:
                if _contains_aggregate(ref.on):
                    raise SQLError("misuse of aggregate function in ON clause")
                on_fn = compile_expr(ref.on, Ctx(list(sources), None, None, "ON"))[0]
            plan.append((table, ref.join, on_fn, len(table.columns)))
            offset += len(table.columns)
        width = offset

        # Expand the select list
        items: list[tuple[ast.Expr, str | None]] = []
        for item in sel.items:
            if isinstance(item.expr, ast.Star):
                if not sources:
                    raise SQLError("no tables specified")
                if item.expr.table is None:
                    chosen = sources
                else:
                    chosen = [s for s in sources if s.name == item.expr.table.lower()]
                    if not chosen:
                        raise SQLError(f"no such table: {item.expr.table}")
                for s in chosen:
                    for i, c in enumerate(s.table.columns):
                        items.append((ast.BoundColumn(s.offset + i, c.affinity), None))
            else:
                items.append((item.expr, item.alias))
        aliases: dict[str, ast.Expr] = {}
        alias_index: dict[str, int] = {}
        for i, (e, alias) in enumerate(items):
            if alias is not None and alias.lower() not in aliases:
                aliases[alias.lower()] = e
                alias_index[alias.lower()] = i

        aggs: list[AggSpec] = []

        where_fn = None
        if sel.where is not None:
            where_fn = compile_expr(sel.where, Ctx(sources, aliases, None, "WHERE"))[0]

        group_fns = []
        group_terms: list[ast.Expr] = []
        for g in sel.group_by:
            n = _ordinal(g)
            if n is not None:
                if not 1 <= n <= len(items):
                    raise SQLError(
                        f"{_ordinal_name(len(group_fns) + 1)} GROUP BY term out of range - "
                        f"should be between 1 and {len(items)}"
                    )
                g = items[n - 1][0]
            if _contains_aggregate(g):
                raise SQLError("aggregate functions are not allowed in the GROUP BY clause")
            group_fns.append(compile_expr(g, Ctx(sources, aliases, None, "GROUP BY"))[0])
            group_terms.append(g)

        group_keys: dict = {}
        ngroup = len(group_terms)
        for j, g in enumerate(group_terms):
            if isinstance(g, ast.ColumnRef) and g.table is None and g.name.lower() in aliases:
                if _resolve_column(g, Ctx(sources)) is None:
                    g = aliases[g.name.lower()]
            group_keys.setdefault(_expr_key(g), j - ngroup)

        base_ctx = Ctx(sources, None, aggs, "result", group_keys)
        item_fns = [compile_expr(e, base_ctx)[0] for e, _ in items]

        order_specs = []  # (kind, value, desc): kind 'col' -> index, 'fn' -> compiled fn
        for i, term in enumerate(sel.order_by):
            e = term.expr
            n = _ordinal(e)
            if n is not None:
                if not 1 <= n <= len(items):
                    raise SQLError(
                        f"{_ordinal_name(i + 1)} ORDER BY term out of range - "
                        f"should be between 1 and {len(items)}"
                    )
                order_specs.append(("col", n - 1, term.desc))
                continue
            if isinstance(e, ast.ColumnRef) and e.table is None and e.name.lower() in alias_index:
                order_specs.append(("col", alias_index[e.name.lower()], term.desc))
                continue
            f = compile_expr(e, Ctx(sources, aliases, aggs, "ORDER BY", group_keys))[0]
            order_specs.append(("fn", f, term.desc))

        having_fn = None
        if sel.having is not None:
            having_ctx = Ctx(sources, aliases, aggs, "HAVING", group_keys)
            having_fn = compile_expr(sel.having, having_ctx)[0]

        is_agg = bool(sel.group_by) or bool(aggs)
        if having_fn is not None and not is_agg:
            raise SQLError("HAVING clause on a non-aggregate query")

        limit = offset_n = None
        if sel.limit is not None:
            limit = _const_int(sel.limit, "LIMIT")
        if sel.offset is not None:
            offset_n = _const_int(sel.offset, "OFFSET")

        # Produce source rows
        rows = self._scan(plan)
        if where_fn is not None:
            truth = V.truth
            rows = [r for r in rows if truth(where_fn(r, None))]

        results: list[tuple[tuple, list]] = []

        def order_keys(out, r, a):
            return [out[v] if kind == "col" else v(r, a) for kind, v, _ in order_specs]

        if is_agg:
            # SQLite loads bare columns on a row only if the *last* min()/max()
            # aggregate accepted that row's value (earlier ones are overwritten).
            minmax = [i for i, a in enumerate(aggs) if a.name in ("min", "max") and not a.star]
            rep_agg = minmax[-1] if minmax else -1
            groups: dict[tuple, list] = {}
            for r in rows:
                key = tuple(g(r, None) for g in group_fns)
                grp = groups.get(key)
                if grp is None:
                    grp = [r, [spec.new_state() for spec in aggs]]
                    groups[key] = grp
                states = grp[1]
                for j, (spec, st) in enumerate(zip(aggs, states, strict=True)):
                    v = None if spec.star else spec.arg(r, None)
                    # Bare columns come from the group's first row, or from the row the
                    # last min()/max() aggregate most recently accepted.
                    if st.step(v) and j == rep_agg:
                        grp[0] = r
            if not group_fns and not groups:
                groups[()] = [(None,) * width, [spec.new_state() for spec in aggs]]
            for key, (rep, states) in groups.items():
                aggvals = [st.final() for st in states]
                aggvals.extend(key)
                if having_fn is not None and not V.truth(having_fn(rep, aggvals)):
                    continue
                out = tuple(f(rep, aggvals) for f in item_fns)
                results.append((out, order_keys(out, rep, aggvals)))
        else:
            for r in rows:
                out = tuple(f(r, None) for f in item_fns)
                results.append((out, order_keys(out, r, None) if order_specs else []))

        if sel.distinct:
            seen = set()
            deduped = []
            for out, keys in results:
                if out not in seen:
                    seen.add(out)
                    deduped.append((out, keys))
            results = deduped

        if order_specs:
            sort_key = V.sort_key
            for i in range(len(order_specs) - 1, -1, -1):
                desc = order_specs[i][2]
                results.sort(key=lambda item, i=i: sort_key(item[1][i]), reverse=desc)

        out_rows = [out for out, _ in results]
        if offset_n is not None and offset_n > 0:
            out_rows = out_rows[offset_n:]
        if limit is not None and limit >= 0:
            out_rows = out_rows[:limit]
        return out_rows

    def _scan(self, plan) -> list[Row]:
        rows: list[Row] = [()]
        truth = V.truth
        for table, kind, on_fn, width in plan:
            new_rows = []
            right_rows = table.rows
            for left in rows:
                matched = False
                for right in right_rows:
                    comb = left + right
                    if on_fn is None or truth(on_fn(comb, None)):
                        new_rows.append(comb)
                        matched = True
                if kind == "LEFT" and not matched:
                    new_rows.append(left + (None,) * width)
            rows = new_rows
        return rows
