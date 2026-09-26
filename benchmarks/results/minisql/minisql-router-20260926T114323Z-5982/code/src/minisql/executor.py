"""Statement execution: name resolution, expression compilation and query evaluation.

Expressions are compiled into Python closures taking a single *env* argument.  An env is a
tuple holding one row tuple per FROM source (``env[source][column]``).  In aggregate queries
the env additionally carries the list of finalized aggregate values as its last element.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from minisql import nodes as n
from minisql import values as v
from minisql.errors import SQLError

Fn = Callable[[Any], Any]


# ====================================================================== storage


class Table:
    def __init__(self, name: str, columns: list[n.ColumnDef]) -> None:
        self.name = name
        self.col_names = [c.name for c in columns]
        self.col_index: dict[str, int] = {}
        for i, c in enumerate(columns):
            key = c.name.lower()
            if key in self.col_index:
                raise SQLError(f"duplicate column name: {c.name}")
            self.col_index[key] = i
        self.affinities = [v.type_affinity(c.type_name) for c in columns]
        self.rows: list[tuple] = []

    @property
    def width(self) -> int:
        return len(self.col_names)

    def coerce_row(self, row: list[object]) -> tuple:
        affs = self.affinities
        return tuple(v.apply_storage_affinity(val, aff) for val, aff in zip(row, affs, strict=True))


@dataclass(slots=True)
class Source:
    name: str  # effective (alias or table) name, lower-case
    table: Table
    index: int


# ====================================================================== aggregates

_AGG_NAMES = frozenset({"count", "sum", "avg", "total", "min", "max"})


def is_agg_call(node: n.Func) -> bool:
    if node.name not in _AGG_NAMES:
        return False
    if node.name in ("min", "max"):
        return len(node.args) == 1 or node.star
    return True


def contains_agg(node: n.Expr | None) -> bool:
    if node is None:
        return False
    if isinstance(node, n.Func) and is_agg_call(node):
        return True
    return any(contains_agg(c) for c in n.children(node))


class _CountAcc:
    __slots__ = ("count",)

    def __init__(self) -> None:
        self.count = 0

    def step(self, x: object) -> bool:
        if x is not None:
            self.count += 1
        return True

    def final(self) -> object:
        return self.count


class _CountStarAcc(_CountAcc):
    __slots__ = ()

    def step(self, x: object) -> bool:
        self.count += 1
        return True


_BIG = 4503599627370496  # 2**52


def _c_mod(a: int, b: int) -> int:
    r = abs(a) % b
    return -r if a < 0 else r


class _SumAcc:
    """SQLite's sum()/avg()/total() state including Kahan-Babuska-Neumaier summation."""

    __slots__ = ("cnt", "isum", "rsum", "rerr", "approx", "ovrfl")

    def __init__(self) -> None:
        self.cnt = 0
        self.isum = 0
        self.rsum = 0.0
        self.rerr = 0.0
        self.approx = False
        self.ovrfl = False

    def _kbn(self, r: float) -> None:
        s = self.rsum
        t = s + r
        if abs(s) > abs(r):
            self.rerr += (s - t) + r
        else:
            self.rerr += (r - t) + s
        self.rsum = t

    def _kbn_int(self, i: int) -> None:
        if i <= -_BIG or i >= _BIG:
            sm = _c_mod(i, 16384)
            self._kbn(float(i - sm))
            self._kbn(float(sm))
        else:
            self._kbn(float(i))

    def _init(self, i: int) -> None:
        if i <= -_BIG or i >= _BIG:
            sm = _c_mod(i, 16384)
            self.rsum = float(i - sm)
            self.rerr = float(sm)
        else:
            self.rsum = float(i)
            self.rerr = 0.0

    def step(self, x: object) -> bool:
        if x is None:
            return True
        if type(x) is str:
            x = v.numeric_affinity(x)
        self.cnt += 1
        if not self.approx:
            if type(x) is not int:
                self._init(self.isum)
                self.approx = True
                self._kbn(v.to_real(x))
            else:
                s = self.isum + x
                if v.INT64_MIN <= s <= v.INT64_MAX:
                    self.isum = s
                else:
                    self.ovrfl = True
                    self._init(self.isum)
                    self.approx = True
                    self._kbn_int(x)
        elif type(x) is int:
            self._kbn_int(x)
        else:
            self.ovrfl = False
            self._kbn(v.to_real(x))
        return True

    def _real(self) -> float:
        r = self.rsum
        if math.isfinite(self.rerr):
            r += self.rerr
        return r


class _SumFinal(_SumAcc):
    __slots__ = ()

    def final(self) -> object:
        if self.cnt == 0:
            return None
        if self.approx:
            if self.ovrfl:
                raise SQLError("integer overflow")
            return self._real()
        return self.isum


class _AvgFinal(_SumAcc):
    __slots__ = ()

    def final(self) -> object:
        if self.cnt == 0:
            return None
        r = self._real() if self.approx else float(self.isum)
        return r / float(self.cnt)


class _TotalFinal(_SumAcc):
    __slots__ = ()

    def final(self) -> object:
        if self.cnt == 0:
            return 0.0
        return self._real() if self.approx else float(self.isum)


class _MinMaxAcc:
    __slots__ = ("best", "is_max")

    def __init__(self, is_max: bool) -> None:
        self.best: object = None
        self.is_max = is_max

    def step(self, x: object) -> bool:
        """Return True when the row is the new min/max (SQLite's bare-column rule)."""
        if x is None:
            return self.best is None
        if self.best is None:
            self.best = x
            return True
        c = v.compare(self.best, x)
        if (self.is_max and c < 0) or (not self.is_max and c > 0):
            self.best = x
            return True
        return False

    def final(self) -> object:
        return self.best


class _DistinctAcc:
    __slots__ = ("inner", "seen")

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.seen: set = set()

    def step(self, x: object) -> bool:
        if x is not None:
            if x in self.seen:
                return False
            self.seen.add(x)
        return self.inner.step(x)

    def final(self) -> object:
        return self.inner.final()


@dataclass(slots=True)
class AggSpec:
    name: str
    distinct: bool
    arg: Fn | None

    def new(self) -> Any:
        name = self.name
        if name == "count":
            acc: Any = _CountStarAcc() if self.arg is None else _CountAcc()
        elif name == "sum":
            acc = _SumFinal()
        elif name == "avg":
            acc = _AvgFinal()
        elif name == "total":
            acc = _TotalFinal()
        else:
            acc = _MinMaxAcc(name == "max")
        if self.distinct:
            acc = _DistinctAcc(acc)
        return acc


class AggRegistry:
    def __init__(self) -> None:
        self.specs: list[AggSpec] = []

    def register(self, spec: AggSpec) -> int:
        self.specs.append(spec)
        return len(self.specs) - 1


# ====================================================================== compiler

_MISUSE_AGG = "misuse of aggregate function {name}()"


@dataclass(slots=True)
class Ctx:
    sources: list[Source]
    nsrc: int = 0
    aliases: dict[str, n.Expr] | None = None
    agg: AggRegistry | None = None
    agg_error: str = _MISUSE_AGG

    def without_aliases(self, agg_error: str | None = None) -> Ctx:
        return Ctx(
            self.sources, self.nsrc, None, self.agg, agg_error or self.agg_error
        )


_CMP_TESTS: dict[str, Callable[[int], bool]] = {
    "=": lambda c: c == 0,
    "!=": lambda c: c != 0,
    "<": lambda c: c < 0,
    "<=": lambda c: c <= 0,
    ">": lambda c: c > 0,
    ">=": lambda c: c >= 0,
}

_ARITH: dict[str, Callable[[object, object], object]] = {
    "+": v.op_add,
    "-": v.op_sub,
    "*": v.op_mul,
    "/": v.op_div,
    "%": v.op_mod,
    "||": v.op_concat,
    "&": v.op_bitand,
    "|": v.op_bitor,
    "<<": v.op_shl,
    ">>": v.op_shr,
}

_CAST_AFFINITIES = {v.INTEGER, v.REAL, v.TEXT, v.NUMERIC}


def _cmp_fn(lf: Fn, rf: Fn, aff: str | None, test: Callable[[int], bool]) -> Fn:
    compare = v.compare
    if aff is None:

        def f(env: Any) -> object:
            a = lf(env)
            b = rf(env)
            if a is None or b is None:
                return None
            return 1 if test(compare(a, b)) else 0

        return f
    apply = v.apply_compare_affinity

    def g(env: Any) -> object:
        a = lf(env)
        b = rf(env)
        if a is None or b is None:
            return None
        a, b = apply(a, b, aff)
        return 1 if test(compare(a, b)) else 0

    return g


def _and(a: object, b: object) -> object:
    ta = v.truth(a)
    if ta is False:
        return 0
    tb = v.truth(b)
    if tb is False:
        return 0
    if ta is None or tb is None:
        return None
    return 1


def _not(a: object) -> object:
    t = v.truth(a)
    if t is None:
        return None
    return 0 if t else 1


def _cast(val: object, aff: str) -> object:
    if val is None:
        return None
    if aff == v.TEXT:
        return v.to_text(val)
    if aff == v.REAL:
        return v.to_real(val)
    if aff == v.INTEGER:
        return v.to_int(val)
    # NUMERIC
    if type(val) is not str:
        return val
    return v.numerify(val)


def _scalar_minmax(args: list[object], is_max: bool) -> object:
    if args[0] is None:
        return None
    best = 0
    for i in range(1, len(args)):
        if args[i] is None:
            return None
        c = v.compare(args[best], args[i])
        if is_max:
            if c < 0:
                best = i
        elif c >= 0:
            best = i
    return args[best]


def _abs(x: object) -> object:
    if x is None:
        return None
    if type(x) is int:
        if x == v.INT64_MIN:
            raise SQLError("integer overflow")
        return abs(x)
    return abs(v.to_real(x))


def _length(x: object) -> object:
    if x is None:
        return None
    return len(v.to_text(x))


def _upper(x: object) -> object:
    return None if x is None else v.ascii_upper(v.to_text(x))


def _lower(x: object) -> object:
    return None if x is None else v.ascii_lower(v.to_text(x))


def _nullif(a: object, b: object) -> object:
    if a is not None and b is not None and v.compare(a, b) == 0:
        return None
    return a


# name -> (min args, max args or None, implementation taking list of values)
_SCALARS: dict[str, tuple[int, int | None, Callable[[list[object]], object]]] = {
    "abs": (1, 1, lambda a: _abs(a[0])),
    "length": (1, 1, lambda a: _length(a[0])),
    "upper": (1, 1, lambda a: _upper(a[0])),
    "lower": (1, 1, lambda a: _lower(a[0])),
    "typeof": (1, 1, lambda a: v.typeof(a[0])),
    "nullif": (2, 2, lambda a: _nullif(a[0], a[1])),
    "min": (2, None, lambda a: _scalar_minmax(a, False)),
    "max": (2, None, lambda a: _scalar_minmax(a, True)),
}


def compile_expr(node: n.Expr, ctx: Ctx) -> tuple[Fn, str | None]:
    """Compile *node* into ``(fn, affinity)``."""
    t = type(node)
    if t is n.Literal:
        value = node.value  # type: ignore[attr-defined]
        return (lambda env: value), None
    if t is n.BoundColumn:
        si, ci = node.source, node.index  # type: ignore[attr-defined]
        return (lambda env: env[si][ci]), node.affinity  # type: ignore[attr-defined]
    if t is n.Column:
        return _compile_column(node, ctx)  # type: ignore[arg-type]
    if t is n.Unary:
        return _compile_unary(node, ctx)  # type: ignore[arg-type]
    if t is n.Binary:
        return _compile_binary(node, ctx)  # type: ignore[arg-type]
    if t is n.InList:
        return _compile_in(node, ctx), None  # type: ignore[arg-type]
    if t is n.Between:
        return _compile_between(node, ctx), None  # type: ignore[arg-type]
    if t is n.Like:
        return _compile_like(node, ctx), None  # type: ignore[arg-type]
    if t is n.Func:
        return _compile_func(node, ctx), None  # type: ignore[arg-type]
    if t is n.Case:
        return _compile_case(node, ctx), None  # type: ignore[arg-type]
    if t is n.Cast:
        return _compile_cast(node, ctx)  # type: ignore[arg-type]
    raise SQLError(f"unsupported expression: {node!r}")


def _compile_column(node: n.Column, ctx: Ctx) -> tuple[Fn, str | None]:
    name = node.name.lower()
    if node.table is None:
        matches = []
        for src in ctx.sources:
            ci = src.table.col_index.get(name)
            if ci is not None:
                matches.append((src, ci))
        if len(matches) > 1:
            raise SQLError(f"ambiguous column name: {node.name}")
        if matches:
            src, ci = matches[0]
            si = src.index
            return (lambda env: env[si][ci]), src.table.affinities[ci]
        if ctx.aliases is not None and name in ctx.aliases:
            alias_ctx = ctx.without_aliases(
                None if ctx.agg is not None else f"misuse of aliased aggregate {node.name}"
            )
            return compile_expr(ctx.aliases[name], alias_ctx)
        if node.dquoted:
            text = node.name
            return (lambda env: text), None
        raise SQLError(f"no such column: {node.name}")
    tname = node.table.lower()
    srcs = [s for s in ctx.sources if s.name == tname]
    label = f"{node.table}.{node.name}"
    if not srcs:
        raise SQLError(f"no such column: {label}")
    found = [(s, s.table.col_index[name]) for s in srcs if name in s.table.col_index]
    if not found:
        raise SQLError(f"no such column: {label}")
    if len(found) > 1:
        raise SQLError(f"ambiguous column name: {label}")
    src, ci = found[0]
    si = src.index
    return (lambda env: env[si][ci]), src.table.affinities[ci]


def _compile_unary(node: n.Unary, ctx: Ctx) -> tuple[Fn, str | None]:
    f, aff = compile_expr(node.operand, ctx)
    op = node.op
    if op == "+":
        return f, None
    if op == "-":
        neg = v.op_negate
        return (lambda env: neg(f(env))), None
    if op == "~":
        bitnot = v.op_bitnot
        return (lambda env: bitnot(f(env))), None
    if op == "NOT":
        return (lambda env: _not(f(env))), None
    raise SQLError(f"unknown operator {op}")


def _compile_binary(node: n.Binary, ctx: Ctx) -> tuple[Fn, str | None]:
    op = node.op
    lf, la = compile_expr(node.left, ctx)
    rf, ra = compile_expr(node.right, ctx)
    if op == "AND":
        return (lambda env: _and(lf(env), rf(env))), None
    if op == "OR":

        def or_(env: Any) -> object:
            ta = v.truth(lf(env))
            if ta is True:
                return 1
            tb = v.truth(rf(env))
            if tb is True:
                return 1
            if ta is None or tb is None:
                return None
            return 0

        return or_, None
    if op in _CMP_TESTS:
        return _cmp_fn(lf, rf, v.comparison_affinity(la, ra), _CMP_TESTS[op]), None
    if op in ("IS", "IS NOT"):
        aff = v.comparison_affinity(la, ra)
        want = 1 if op == "IS" else 0

        def is_(env: Any) -> object:
            a = lf(env)
            b = rf(env)
            if a is None or b is None:
                eq = a is None and b is None
            else:
                a, b = v.apply_compare_affinity(a, b, aff)
                eq = v.compare(a, b) == 0
            return want if eq else 1 - want

        return is_, None
    fn = _ARITH.get(op)
    if fn is None:
        raise SQLError(f"unknown operator {op}")
    return (lambda env: fn(lf(env), rf(env))), None


def _in_affinity(aff: str | None) -> str | None:
    if aff is None or aff == v.BLOB:
        return None
    return v.TEXT if aff == v.TEXT else v.NUMERIC


def _compile_in(node: n.InList, ctx: Ctx) -> Fn:
    lf, la = compile_expr(node.operand, ctx)
    items = [compile_expr(item, ctx)[0] for item in node.items]
    aff = _in_affinity(la)
    hit, miss = (0, 1) if node.negated else (1, 0)
    if not items:
        return lambda env: miss

    def f(env: Any) -> object:
        a = lf(env)
        if a is None:
            return None
        has_null = False
        for itf in items:
            b = itf(env)
            if b is None:
                has_null = True
                continue
            x, y = v.apply_compare_affinity(a, b, aff)
            if v.compare(x, y) == 0:
                return hit
        if has_null:
            return None
        return miss

    return f


def _compile_between(node: n.Between, ctx: Ctx) -> Fn:
    xf, xa = compile_expr(node.operand, ctx)
    lof, loa = compile_expr(node.low, ctx)
    hif, hia = compile_expr(node.high, ctx)
    aff_lo = v.comparison_affinity(xa, loa)
    aff_hi = v.comparison_affinity(xa, hia)
    negated = node.negated

    def cmp(a: object, b: object, aff: str | None, lower: bool) -> object:
        if a is None or b is None:
            return None
        a, b = v.apply_compare_affinity(a, b, aff)
        c = v.compare(a, b)
        return 1 if (c >= 0 if lower else c <= 0) else 0

    def f(env: Any) -> object:
        x = xf(env)
        res = _and(cmp(x, lof(env), aff_lo, True), cmp(x, hif(env), aff_hi, False))
        return _not(res) if negated else res

    return f


def _compile_like(node: n.Like, ctx: Ctx) -> Fn:
    vf = compile_expr(node.operand, ctx)[0]
    pf = compile_expr(node.pattern, ctx)[0]
    ef = compile_expr(node.escape, ctx)[0] if node.escape is not None else None
    negated = node.negated
    if node.op == "GLOB":
        if ef is not None:
            raise SQLError("ESCAPE is not supported with GLOB")

        def g(env: Any) -> object:
            res = v.glob(vf(env), pf(env))
            return _not(res) if negated else res

        return g

    def f(env: Any) -> object:
        res = v.like(vf(env), pf(env), ef(env) if ef is not None else None)
        return _not(res) if negated else res

    return f


def _compile_func(node: n.Func, ctx: Ctx) -> Fn:
    name = node.name
    if is_agg_call(node):
        if ctx.agg is None:
            raise SQLError(ctx.agg_error.format(name=name))
        nargs = len(node.args)
        if node.star:
            if name != "count":
                raise SQLError(f"wrong number of arguments to function {name}()")
        elif name == "count":
            if nargs > 1:
                raise SQLError(f"wrong number of arguments to function {name}()")
        elif nargs != 1:
            raise SQLError(f"wrong number of arguments to function {name}()")
        if node.distinct and nargs != 1:
            raise SQLError("DISTINCT aggregates must have exactly one argument")
        arg = None
        if nargs == 1:
            inner = Ctx(ctx.sources, ctx.nsrc, ctx.aliases, None, _MISUSE_AGG)
            arg = compile_expr(node.args[0], inner)[0]
        slot = ctx.agg.register(AggSpec(name, node.distinct, arg))
        pos = ctx.nsrc
        return lambda env: env[pos][slot]
    if name in ("coalesce", "ifnull"):
        nargs = len(node.args)
        if node.star or nargs < 2 or (name == "ifnull" and nargs != 2):
            raise SQLError(f"wrong number of arguments to function {name}()")
        fns = [compile_expr(a, ctx)[0] for a in node.args]

        def coalesce(env: Any) -> object:
            for fn in fns:
                val = fn(env)
                if val is not None:
                    return val
            return None

        return coalesce
    spec = _SCALARS.get(name)
    if spec is None:
        raise SQLError(f"no such function: {name}")
    lo, hi, impl = spec
    nargs = len(node.args)
    if node.star or nargs < lo or (hi is not None and nargs > hi):
        raise SQLError(f"wrong number of arguments to function {name}()")
    if node.distinct:
        raise SQLError(f"DISTINCT is not supported for scalar function {name}()")
    fns = [compile_expr(a, ctx)[0] for a in node.args]
    return lambda env: impl([fn(env) for fn in fns])


def _compile_case(node: n.Case, ctx: Ctx) -> Fn:
    else_f = compile_expr(node.else_, ctx)[0] if node.else_ is not None else None
    if node.operand is None:
        branches = [
            (compile_expr(c, ctx)[0], compile_expr(r, ctx)[0]) for c, r in node.whens
        ]

        def searched(env: Any) -> object:
            for cf, rf in branches:
                if v.truth(cf(env)) is True:
                    return rf(env)
            return else_f(env) if else_f is not None else None

        return searched
    bf, ba = compile_expr(node.operand, ctx)
    simple = []
    for c, r in node.whens:
        cf, ca = compile_expr(c, ctx)
        simple.append((cf, v.comparison_affinity(ba, ca), compile_expr(r, ctx)[0]))

    def simple_case(env: Any) -> object:
        base = bf(env)
        for cf, aff, rf in simple:
            w = cf(env)
            if base is not None and w is not None:
                x, y = v.apply_compare_affinity(base, w, aff)
                if v.compare(x, y) == 0:
                    return rf(env)
        return else_f(env) if else_f is not None else None

    return simple_case


def _compile_cast(node: n.Cast, ctx: Ctx) -> tuple[Fn, str | None]:
    f = compile_expr(node.operand, ctx)[0]
    aff = v.type_affinity(node.type_name)
    if aff not in _CAST_AFFINITIES:
        raise SQLError(f"CAST to {node.type_name} is not supported")
    return (lambda env: _cast(f(env), aff)), aff


# ====================================================================== database


def _ordinal(i: int) -> str:
    if 10 <= i % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(i % 10, "th")
    return f"{i}{suffix}"


def _int_position(expr: n.Expr) -> int | None:
    while isinstance(expr, n.Unary) and expr.op == "+":
        expr = expr.operand
    if isinstance(expr, n.Literal) and type(expr.value) is int:
        return expr.value
    return None


def _truthy(val: object) -> bool:
    return v.truth(val) is True


class Executor:
    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}

    def get_table(self, name: str) -> Table:
        table = self.tables.get(name.lower())
        if table is None:
            raise SQLError(f"no such table: {name}")
        return table

    def execute(self, stmt: n.Statement) -> list[tuple]:
        if isinstance(stmt, n.Select):
            return self.select(stmt)
        if isinstance(stmt, n.Insert):
            return self.insert(stmt)
        if isinstance(stmt, n.Update):
            return self.update(stmt)
        if isinstance(stmt, n.Delete):
            return self.delete(stmt)
        if isinstance(stmt, n.CreateTable):
            return self.create(stmt)
        if isinstance(stmt, n.DropTable):
            return self.drop(stmt)
        raise SQLError("unsupported statement")

    # ------------------------------------------------------------- DDL
    def create(self, stmt: n.CreateTable) -> list[tuple]:
        key = stmt.name.lower()
        if key in self.tables:
            if stmt.if_not_exists:
                return []
            raise SQLError(f"table {stmt.name} already exists")
        self.tables[key] = Table(stmt.name, stmt.columns)
        return []

    def drop(self, stmt: n.DropTable) -> list[tuple]:
        key = stmt.name.lower()
        if key not in self.tables:
            if stmt.if_exists:
                return []
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[key]
        return []

    # ------------------------------------------------------------- DML
    def insert(self, stmt: n.Insert) -> list[tuple]:
        table = self.get_table(stmt.table)
        if stmt.columns is None:
            targets = list(range(table.width))
        else:
            targets = []
            for col in stmt.columns:
                ci = table.col_index.get(col.lower())
                if ci is None:
                    raise SQLError(f"table {table.name} has no column named {col}")
                targets.append(ci)
        if stmt.select is not None:
            value_rows: list[list[object]] = [list(r) for r in self.select(stmt.select)]
            width = self._select_width(stmt.select)
        else:
            assert stmt.rows is not None
            ctx = Ctx([], 0)
            value_rows = []
            width = len(stmt.rows[0])
            for row in stmt.rows:
                value_rows.append([compile_expr(e, ctx)[0](()) for e in row])
        if width != len(targets):
            if stmt.columns is None:
                raise SQLError(
                    f"table {table.name} has {table.width} columns but {width} values were supplied"
                )
            raise SQLError(f"{width} values for {len(targets)} columns")
        new_rows = []
        for vals in value_rows:
            full: list[object] = [None] * table.width
            for ci, val in zip(targets, vals, strict=True):
                full[ci] = val
            new_rows.append(table.coerce_row(full))
        table.rows.extend(new_rows)
        return []

    def _select_width(self, sel: n.Select) -> int:
        sources = self._sources(sel)
        return len(self._expand_items(sel, sources))

    def _single_ctx(self, table: Table) -> Ctx:
        return Ctx([Source(table.name.lower(), table, 0)], 1)

    def update(self, stmt: n.Update) -> list[tuple]:
        table = self.get_table(stmt.table)
        ctx = self._single_ctx(table)
        where = compile_expr(stmt.where, ctx)[0] if stmt.where is not None else None
        sets = []
        for col, expr in stmt.assignments:
            ci = table.col_index.get(col.lower())
            if ci is None:
                raise SQLError(f"no such column: {col}")
            sets.append((ci, compile_expr(expr, ctx)[0], table.affinities[ci]))
        new_rows = []
        for row in table.rows:
            env = (row,)
            if where is None or _truthy(where(env)):
                new = list(row)
                for ci, fn, aff in sets:
                    new[ci] = v.apply_storage_affinity(fn(env), aff)
                new_rows.append(tuple(new))
            else:
                new_rows.append(row)
        table.rows = new_rows
        return []

    def delete(self, stmt: n.Delete) -> list[tuple]:
        table = self.get_table(stmt.table)
        if stmt.where is None:
            table.rows = []
            return []
        where = compile_expr(stmt.where, self._single_ctx(table))[0]
        table.rows = [row for row in table.rows if not _truthy(where((row,)))]
        return []

    # ------------------------------------------------------------- SELECT
    def _sources(self, sel: n.Select) -> list[Source]:
        sources: list[Source] = []
        if sel.from_table is None:
            return sources
        refs = [sel.from_table] + [j.table for j in sel.joins]
        for i, ref in enumerate(refs):
            table = self.get_table(ref.name)
            sources.append(Source((ref.alias or ref.name).lower(), table, i))
        return sources

    def _expand_items(
        self, sel: n.Select, sources: list[Source]
    ) -> list[tuple[n.Expr, str | None]]:
        out: list[tuple[n.Expr, str | None]] = []
        for item in sel.items:
            if not item.is_star:
                assert item.expr is not None
                out.append((item.expr, item.alias))
                continue
            if not sources:
                raise SQLError("no tables specified")
            if item.star_table is None:
                chosen = sources
                names = [s.name for s in sources]
                if len(set(names)) != len(names):
                    dup = next(nm for nm in names if names.count(nm) > 1)
                    raise SQLError(f"ambiguous column name: {dup}")
            else:
                chosen = [s for s in sources if s.name == item.star_table.lower()]
                if not chosen:
                    raise SQLError(f"no such table: {item.star_table}")
                if len(chosen) > 1:
                    raise SQLError(f"ambiguous column name: {item.star_table}")
            for src in chosen:
                for ci in range(src.table.width):
                    out.append((n.BoundColumn(src.index, ci, src.table.affinities[ci]), None))
        return out

    def _from_rows(self, sel: n.Select, sources: list[Source]) -> list[tuple]:
        if not sources:
            return [()]
        nsrc = len(sources)
        rows: list[tuple] = [(r,) for r in sources[0].table.rows]
        for k, join in enumerate(sel.joins, start=1):
            right = sources[k].table
            on = None
            if join.on is not None:
                on = compile_expr(join.on, Ctx(sources[: k + 1], nsrc))[0]
            new_rows: list[tuple] = []
            left_join = join.kind == "LEFT"
            null_row = (None,) * right.width
            for left in rows:
                matched = False
                for rrow in right.rows:
                    combined = left + (rrow,)
                    if on is None or _truthy(on(combined)):
                        new_rows.append(combined)
                        matched = True
                if left_join and not matched:
                    new_rows.append(left + (null_row,))
            rows = new_rows
        return rows

    def _eval_limit(self, expr: n.Expr) -> int:
        val = compile_expr(expr, Ctx([], 0))[0](())
        val = v.apply_storage_affinity(val, v.NUMERIC)
        if type(val) is not int:
            raise SQLError("datatype mismatch")
        return val

    def select(self, sel: n.Select) -> list[tuple]:
        sources = self._sources(sel)
        nsrc = len(sources)
        items = self._expand_items(sel, sources)
        ncols = len(items)
        aliases: dict[str, n.Expr] = {}
        for expr, alias in items:
            if alias is not None and alias.lower() not in aliases:
                aliases[alias.lower()] = expr
        alias_positions: dict[str, int] = {}
        for i, (_, alias) in enumerate(items):
            if alias is not None and alias.lower() not in alias_positions:
                alias_positions[alias.lower()] = i

        is_agg = bool(sel.group_by) or any(contains_agg(e) for e, _ in items)
        if sel.having is not None and not is_agg:
            raise SQLError("HAVING clause on a non-aggregate query")

        registry = AggRegistry() if is_agg else None
        item_ctx = Ctx(sources, nsrc, None, registry)
        item_fns = [compile_expr(e, item_ctx)[0] for e, _ in items]

        where_fn = None
        if sel.where is not None:
            where_fn = compile_expr(sel.where, Ctx(sources, nsrc, aliases, None))[0]

        group_fns: list[Fn] = []
        for i, g in enumerate(sel.group_by, start=1):
            expr = g
            pos = _int_position(g)
            if pos is not None:
                if not 1 <= pos <= ncols:
                    raise SQLError(
                        f"{_ordinal(i)} GROUP BY term out of range - should be between 1 and "
                        f"{ncols}"
                    )
                expr = items[pos - 1][0]
            gctx = Ctx(
                sources,
                nsrc,
                aliases,
                None,
                "aggregate functions are not allowed in the GROUP BY clause",
            )
            group_fns.append(compile_expr(expr, gctx)[0])

        having_fn = None
        if sel.having is not None:
            having_fn = compile_expr(sel.having, Ctx(sources, nsrc, aliases, registry))[0]

        # ORDER BY: each key is a function (out_row, env) -> value.
        order_keys: list[tuple[Callable[[tuple, Any], object], bool, bool]] = []
        for i, term in enumerate(sel.order_by, start=1):
            expr = term.expr
            key: Callable[[tuple, Any], object]
            idx = None
            if isinstance(expr, n.Column) and expr.table is None:
                idx = alias_positions.get(expr.name.lower())
            if idx is None:
                pos = _int_position(expr)
                if pos is not None:
                    if not 1 <= pos <= ncols:
                        raise SQLError(
                            f"{_ordinal(i)} ORDER BY term out of range - should be between 1 "
                            f"and {ncols}"
                        )
                    idx = pos - 1
            if idx is not None:
                key = (lambda j: lambda out, env: out[j])(idx)
            else:
                octx = Ctx(sources, nsrc, aliases, registry, "misuse of aggregate: {name}()")
                fn = compile_expr(expr, octx)[0]
                key = (lambda f: lambda out, env: f(env))(fn)
            nulls_high = term.nulls_first is not None and term.nulls_first == term.desc
            order_keys.append((key, term.desc, nulls_high))

        limit = self._eval_limit(sel.limit) if sel.limit is not None else -1
        offset = self._eval_limit(sel.offset) if sel.offset is not None else 0

        rows = self._from_rows(sel, sources)
        if where_fn is not None:
            rows = [r for r in rows if _truthy(where_fn(r))]

        results: list[tuple[tuple, tuple]] = []
        if not is_agg:
            for env in rows:
                out = tuple(f(env) for f in item_fns)
                keys = tuple(k(out, env) for k, _, _ in order_keys)
                results.append((out, keys))
        else:
            assert registry is not None
            for env in self._aggregate(rows, sources, group_fns, registry, bool(sel.group_by)):
                if having_fn is not None and not _truthy(having_fn(env)):
                    continue
                out = tuple(f(env) for f in item_fns)
                keys = tuple(k(out, env) for k, _, _ in order_keys)
                results.append((out, keys))

        if sel.distinct:
            seen: set = set()
            unique = []
            for item in results:
                if item[0] not in seen:
                    seen.add(item[0])
                    unique.append(item)
            results = unique

        for j in range(len(order_keys) - 1, -1, -1):
            _, desc, nulls_high = order_keys[j]
            results.sort(key=_make_sort_key(j, nulls_high), reverse=desc)

        out_rows = [r[0] for r in results]
        if offset > 0:
            out_rows = out_rows[offset:]
        if limit >= 0:
            out_rows = out_rows[:limit]
        return out_rows

    def _aggregate(
        self,
        rows: list[tuple],
        sources: list[Source],
        group_fns: list[Fn],
        registry: AggRegistry,
        grouped: bool,
    ) -> list[tuple]:
        specs = registry.specs
        minmax_slots = [i for i, s in enumerate(specs) if s.name in ("min", "max")]
        last_minmax = minmax_slots[-1] if minmax_slots else None
        null_env = tuple((None,) * s.table.width for s in sources)
        groups: dict[tuple, list] = {}
        for env in rows:
            key = tuple(g(env) for g in group_fns)
            state = groups.get(key)
            if state is None:
                state = [[spec.new() for spec in specs], null_env]
                groups[key] = state
            accs = state[0]
            hit = True
            for i, spec in enumerate(specs):
                arg = spec.arg
                h = accs[i].step(arg(env) if arg is not None else None)
                if i == last_minmax:
                    hit = h
            if hit:
                state[1] = env
        if not groups and not grouped:
            groups[()] = [[spec.new() for spec in specs], null_env]
        out = []
        for accs, bare in groups.values():
            aggvals = [acc.final() for acc in accs]
            out.append((*bare, aggvals))
        return out


def _make_sort_key(j: int, nulls_high: bool) -> Callable[[tuple], tuple]:
    null_key = (3, 0) if nulls_high else (0, 0)

    def key(item: tuple) -> tuple:
        val = item[1][j]
        if val is None:
            return null_key
        if type(val) is str:
            return (2, val)
        return (1, val)

    return key
