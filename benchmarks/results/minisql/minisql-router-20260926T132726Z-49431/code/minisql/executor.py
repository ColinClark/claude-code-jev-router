"""Statement execution: compiles AST expressions to closures and runs queries."""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass, field

from minisql import nodes as n
from minisql.errors import SQLError
from minisql.functions import AGGREGATE_ARGS, SCALAR_FUNCTIONS, compute_aggregate
from minisql.parser import parse
from minisql.values import (
    INTEGER,
    NUMERIC,
    REAL,
    TEXT,
    apply_affinity,
    arith,
    bitwise,
    compare,
    comparison_operands,
    concat,
    like,
    negate,
    numeric_affinity,
    sort_compare,
    to_integer,
    to_number,
    to_real,
    to_text,
    truth,
    type_affinity,
)

Fn = Callable[[list], object]


@dataclass
class Table:
    name: str
    columns: list[str]
    affinities: list[str]
    rows: list[list] = field(default_factory=list)

    def __post_init__(self):
        self.index = {c.lower(): i for i, c in enumerate(self.columns)}


@dataclass
class Source:
    alias: str  # lower-case name used for qualification
    table: Table
    offset: int


@dataclass
class AggSpec:
    name: str
    args: list[Fn]
    distinct: bool
    star: bool


class Ctx:
    """Compilation context: visible sources, aggregate slots and select aliases."""

    def __init__(
        self,
        sources: list[Source],
        width: int,
        aggs: list[AggSpec] | None = None,
        aliases: dict[str, n.Expr] | None = None,
    ):
        self.sources = sources
        self.width = width
        self.aggs = aggs
        self.aliases = aliases or {}
        self.resolving: set[str] = set()

    def without_aggs(self) -> Ctx:
        c = Ctx(self.sources, self.width, None, self.aliases)
        c.resolving = self.resolving
        return c


def _cmp_op(op: str, c: int) -> int:
    if op == "=":
        return int(c == 0)
    if op == "!=":
        return int(c != 0)
    if op == "<":
        return int(c < 0)
    if op == "<=":
        return int(c <= 0)
    if op == ">":
        return int(c > 0)
    return int(c >= 0)


def _compare_values(op: str, a, aff_a, b, aff_b):
    if a is None or b is None:
        return None
    a, b = comparison_operands(a, aff_a, b, aff_b)
    return _cmp_op(op, compare(a, b))


def _cast(v, type_name: str):
    if v is None:
        return None
    aff = type_affinity(type_name)
    if aff == TEXT:
        return to_text(v)
    if aff == INTEGER:
        return to_integer(v)
    if aff == REAL:
        return to_real(v)
    if aff == NUMERIC:
        if isinstance(v, str):
            num = to_number(v)
            return numeric_affinity(num)
        return numeric_affinity(v)
    return v  # BLOB / NONE: unchanged


class Compiler:
    """Turns expression AST nodes into Python closures over flat rows."""

    def compile(self, node: n.Expr, ctx: Ctx) -> tuple[Fn, str | None]:
        method = getattr(self, "c_" + type(node).__name__)
        return method(node, ctx)

    def fn(self, node: n.Expr, ctx: Ctx) -> Fn:
        return self.compile(node, ctx)[0]

    # -------------------------------------------------------------- leaves
    def c_Literal(self, node: n.Literal, ctx: Ctx):
        v = node.value
        return (lambda r: v), None

    def c_Column(self, node: n.Column, ctx: Ctx):
        lname = node.name.lower()
        if node.table is not None:
            lt = node.table.lower()
            for s in ctx.sources:
                if s.alias == lt:
                    idx = s.table.index.get(lname)
                    if idx is None:
                        break
                    pos = s.offset + idx
                    return (lambda r, pos=pos: r[pos]), s.table.affinities[idx]
            raise SQLError(f"no such column: {node.table}.{node.name}")
        matches = []
        for s in ctx.sources:
            idx = s.table.index.get(lname)
            if idx is not None:
                matches.append((s, idx))
        if len(matches) > 1:
            raise SQLError(f"ambiguous column name: {node.name}")
        if matches:
            s, idx = matches[0]
            pos = s.offset + idx
            return (lambda r: r[pos]), s.table.affinities[idx]
        if lname in ctx.aliases and lname not in ctx.resolving:
            ctx.resolving.add(lname)
            try:
                f, _ = self.compile(ctx.aliases[lname], ctx)
            finally:
                ctx.resolving.discard(lname)
            return f, None
        if lname == "true":
            return (lambda r: 1), None
        if lname == "false":
            return (lambda r: 0), None
        raise SQLError(f"no such column: {node.name}")

    # -------------------------------------------------------------- operators
    def c_Unary(self, node: n.Unary, ctx: Ctx):
        f = self.fn(node.operand, ctx)
        if node.op == "-":
            return (lambda r: negate(f(r))), None
        if node.op == "+":
            return f, None
        if node.op == "~":

            def bitnot(r):
                v = f(r)
                return None if v is None else ~to_integer(v)

            return bitnot, None
        if node.op == "NOT":

            def not_(r):
                t = truth(f(r))
                return None if t is None else int(not t)

            return not_, None
        raise SQLError(f"unknown operator {node.op}")

    def c_Binary(self, node: n.Binary, ctx: Ctx):
        op = node.op
        fa, aff_a = self.compile(node.left, ctx)
        fb, aff_b = self.compile(node.right, ctx)
        if op == "AND":

            def and_(r):
                a = truth(fa(r))
                if a is False:
                    return 0
                b = truth(fb(r))
                if b is False:
                    return 0
                if a is None or b is None:
                    return None
                return 1

            return and_, None
        if op == "OR":

            def or_(r):
                a = truth(fa(r))
                if a is True:
                    return 1
                b = truth(fb(r))
                if b is True:
                    return 1
                if a is None or b is None:
                    return None
                return 0

            return or_, None
        if op in ("=", "!=", "<", "<=", ">", ">="):
            return (lambda r: _compare_values(op, fa(r), aff_a, fb(r), aff_b)), None
        if op in ("IS", "ISNOT"):
            want = op == "IS"

            def is_(r):
                a, b = fa(r), fb(r)
                if a is None or b is None:
                    eq = a is None and b is None
                else:
                    a, b = comparison_operands(a, aff_a, b, aff_b)
                    eq = compare(a, b) == 0
                return int(eq == want)

            return is_, None
        if op in ("+", "-", "*", "/", "%"):
            return (lambda r: arith(op, fa(r), fb(r))), None
        if op == "||":
            return (lambda r: concat(fa(r), fb(r))), None
        if op in ("&", "|", "<<", ">>"):
            return (lambda r: bitwise(op, fa(r), fb(r))), None
        raise SQLError(f"unknown operator {op}")

    def c_InList(self, node: n.InList, ctx: Ctx):
        f, aff = self.compile(node.operand, ctx)
        items = [self.compile(i, ctx) for i in node.items]
        negated = node.negated

        def in_(r):
            v = f(r)
            if not items:
                return int(negated)
            if v is None:
                return None
            has_null = False
            found = False
            for fi, affi in items:
                iv = fi(r)
                if iv is None:
                    has_null = True
                    continue
                a, b = comparison_operands(v, aff, iv, affi)
                if compare(a, b) == 0:
                    found = True
                    break
            if found:
                return int(not negated)
            if has_null:
                return None
            return int(negated)

        return in_, None

    def c_Between(self, node: n.Between, ctx: Ctx):
        f, aff = self.compile(node.operand, ctx)
        flo, aff_lo = self.compile(node.low, ctx)
        fhi, aff_hi = self.compile(node.high, ctx)
        negated = node.negated

        def between(r):
            v = f(r)
            ge = _compare_values(">=", v, aff, flo(r), aff_lo)
            if ge == 0:
                res = 0
            else:
                le = _compare_values("<=", v, aff, fhi(r), aff_hi)
                if le == 0:
                    res = 0
                elif ge is None or le is None:
                    res = None
                else:
                    res = 1
            if res is None:
                return None
            return int(not res) if negated else res

        return between, None

    def c_Like(self, node: n.Like, ctx: Ctx):
        f = self.fn(node.operand, ctx)
        fp = self.fn(node.pattern, ctx)
        fe = self.fn(node.escape, ctx) if node.escape is not None else None
        negated = node.negated

        def like_(r):
            esc = None
            if fe is not None:
                esc = fe(r)
                if esc is None:
                    return None
            try:
                res = like(f(r), fp(r), esc)
            except ValueError as e:
                raise SQLError(str(e)) from None
            if res is None:
                return None
            return int(not res) if negated else res

        return like_, None

    def c_Case(self, node: n.Case, ctx: Ctx):
        whens = [(self.compile(c, ctx), self.fn(v, ctx)) for c, v in node.whens]
        fe = self.fn(node.else_, ctx) if node.else_ is not None else (lambda r: None)
        if node.operand is not None:
            fo, aff_o = self.compile(node.operand, ctx)

            def case_op(r):
                base = fo(r)
                for (fc, aff_c), fv in whens:
                    if _compare_values("=", base, aff_o, fc(r), aff_c) == 1:
                        return fv(r)
                return fe(r)

            return case_op, None

        def case(r):
            for (fc, _), fv in whens:
                if truth(fc(r)):
                    return fv(r)
            return fe(r)

        return case, None

    def c_Cast(self, node: n.Cast, ctx: Ctx):
        f = self.fn(node.operand, ctx)
        tn = node.type_name
        return (lambda r: _cast(f(r), tn)), type_affinity(tn)

    def c_Func(self, node: n.Func, ctx: Ctx):
        name = node.name
        nargs = len(node.args)
        is_agg = name in AGGREGATE_ARGS and not (name in ("MIN", "MAX") and nargs != 1)
        if node.star and name != "COUNT":
            raise SQLError(f"wrong number of arguments to function {name.lower()}()")
        if is_agg:
            lo, hi = AGGREGATE_ARGS[name]
            if not node.star and not (lo <= nargs <= hi):
                raise SQLError(f"wrong number of arguments to function {name.lower()}()")
            if ctx.aggs is None:
                raise SQLError(f"misuse of aggregate function {name.lower()}()")
            inner = ctx.without_aggs()
            args = [self.fn(a, inner) for a in node.args]
            if node.distinct and len(args) != 1:
                raise SQLError(
                    "DISTINCT aggregates must have exactly one argument"
                )
            star = node.star or (name == "COUNT" and nargs == 0)
            spec = AggSpec(name, args, node.distinct, star)
            pos = ctx.width + len(ctx.aggs)
            ctx.aggs.append(spec)
            return (lambda r: r[pos]), None
        entry = SCALAR_FUNCTIONS.get(name)
        if entry is None:
            raise SQLError(f"no such function: {name.lower()}")
        if node.distinct:
            raise SQLError(f"DISTINCT is not allowed for function {name.lower()}()")
        lo, hi = entry[0], entry[1]
        if nargs < lo or (hi is not None and nargs > hi):
            raise SQLError(f"wrong number of arguments to function {name.lower()}()")
        impl = entry[2]
        compiled = [self.compile(a, ctx) for a in node.args]
        fns = [c[0] for c in compiled]
        aff = None
        if name in ("COALESCE", "IFNULL", "NULLIF") or (name in ("MIN", "MAX")):
            aff = compiled[0][1]
        if name in ("COALESCE", "IFNULL"):

            def coalesce(r):
                for f in fns:
                    v = f(r)
                    if v is not None:
                        return v
                return None

            return coalesce, aff
        return (lambda r: impl(*[f(r) for f in fns])), aff


_COMPILER = Compiler()


def _limit_value(expr: n.Expr | None, what: str) -> int | None:
    if expr is None:
        return None
    v = _COMPILER.fn(expr, Ctx([], 0))([])
    if v is None:
        raise SQLError("datatype mismatch")
    v = numeric_affinity(v)
    if isinstance(v, float):
        if not v.is_integer():
            raise SQLError("datatype mismatch")
        v = int(v)
    if not isinstance(v, int):
        raise SQLError("datatype mismatch")
    return v


class Database:
    """An in-memory SQL database."""

    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}

    # ------------------------------------------------------------ public API
    def execute(self, sql: str) -> list[tuple]:
        if not isinstance(sql, str):
            raise SQLError("SQL must be a string")
        try:
            stmt = parse(sql)
            if stmt is None:
                return []
            if isinstance(stmt, n.Select):
                return self._select(stmt)
            if isinstance(stmt, n.CreateTable):
                self._create(stmt)
            elif isinstance(stmt, n.DropTable):
                self._drop(stmt)
            elif isinstance(stmt, n.Insert):
                self._insert(stmt)
            elif isinstance(stmt, n.Update):
                self._update(stmt)
            elif isinstance(stmt, n.Delete):
                self._delete(stmt)
            else:  # pragma: no cover - parser only produces the above
                raise SQLError("unsupported statement")
            return []
        except RecursionError:
            raise SQLError("expression tree is too large") from None
        except OverflowError as e:
            raise SQLError(str(e)) from None

    # ------------------------------------------------------------ DDL
    def _table(self, name: str) -> Table:
        t = self.tables.get(name.lower())
        if t is None:
            raise SQLError(f"no such table: {name}")
        return t

    def _create(self, stmt: n.CreateTable) -> None:
        key = stmt.name.lower()
        if key in self.tables:
            if stmt.if_not_exists:
                return
            raise SQLError(f"table {stmt.name} already exists")
        names = [c.name for c in stmt.columns]
        seen: set[str] = set()
        for c in names:
            if c.lower() in seen:
                raise SQLError(f"duplicate column name: {c}")
            seen.add(c.lower())
        affs = [type_affinity(c.type_name) for c in stmt.columns]
        self.tables[key] = Table(stmt.name, names, affs)

    def _drop(self, stmt: n.DropTable) -> None:
        key = stmt.name.lower()
        if key not in self.tables:
            if stmt.if_exists:
                return
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[key]

    # ------------------------------------------------------------ DML
    def _insert(self, stmt: n.Insert) -> None:
        t = self._table(stmt.table)
        ncols = len(t.columns)
        if stmt.columns is not None:
            targets = []
            for c in stmt.columns:
                idx = t.index.get(c.lower())
                if idx is None:
                    raise SQLError(f"table {t.name} has no column named {c}")
                targets.append(idx)
        else:
            targets = list(range(ncols))
        if stmt.select is not None:
            values_rows = self._select(stmt.select)
        else:
            empty = Ctx([], 0)
            values_rows = []
            for row in stmt.rows or []:
                fns = [_COMPILER.fn(e, empty) for e in row]
                values_rows.append(tuple(f([]) for f in fns))
        new_rows = []
        for vals in values_rows:
            if len(vals) != len(targets):
                if stmt.columns is None:
                    raise SQLError(
                        f"table {t.name} has {ncols} columns but {len(vals)} values were supplied"
                    )
                raise SQLError(f"{len(vals)} values for {len(targets)} columns")
            row: list = [None] * ncols
            for idx, v in zip(targets, vals, strict=True):
                row[idx] = apply_affinity(v, t.affinities[idx])
            new_rows.append(row)
        t.rows.extend(new_rows)

    def _single_ctx(self, t: Table) -> Ctx:
        return Ctx([Source(t.name.lower(), t, 0)], len(t.columns))

    def _update(self, stmt: n.Update) -> None:
        t = self._table(stmt.table)
        ctx = self._single_ctx(t)
        where = _COMPILER.fn(stmt.where, ctx) if stmt.where is not None else None
        assigns = []
        for col, expr in stmt.assignments:
            idx = t.index.get(col.lower())
            if idx is None:
                raise SQLError(f"no such column: {col}")
            assigns.append((idx, _COMPILER.fn(expr, ctx)))
        new_rows = []
        for row in t.rows:
            if where is None or truth(where(row)):
                new = list(row)
                for idx, f in assigns:
                    new[idx] = apply_affinity(f(row), t.affinities[idx])
                new_rows.append(new)
            else:
                new_rows.append(row)
        t.rows = new_rows

    def _delete(self, stmt: n.Delete) -> None:
        t = self._table(stmt.table)
        if stmt.where is None:
            t.rows = []
            return
        where = _COMPILER.fn(stmt.where, self._single_ctx(t))
        t.rows = [row for row in t.rows if not truth(where(row))]

    # ------------------------------------------------------------ SELECT
    def _from(self, stmt: n.Select) -> tuple[list[Source], int, list[list]]:
        if stmt.from_ is None:
            return [], 0, [[]]
        t = self._table(stmt.from_.name)
        sources = [Source((stmt.from_.alias or t.name).lower(), t, 0)]
        width = len(t.columns)
        rows: list[list] = t.rows
        for join in stmt.joins:
            jt = self._table(join.table.name)
            src = Source((join.table.alias or jt.name).lower(), jt, width)
            sources = sources + [src]
            width += len(jt.columns)
            on = None
            if join.on is not None:
                on = _COMPILER.fn(join.on, Ctx(sources, width))
            left = join.kind == "LEFT"
            nulls = [None] * len(jt.columns)
            new_rows = []
            right_rows = jt.rows
            for r in rows:
                matched = False
                for s in right_rows:
                    combined = r + s
                    if on is None or truth(on(combined)):
                        new_rows.append(combined)
                        matched = True
                if left and not matched:
                    new_rows.append(r + nulls)
            rows = new_rows
        return sources, width, rows

    def _select(self, stmt: n.Select) -> list[tuple]:
        sources, width, rows = self._from(stmt)
        aliases: dict[str, n.Expr] = {}
        for item in stmt.items:
            if item.alias is not None and not isinstance(item.expr, n.Star):
                aliases.setdefault(item.alias.lower(), item.expr)
        aggs: list[AggSpec] = []
        ctx = Ctx(sources, width, aggs, aliases)
        noagg = ctx.without_aggs()

        # Result columns.
        out_fns: list[Fn] = []
        out_exprs: list[n.Expr | None] = []
        out_names: list[str | None] = []
        for item in stmt.items:
            if isinstance(item.expr, n.Star):
                if not sources:
                    raise SQLError("no tables specified")
                chosen = sources
                if item.expr.table is not None:
                    lt = item.expr.table.lower()
                    chosen = [s for s in sources if s.alias == lt]
                    if not chosen:
                        raise SQLError(f"no such table: {item.expr.table}")
                for s in chosen:
                    for i in range(len(s.table.columns)):
                        pos = s.offset + i
                        out_fns.append(lambda r, pos=pos: r[pos])
                        out_exprs.append(None)
                        out_names.append(None)
            else:
                out_fns.append(_COMPILER.fn(item.expr, ctx))
                out_exprs.append(item.expr)
                out_names.append(item.alias.lower() if item.alias is not None else None)
        ncols = len(out_fns)

        where = _COMPILER.fn(stmt.where, noagg) if stmt.where is not None else None

        group_fns: list[Fn] = []
        for g in stmt.group_by:
            if isinstance(g, n.Literal) and isinstance(g.value, int):
                k = g.value
                if not 1 <= k <= ncols:
                    raise SQLError(
                        f"GROUP BY term out of range - should be between 1 and {ncols}"
                    )
                expr = out_exprs[k - 1]
                if expr is None:
                    group_fns.append(out_fns[k - 1])
                    continue
                g = expr
            try:
                group_fns.append(_COMPILER.fn(g, noagg))
            except SQLError as e:
                if "misuse of aggregate" in str(e):
                    raise SQLError(
                        "aggregate functions are not allowed in the GROUP BY clause"
                    ) from None
                raise

        having = _COMPILER.fn(stmt.having, ctx) if stmt.having is not None else None

        # ORDER BY terms: either an output column index or a closure over the row.
        order_keys: list[int | Fn] = []
        for term in stmt.order_by:
            e = term.expr
            if isinstance(e, n.Literal) and isinstance(e.value, int):
                k = e.value
                if not 1 <= k <= ncols:
                    raise SQLError(
                        f"ORDER BY term out of range - should be between 1 and {ncols}"
                    )
                order_keys.append(k - 1)
                continue
            if isinstance(e, n.Column) and e.table is None and e.name.lower() in out_names:
                order_keys.append(out_names.index(e.name.lower()))
                continue
            order_keys.append(_COMPILER.fn(e, ctx))

        is_agg = bool(stmt.group_by) or having is not None or bool(aggs)
        if having is not None and not stmt.group_by and not aggs:
            # SQLite allows HAVING without GROUP BY only in aggregate queries.
            raise SQLError("HAVING clause on a non-aggregate query")

        results: list[tuple[tuple, list]] = []

        def emit(r: list) -> None:
            out = tuple(f(r) for f in out_fns)
            keys = [out[k] if isinstance(k, int) else k(r) for k in order_keys]
            results.append((out, keys))

        if where is not None:
            rows = [r for r in rows if truth(where(r))]

        if not is_agg:
            for r in rows:
                emit(r)
        else:
            if group_fns:
                groups: dict[tuple, list[list]] = {}
                for r in rows:
                    key = tuple(f(r) for f in group_fns)
                    groups.setdefault(key, []).append(r)
                ordered = sorted(
                    groups.items(),
                    key=functools.cmp_to_key(lambda a, b: _cmp_tuple(a[0], b[0])),
                )
                group_list = [g for _, g in ordered]
            else:
                group_list = [rows]
            null_row = [None] * width
            for grp in group_list:
                agg_vals = []
                rep = grp[0] if grp else null_row
                for spec in aggs:
                    val, sel = self._aggregate(spec, grp)
                    agg_vals.append(val)
                    if len(aggs) == 1 and spec.name in ("MIN", "MAX") and sel is not None:
                        rep = grp[sel]
                ext = rep + agg_vals
                if having is not None and not truth(having(ext)):
                    continue
                emit(ext)

        if stmt.distinct:
            seen: set[tuple] = set()
            unique = []
            for out, keys in results:
                if out not in seen:
                    seen.add(out)
                    unique.append((out, keys))
            results = unique

        if order_keys:
            terms = stmt.order_by

            def cmp(a, b):
                ka, kb = a[1], b[1]
                for i, term in enumerate(terms):
                    x, y = ka[i], kb[i]
                    if x is None or y is None:
                        if x is None and y is None:
                            continue
                        nulls_first = term.nulls_first
                        if nulls_first is None:
                            nulls_first = not term.desc
                        return -1 if (x is None) == nulls_first else 1
                    c = compare(x, y)
                    if c:
                        return -c if term.desc else c
                return 0

            results.sort(key=functools.cmp_to_key(cmp))

        offset = _limit_value(stmt.offset, "OFFSET")
        limit = _limit_value(stmt.limit, "LIMIT")
        out_rows = [out for out, _ in results]
        if offset is not None and offset > 0:
            out_rows = out_rows[offset:]
        if limit is not None and limit >= 0:
            out_rows = out_rows[:limit]
        return out_rows

    @staticmethod
    def _aggregate(spec: AggSpec, rows: list[list]):
        if spec.star:
            return len(rows), None
        f = spec.args[0]
        values = [f(r) for r in rows]
        seps = None
        if len(spec.args) > 1:
            fs = spec.args[1]
            seps = [fs(r) for r in rows]
        if spec.distinct:
            seen: set = set()
            uniq = []
            for v in values:
                if v is None or v in seen:
                    continue
                seen.add(v)
                uniq.append(v)
            if spec.name in ("MIN", "MAX"):
                val, _ = compute_aggregate(spec.name, uniq)
                return val, None
            return compute_aggregate(spec.name, uniq)[0], None
        return compute_aggregate(spec.name, values, seps)


def _cmp_tuple(a: tuple, b: tuple) -> int:
    for x, y in zip(a, b, strict=True):
        c = sort_compare(x, y)
        if c:
            return c
    return 0
