"""Compile expression trees into Python closures.

A compiled expression is a function taking one row (a tuple) and returning a value.
Column references compile to tuple indexing. In aggregate queries the row passed in is
the group's representative source row followed by the group's aggregate results, and an
aggregate call compiles to a lookup of its slot after the source columns.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from . import ast
from . import values as V
from .errors import SQLError

Fn = Callable[[tuple], object]

AGGREGATES = frozenset({"count", "sum", "avg", "min", "max", "total"})


def is_aggregate_call(e: ast.Expr) -> bool:
    if not isinstance(e, ast.Func) or e.name not in AGGREGATES:
        return False
    # min() and max() with several arguments are scalar functions.
    return not (e.name in ("min", "max") and len(e.args) != 1)


def children(e: ast.Expr) -> list[ast.Expr]:
    if isinstance(e, ast.Unary):
        return [e.operand]
    if isinstance(e, ast.Binary):
        return [e.left, e.right]
    if isinstance(e, ast.IsNull):
        return [e.operand]
    if isinstance(e, ast.InList):
        return [e.operand, *e.items]
    if isinstance(e, ast.Between):
        return [e.operand, e.low, e.high]
    if isinstance(e, ast.Like):
        return [e.operand, e.pattern] + ([e.escape] if e.escape is not None else [])
    if isinstance(e, ast.Func):
        return list(e.args)
    if isinstance(e, ast.Case):
        out = [] if e.operand is None else [e.operand]
        for w, t in e.whens:
            out += [w, t]
        if e.default is not None:
            out.append(e.default)
        return out
    if isinstance(e, ast.Cast):
        return [e.operand]
    return []


def contains_aggregate(e: ast.Expr) -> bool:
    if is_aggregate_call(e):
        return True
    return any(contains_aggregate(c) for c in children(e))


# ---------------------------------------------------------------------------
# Name resolution


@dataclass
class ScopeTable:
    key: str  # alias or table name, lower-case
    start: int
    columns: list[str]  # lower-case column names
    affinities: list[str]


class Scope:
    """The columns visible to an expression: the tables of a FROM clause, flattened."""

    def __init__(self) -> None:
        self.tables: list[ScopeTable] = []
        self.width = 0

    def add(self, key: str, columns: list[str], affinities: list[str]) -> None:
        self.tables.append(ScopeTable(key, self.width, columns, affinities))
        self.width += len(columns)

    def resolve(self, table: str | None, name: str) -> tuple[int, str] | None:
        matches = []
        for t in self.tables:
            if table is not None and t.key != table:
                continue
            for i, c in enumerate(t.columns):
                if c == name:
                    matches.append((t.start + i, t.affinities[i]))
        if len(matches) > 1:
            shown = f"{table}.{name}" if table else name
            raise SQLError(f"ambiguous column name: {shown}")
        return matches[0] if matches else None


@dataclass
class AggSpec:
    name: str
    arg: Fn | None  # None for count(*)
    distinct: bool
    key: str = ""  # repr of the call's syntax, used to share identical aggregates


@dataclass
class Ctx:
    scope: Scope
    aliases: dict[str, ast.Expr] | None = None
    aggs: list[AggSpec] | None = None  # None: aggregates not allowed here
    agg_base: int = 0
    resolving: frozenset[str] = field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# Compilation


def compile_expr(e: ast.Expr, ctx: Ctx) -> tuple[Fn, str | None]:
    """Compile an expression; returns (function, affinity or None)."""
    method = _DISPATCH.get(type(e))
    if method is None:  # pragma: no cover - parser only produces known nodes
        raise SQLError(f"unsupported expression: {e!r}")
    return method(e, ctx)


def _literal(e: ast.Literal, ctx: Ctx):
    v = e.value
    return (lambda r: v), None


def _column(e: ast.Column, ctx: Ctx):
    res = ctx.scope.resolve(e.table, e.name)
    if res is not None:
        idx, aff = res
        return (lambda r: r[idx]), aff
    if e.table is None and ctx.aliases and e.name in ctx.aliases and e.name not in ctx.resolving:
        sub = Ctx(ctx.scope, ctx.aliases, ctx.aggs, ctx.agg_base, ctx.resolving | {e.name})
        return compile_expr(ctx.aliases[e.name], sub)
    if e.table is not None:
        raise SQLError(f"no such column: {e.table}.{e.name}")
    raise SQLError(f"no such column: {e.name}")


def _unary(e: ast.Unary, ctx: Ctx):
    f, _ = compile_expr(e.operand, ctx)
    if e.op == "-":
        # SQLite computes -x as 0 - x (numeric literals are already folded by the parser).
        sub = V.sub
        return (lambda r: sub(0, f(r))), None
    if e.op == "+":
        return f, None
    truth = V.truth

    def not_(r):
        t = truth(f(r))
        return None if t is None else (0 if t else 1)

    return not_, None


_ARITH = {"+": V.add, "-": V.sub, "*": V.mul, "/": V.div, "%": V.mod, "||": V.concat}

_CMP = {
    "=": lambda c: c == 0,
    "!=": lambda c: c != 0,
    "<": lambda c: c < 0,
    "<=": lambda c: c <= 0,
    ">": lambda c: c > 0,
    ">=": lambda c: c >= 0,
}

_NUMERIC_AFFS = (V.INTEGER, V.REAL, V.NUMERIC)


def comparison_conversions(la: str | None, ra: str | None):
    """Affinity conversions applied to (left, right) operands before comparing."""
    if la in _NUMERIC_AFFS and ra not in _NUMERIC_AFFS:
        return None, V.numeric_affinity
    if ra in _NUMERIC_AFFS and la not in _NUMERIC_AFFS:
        return V.numeric_affinity, None
    if la == V.TEXT and ra is None:
        return None, V.text_affinity
    if ra == V.TEXT and la is None:
        return V.text_affinity, None
    return None, None


def make_comparer(la: str | None, ra: str | None) -> Callable[[object, object], int]:
    """Return cmp(a, b) for non-NULL a, b with comparison affinity applied."""
    lc, rc = comparison_conversions(la, ra)
    compare = V.compare
    if lc is None and rc is None:
        return compare
    if lc is None:
        return lambda a, b: compare(a, rc(b))
    return lambda a, b: compare(lc(a), b)


def _binary(e: ast.Binary, ctx: Ctx):
    lf, la = compile_expr(e.left, ctx)
    rf, ra = compile_expr(e.right, ctx)
    op = e.op
    if op in _ARITH:
        fn = _ARITH[op]
        return (lambda r: fn(lf(r), rf(r))), None
    truth = V.truth
    if op == "AND":

        def and_(r):
            a = truth(lf(r))
            if a is False:
                return 0
            b = truth(rf(r))
            if b is False:
                return 0
            if a is None or b is None:
                return None
            return 1

        return and_, None
    if op == "OR":

        def or_(r):
            a = truth(lf(r))
            if a:
                return 1
            b = truth(rf(r))
            if b:
                return 1
            if a is None or b is None:
                return None
            return 0

        return or_, None
    cmp = make_comparer(la, ra)
    if op in ("IS", "IS NOT"):
        want = 1 if op == "IS" else 0

        def is_(r):
            a = lf(r)
            b = rf(r)
            if a is None or b is None:
                same = a is None and b is None
            else:
                same = cmp(a, b) == 0
            return want if same else 1 - want

        return is_, None
    test = _CMP[op]

    def compare(r):
        a = lf(r)
        if a is None:
            return None
        b = rf(r)
        if b is None:
            return None
        return 1 if test(cmp(a, b)) else 0

    return compare, None


def _is_null(e: ast.IsNull, ctx: Ctx):
    f, _ = compile_expr(e.operand, ctx)
    if e.negated:
        return (lambda r: 0 if f(r) is None else 1), None
    return (lambda r: 1 if f(r) is None else 0), None


def _in_list(e: ast.InList, ctx: Ctx):
    lf, la = compile_expr(e.operand, ctx)
    # The comparison affinity of IN comes from the left operand alone.
    cmp = make_comparer(la, None)
    items = [(compile_expr(item, ctx)[0], cmp) for item in e.items]
    found, missing = (0, 1) if e.negated else (1, 0)

    def in_(r):
        v = lf(r)
        if not items:
            return missing
        if v is None:
            return None
        saw_null = False
        for f, cmp in items:
            w = f(r)
            if w is None:
                saw_null = True
            elif cmp(v, w) == 0:
                return found
        return None if saw_null else missing

    return in_, None


def _between(e: ast.Between, ctx: Ctx):
    f, a = compile_expr(e.operand, ctx)
    lof, loa = compile_expr(e.low, ctx)
    hif, hia = compile_expr(e.high, ctx)
    cmp_lo = make_comparer(a, loa)
    cmp_hi = make_comparer(a, hia)
    negated = e.negated

    def between(r):
        v = f(r)
        lo = lof(r)
        hi = hif(r)
        # v >= lo AND v <= hi, with three-valued logic.
        t1 = None if v is None or lo is None else cmp_lo(v, lo) >= 0
        if t1 is False:
            return 1 if negated else 0
        t2 = None if v is None or hi is None else cmp_hi(v, hi) <= 0
        if t2 is False:
            return 1 if negated else 0
        if t1 is None or t2 is None:
            return None
        return 0 if negated else 1

    return between, None


def _like(e: ast.Like, ctx: Ctx):
    f, _ = compile_expr(e.operand, ctx)
    pf, _ = compile_expr(e.pattern, ctx)
    ef = compile_expr(e.escape, ctx)[0] if e.escape is not None else None
    like = V.like
    negated = e.negated

    def like_(r):
        res = like(f(r), pf(r), ef(r) if ef is not None else None)
        if res is None or not negated:
            return res
        return 1 - res

    return like_, None


def _case(e: ast.Case, ctx: Ctx):
    default = compile_expr(e.default, ctx)[0] if e.default is not None else (lambda r: None)
    truth = V.truth
    if e.operand is None:
        whens = [(compile_expr(w, ctx)[0], compile_expr(t, ctx)[0]) for w, t in e.whens]

        def case(r):
            for w, t in whens:
                if truth(w(r)):
                    return t(r)
            return default(r)

        return case, None
    of, oa = compile_expr(e.operand, ctx)
    whens2 = []
    for w, t in e.whens:
        wf, wa = compile_expr(w, ctx)
        whens2.append((wf, make_comparer(oa, wa), compile_expr(t, ctx)[0]))

    def case_operand(r):
        v = of(r)
        if v is not None:
            for wf, cmp, t in whens2:
                w = wf(r)
                if w is not None and cmp(v, w) == 0:
                    return t(r)
        return default(r)

    return case_operand, None


def _cast(e: ast.Cast, ctx: Ctx):
    f, _ = compile_expr(e.operand, ctx)
    aff = V.affinity_of_type(e.type_name)
    cast = V.cast
    return (lambda r: cast(f(r), aff)), aff


def _func(e: ast.Func, ctx: Ctx):
    if is_aggregate_call(e):
        return _aggregate(e, ctx)
    if e.star or e.distinct:
        raise SQLError(f"wrong number of arguments to function {e.name}()")
    impl = _SCALARS.get(e.name)
    if impl is None:
        raise SQLError(f"no such function: {e.name}")
    fn, lo, hi = impl
    if not (lo <= len(e.args) <= hi):
        raise SQLError(f"wrong number of arguments to function {e.name}()")
    args = [compile_expr(a, ctx)[0] for a in e.args]
    if len(args) == 1:
        a0 = args[0]
        return (lambda r: fn(a0(r))), None
    return (lambda r: fn(*[a(r) for a in args])), None


def _aggregate(e: ast.Func, ctx: Ctx):
    if ctx.aggs is None:
        raise SQLError(f"misuse of aggregate function {e.name}()")
    if e.star:
        if e.name != "count":
            raise SQLError(f"wrong number of arguments to function {e.name}()")
        arg = None
    else:
        if len(e.args) != 1:
            raise SQLError(f"wrong number of arguments to function {e.name}()")
        inner = Ctx(ctx.scope, ctx.aliases, None, 0, ctx.resolving)
        arg = compile_expr(e.args[0], inner)[0]
    # Identical aggregate calls share one slot, as in SQLite (this matters for which row
    # supplies bare columns).
    # repr() rather than == so that e.g. min(0) and min(0.0) stay distinct.
    key = repr(e)
    for i, spec in enumerate(ctx.aggs):
        if spec.key == key:
            idx = ctx.agg_base + i
            break
    else:
        idx = ctx.agg_base + len(ctx.aggs)
        ctx.aggs.append(AggSpec(e.name, arg, e.distinct, key))
    return (lambda r: r[idx]), None


# ---------------------------------------------------------------------------
# Scalar functions


def _abs(v):
    if v is None:
        return None
    v = V.to_real(v) if isinstance(v, str) else v
    if type(v) is int and v == V.INT64_MIN:
        raise SQLError("integer overflow")
    return abs(v)


def _coalesce(*args):
    for a in args:
        if a is not None:
            return a
    return None


def _nullif(a, b):
    if a is not None and b is not None and V.compare(a, b) == 0:
        return None
    return a


def _length(v):
    if v is None:
        return None
    return len(V.to_text(v))


_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _upper(v):
    return None if v is None else V.to_text(v).translate(_UPPER)


def _lower(v):
    return None if v is None else V.to_text(v).translate(_LOWER)


def _typeof(v):
    if v is None:
        return "null"
    if isinstance(v, str):
        return "text"
    if isinstance(v, int):
        return "integer"
    return "real"


def _scalar_extreme(sign: int):
    def extreme(*args):
        best = None
        for i, a in enumerate(args):
            if a is None:
                return None
            if i == 0 or V.compare(a, best) * sign > 0:
                best = a
        return best

    return extreme


_BIG = 1 << 30
_SCALARS = {
    "abs": (_abs, 1, 1),
    "coalesce": (_coalesce, 2, _BIG),
    "ifnull": (_coalesce, 2, 2),
    "nullif": (_nullif, 2, 2),
    "length": (_length, 1, 1),
    "upper": (_upper, 1, 1),
    "lower": (_lower, 1, 1),
    "typeof": (_typeof, 1, 1),
    "min": (_scalar_extreme(-1), 2, _BIG),
    "max": (_scalar_extreme(1), 2, _BIG),
}

_DISPATCH = {
    ast.Literal: _literal,
    ast.Column: _column,
    ast.Unary: _unary,
    ast.Binary: _binary,
    ast.IsNull: _is_null,
    ast.InList: _in_list,
    ast.Between: _between,
    ast.Like: _like,
    ast.Case: _case,
    ast.Cast: _cast,
    ast.Func: _func,
}
