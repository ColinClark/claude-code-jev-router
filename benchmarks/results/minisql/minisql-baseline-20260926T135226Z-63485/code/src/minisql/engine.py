"""Query compilation and execution."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from operator import itemgetter

from . import ast
from . import values as V
from .aggregates import is_aggregate_call, make_accumulator
from .errors import SQLError
from .parser import parse

Row = tuple
Fn = Callable[[Row], object]


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
    name: str  # lower-case name the table is referenced by (alias or table name)
    table: Table
    offset: int


@dataclass
class AggSpec:
    name: str
    arg: Fn | None
    star: bool
    distinct: bool


class Context:
    """Name-resolution and aggregate-collection state for compiling expressions."""

    def __init__(
        self,
        sources: list[Source],
        aggs: list[AggSpec] | None = None,
        agg_base: int = 0,
        aliases: dict[str, ast.Expr] | None = None,
        clause: str = "",
    ):
        self.sources = sources
        self.aggs = aggs
        self.agg_base = agg_base
        self.aliases = aliases
        self.clause = clause

    def derive(self, **changes) -> Context:
        ctx = Context(self.sources, self.aggs, self.agg_base, self.aliases, self.clause)
        for key, value in changes.items():
            setattr(ctx, key, value)
        return ctx


def _ordinal(n: int) -> str:
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n if n < 20 else n % 10, "th")
    return f"{n}{suffix}"


class Database:
    """An in-memory SQL database."""

    def __init__(self):
        self.tables: dict[str, Table] = {}

    # ---------------------------------------------------------------- API

    def execute(self, sql: str) -> list[tuple]:
        if not isinstance(sql, str):
            raise SQLError("SQL must be a string")
        # Parsing, compiling and evaluating are recursive in expression depth; allow
        # roughly SQLite's default maximum expression depth of 1000.
        limit = sys.getrecursionlimit()
        if limit < 20000:
            sys.setrecursionlimit(20000)
        try:
            return self._execute(parse(sql))
        except RecursionError:
            raise SQLError("expression tree is too large") from None
        finally:
            sys.setrecursionlimit(limit)

    def _execute(self, stmt: ast.Statement) -> list[tuple]:
        if isinstance(stmt, ast.Select):
            return self._select(stmt)
        if isinstance(stmt, ast.CreateTable):
            self._create(stmt)
        elif isinstance(stmt, ast.DropTable):
            self._drop(stmt)
        elif isinstance(stmt, ast.Insert):
            self._insert(stmt)
        elif isinstance(stmt, ast.Update):
            self._update(stmt)
        elif isinstance(stmt, ast.Delete):
            self._delete(stmt)
        return []

    # ---------------------------------------------------------------- DDL

    def _table(self, name: str) -> Table:
        table = self.tables.get(name.lower())
        if table is None:
            raise SQLError(f"no such table: {name}")
        return table

    def _create(self, stmt: ast.CreateTable) -> None:
        key = stmt.name.lower()
        if key in self.tables:
            if stmt.if_not_exists:
                return
            raise SQLError(f"table {stmt.name} already exists")
        seen = set()
        for col in stmt.columns:
            if col.name.lower() in seen:
                raise SQLError(f"duplicate column name: {col.name}")
            seen.add(col.name.lower())
        self.tables[key] = Table(
            stmt.name,
            [c.name for c in stmt.columns],
            [V.type_affinity(c.type_name) for c in stmt.columns],
        )

    def _drop(self, stmt: ast.DropTable) -> None:
        key = stmt.name.lower()
        if key not in self.tables:
            if stmt.if_exists:
                return
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[key]

    # ---------------------------------------------------------------- DML

    def _insert(self, stmt: ast.Insert) -> None:
        table = self._table(stmt.table)
        if stmt.columns is None:
            targets = list(range(len(table.columns)))
        else:
            targets = []
            for name in stmt.columns:
                idx = table.index.get(name.lower())
                if idx is None:
                    raise SQLError(f"table {table.name} has no column named {name}")
                if idx in targets:
                    raise SQLError(f"duplicate column name: {name}")
                targets.append(idx)
        if stmt.select is not None:
            source_rows = self._select(stmt.select)
            if source_rows and len(source_rows[0]) != len(targets):
                raise SQLError(
                    f"table {table.name} has {len(table.columns)} columns "
                    f"but {len(source_rows[0])} values were supplied"
                )
        else:
            ctx = Context([], clause="VALUES")
            source_rows = []
            for exprs in stmt.rows or []:
                if len(exprs) != len(targets):
                    if stmt.columns is None:
                        raise SQLError(
                            f"table {table.name} has {len(targets)} columns "
                            f"but {len(exprs)} values were supplied"
                        )
                    raise SQLError(f"{len(exprs)} values for {len(targets)} columns")
                fns = [self._compile(e, ctx)[0] for e in exprs]
                source_rows.append(tuple(fn(()) for fn in fns))
        new_rows = []
        width = len(table.columns)
        for values in source_rows:
            row = [None] * width
            for idx, value in zip(targets, values, strict=True):
                row[idx] = V.apply_affinity(value, table.affinities[idx])
            new_rows.append(row)
        table.rows.extend(new_rows)

    def _single_table_context(self, table: Table, clause: str) -> Context:
        return Context([Source(table.name.lower(), table, 0)], clause=clause)

    def _update(self, stmt: ast.Update) -> None:
        table = self._table(stmt.table)
        ctx = self._single_table_context(table, "UPDATE")
        assignments = []
        for name, expr in stmt.assignments:
            idx = table.index.get(name.lower())
            if idx is None:
                raise SQLError(f"no such column: {name}")
            assignments.append((idx, self._compile(expr, ctx)[0]))
        where = self._compile_predicate(stmt.where, ctx.derive(clause="WHERE"))
        updates = []
        for i, row in enumerate(table.rows):
            t = tuple(row)
            if where is None or V.truth(where(t)):
                updates.append((i, [(idx, fn(t)) for idx, fn in assignments]))
        for i, changes in updates:
            row = table.rows[i]
            for idx, value in changes:
                row[idx] = V.apply_affinity(value, table.affinities[idx])

    def _delete(self, stmt: ast.Delete) -> None:
        table = self._table(stmt.table)
        ctx = self._single_table_context(table, "WHERE")
        where = self._compile_predicate(stmt.where, ctx)
        if where is None:
            table.rows = []
        else:
            table.rows = [row for row in table.rows if not V.truth(where(tuple(row)))]

    def _compile_predicate(self, expr: ast.Expr | None, ctx: Context) -> Fn | None:
        return None if expr is None else self._compile(expr, ctx)[0]

    # ------------------------------------------------------------- SELECT

    def _build_sources(self, stmt: ast.Select) -> list[Source]:
        sources: list[Source] = []
        offset = 0
        refs = [stmt.from_] + [j.table for j in stmt.joins] if stmt.from_ else []
        for ref in refs:
            table = self._table(ref.name)
            name = (ref.alias or ref.name).lower()
            if any(s.name == name for s in sources):
                raise SQLError(f"ambiguous table name: {ref.alias or ref.name}")
            sources.append(Source(name, table, offset))
            offset += len(table.columns)
        return sources

    def _scan(self, stmt: ast.Select, sources: list[Source], aliases) -> list[Row]:
        if not sources:
            return [()]
        rows: list[Row] = [tuple(r) for r in sources[0].table.rows]
        for k, join in enumerate(stmt.joins, start=1):
            source = sources[k]
            right_rows = [tuple(r) for r in source.table.rows]
            on = None
            if join.on is not None:
                ctx = Context(sources[: k + 1], aliases=aliases, clause="ON")
                on = self._compile(join.on, ctx)[0]
            null_row = (None,) * len(source.table.columns)
            probe = None
            if join.on is not None:
                probe = self._hash_probe(join.on, ctx, source, right_rows)
            joined = []
            for left in rows:
                matched = False
                candidates = right_rows if probe is None else probe(left)
                for right in candidates:
                    combined = left + right
                    if on is None or V.truth(on(combined)):
                        joined.append(combined)
                        matched = True
                if join.kind == "LEFT" and not matched:
                    joined.append(left + null_row)
            rows = joined
        return rows

    def _hash_probe(self, on: ast.Expr, ctx: Context, source: Source, right_rows):
        """For an ON clause containing ``left_col = right_col``, index the right rows by value.

        Returns a function mapping a left row to the right rows that can satisfy that
        equality (the full ON condition is still evaluated), or None if not applicable.
        """
        terms = [on]
        while terms and not (isinstance(terms[0], ast.Binary) and terms[0].op == "="):
            term = terms.pop(0)
            if isinstance(term, ast.Binary) and term.op == "AND":
                terms[:0] = [term.left, term.right]
        for term in terms:
            if not (isinstance(term, ast.Binary) and term.op == "="):
                continue
            if not (isinstance(term.left, ast.Column) and isinstance(term.right, ast.Column)):
                continue
            try:
                lf, la = self._resolve(term.left, ctx.derive(aliases=None))
                rf, ra = self._resolve(term.right, ctx.derive(aliases=None))
            except SQLError:
                return None
            l_right = _is_right(lf, source)
            r_right = _is_right(rf, source)
            if l_right == r_right:
                continue
            left_fn, right_fn = (rf, lf) if l_right else (lf, rf)
            aff = V.comparison_affinity(la, ra)
            index: dict = {}
            pad = (None,) * source.offset
            for right in right_rows:
                value = right_fn(pad + right)
                if value is None:
                    continue
                if aff is not None:
                    value = V.apply_affinity(value, aff)
                index.setdefault(value, []).append(right)

            def probe(left, left_fn=left_fn, aff=aff, index=index):
                value = left_fn(left)
                if value is None:
                    return ()
                if aff is not None:
                    value = V.apply_affinity(value, aff)
                return index.get(value, ())

            return probe
        return None

    def _select(self, stmt: ast.Select) -> list[tuple]:
        sources = self._build_sources(stmt)
        width = sum(len(s.table.columns) for s in sources)

        # Expand stars into column references.
        items: list[tuple[ast.Expr | None, int | None, str | None]] = []
        for item in stmt.items:
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
                    for i in range(len(s.table.columns)):
                        items.append((None, s.offset + i, None))
            else:
                items.append((item.expr, None, item.alias))

        aliases: dict[str, ast.Expr] = {}
        for expr, _, alias in items:
            if alias is not None and alias.lower() not in aliases:
                aliases[alias.lower()] = expr

        is_agg = bool(stmt.group_by) or any(
            expr is not None and _contains_aggregate(expr) for expr, _, _ in items
        )
        if stmt.having is not None and not is_agg:
            if not _contains_aggregate(stmt.having):
                raise SQLError("HAVING clause on a non-aggregate query")
            is_agg = True

        rows = self._scan(stmt, sources, aliases)

        base_ctx = Context(sources, aliases=aliases)
        if stmt.where is not None:
            where = self._compile(stmt.where, base_ctx.derive(clause="WHERE"))[0]
            rows = [r for r in rows if V.truth(where(r))]

        aggs: list[AggSpec] | None = [] if is_agg else None
        out_ctx = base_ctx.derive(aggs=aggs, agg_base=width, clause="SELECT")

        item_fns: list[Fn] = []
        item_affs: list[str | None] = []
        for expr, index, _ in items:
            if expr is None:
                item_fns.append(itemgetter(index))
                item_affs.append(_source_affinity(sources, index))
            else:
                fn, aff = self._compile(expr, out_ctx)
                item_fns.append(fn)
                item_affs.append(aff)

        having = None
        if stmt.having is not None:
            having = self._compile(stmt.having, out_ctx.derive(clause="HAVING"))[0]

        # ORDER BY terms: ("out", index) refers to an output column, ("ctx", fn) to an expression.
        order_terms: list[tuple[str, object, bool]] = []
        for pos, term in enumerate(stmt.order_by, start=1):
            order_terms.append(self._order_term(term, pos, items, out_ctx) + (term.desc,))

        if is_agg:
            group_fns = [
                self._group_term(g, items, out_ctx.derive(aggs=None, clause="GROUP BY"))
                for g in stmt.group_by
            ]
            contexts = self._aggregate(rows, group_fns, aggs or [], width, bool(stmt.group_by))
            if having is not None:
                contexts = [c for c in contexts if V.truth(having(c))]
        else:
            contexts = rows

        results = [(tuple(fn(c) for fn in item_fns), c) for c in contexts]

        if stmt.distinct:
            seen = set()
            unique = []
            for out, c in results:
                if out not in seen:
                    seen.add(out)
                    unique.append((out, c))
            results = unique

        for kind, ref, desc in reversed(order_terms):
            if kind == "out":
                results.sort(key=lambda rc, i=ref: V.sort_key(rc[0][i]), reverse=desc)
            else:
                results.sort(key=lambda rc, f=ref: V.sort_key(f(rc[1])), reverse=desc)

        output = [out for out, _ in results]
        if stmt.limit is not None or stmt.offset is not None:
            offset = self._limit_value(stmt.offset) if stmt.offset is not None else 0
            limit = self._limit_value(stmt.limit) if stmt.limit is not None else -1
            offset = max(offset, 0)
            output = output[offset:] if limit < 0 else output[offset : offset + limit]
        return output

    def _limit_value(self, expr: ast.Expr) -> int:
        value = self._compile(expr, Context([], clause="LIMIT"))[0](())
        value = V.apply_affinity(value, V.NUMERIC)
        if not isinstance(value, int):
            raise SQLError("datatype mismatch")
        return value

    def _order_term(self, term, pos: int, items, ctx: Context) -> tuple[str, object]:
        expr = term.expr
        n = _int_constant(expr)
        if n is not None:
            if not 1 <= n <= len(items):
                raise SQLError(
                    f"{_ordinal(pos)} ORDER BY term out of range - "
                    f"should be between 1 and {len(items)}"
                )
            return ("out", n - 1)
        if isinstance(expr, ast.Column) and expr.table is None:
            name = expr.name.lower()
            for i, (_, _, alias) in enumerate(items):
                if alias is not None and alias.lower() == name:
                    return ("out", i)
        return ("ctx", self._compile(expr, ctx.derive(clause="ORDER BY"))[0])

    def _group_term(self, expr: ast.Expr, items, ctx: Context) -> Fn:
        n = _int_constant(expr)
        if n is not None:
            if not 1 <= n <= len(items):
                raise SQLError(
                    f"GROUP BY term out of range - should be between 1 and {len(items)}"
                )
            item_expr, index, _ = items[n - 1]
            if item_expr is None:
                return itemgetter(index)
            if _contains_aggregate(item_expr):
                raise SQLError("aggregate functions are not allowed in the GROUP BY clause")
            return self._compile(item_expr, ctx)[0]
        return self._compile(expr, ctx)[0]

    def _aggregate(self, rows, group_fns, aggs: list[AggSpec], width: int, grouped: bool):
        # Bare columns come from the group's first row, unless the query has min()/max():
        # then from the latest row on which the last executed min()/max() was updated.
        minmax = {i for i, spec in enumerate(aggs) if spec.name in ("MIN", "MAX")}
        groups: dict[tuple, list] = {}
        for row in rows:
            key = tuple(g(row) for g in group_fns)
            group = groups.get(key)
            if group is None:
                accs = [make_accumulator(s.name, s.star, s.distinct) for s in aggs]
                group = groups[key] = [row, accs, False]
            accs = group[1]
            for i, spec in enumerate(aggs):
                loaded = accs[i].step(None if spec.arg is None else spec.arg(row))
                if i in minmax and loaded is not None:
                    group[2] = not loaded
            if minmax and not group[2]:
                group[0] = row
        if not groups and not grouped:
            accs = [make_accumulator(s.name, s.star, s.distinct) for s in aggs]
            groups[()] = [(None,) * width, accs, False]
        return [rep + tuple(acc.final() for acc in accs) for rep, accs, _ in groups.values()]

    # -------------------------------------------------------- expressions

    def _resolve(self, col: ast.Column, ctx: Context):
        name = col.name.lower()
        if col.table is not None:
            table_name = col.table.lower()
            for source in ctx.sources:
                if source.name == table_name:
                    idx = source.table.index.get(name)
                    if idx is None:
                        break
                    return itemgetter(source.offset + idx), source.table.affinities[idx]
            raise SQLError(f"no such column: {col.table}.{col.name}")
        hits = []
        for source in ctx.sources:
            idx = source.table.index.get(name)
            if idx is not None:
                hits.append((source, idx))
        if len(hits) > 1:
            raise SQLError(f"ambiguous column name: {col.name}")
        if hits:
            source, idx = hits[0]
            return itemgetter(source.offset + idx), source.table.affinities[idx]
        if ctx.aliases and name in ctx.aliases:
            target = ctx.aliases[name]
            if ctx.aggs is None and _contains_aggregate(target):
                raise SQLError(f"misuse of aliased aggregate {col.name}")
            return self._compile(target, ctx.derive(aliases=None))
        raise SQLError(f"no such column: {col.name}")

    def _compile(self, expr: ast.Expr, ctx: Context) -> tuple[Fn, str | None]:
        """Compile an expression to (function of a row, affinity)."""
        if isinstance(expr, ast.Literal):
            value = expr.value
            return (lambda r: value), None
        if isinstance(expr, ast.Column):
            return self._resolve(expr, ctx)
        if isinstance(expr, ast.Binary):
            return self._compile_binary(expr, ctx), None
        if isinstance(expr, ast.Unary):
            fn, aff = self._compile(expr.operand, ctx)
            if expr.op == "-":
                return (lambda r: V.negate(fn(r))), None
            if expr.op == "+":
                return fn, None  # unary plus is a no-op that strips affinity

            def not_(r):
                t = V.truth(fn(r))
                return None if t is None else int(not t)

            return not_, None
        if isinstance(expr, ast.InList):
            return self._compile_in(expr, ctx), None
        if isinstance(expr, ast.Between):
            both = ast.Binary(
                "AND",
                ast.Binary(">=", expr.operand, expr.low),
                ast.Binary("<=", expr.operand, expr.high),
            )
            return self._compile(ast.Unary("NOT", both) if expr.negated else both, ctx)
        if isinstance(expr, ast.Like):
            return self._compile_like(expr, ctx), None
        if isinstance(expr, ast.Func):
            return self._compile_func(expr, ctx)
        if isinstance(expr, ast.Case):
            return self._compile_case(expr, ctx), None
        if isinstance(expr, ast.Cast):
            return self._compile_cast(expr, ctx)
        raise SQLError(f"unsupported expression: {expr!r}")

    def _compile_binary(self, expr: ast.Binary, ctx: Context) -> Fn:
        op = expr.op
        lf, la = self._compile(expr.left, ctx)
        rf, ra = self._compile(expr.right, ctx)
        if op == "AND":

            def and_(r):
                a = V.truth(lf(r))
                if a is False:
                    return 0
                b = V.truth(rf(r))
                if b is False:
                    return 0
                return None if a is None or b is None else 1

            return and_
        if op == "OR":

            def or_(r):
                a = V.truth(lf(r))
                if a is True:
                    return 1
                b = V.truth(rf(r))
                if b is True:
                    return 1
                return None if a is None or b is None else 0

            return or_
        if op in ("=", "!=", "<", "<=", ">", ">=", "IS", "IS NOT"):
            return _comparison(op, lf, rf, V.comparison_affinity(la, ra))
        arith = {
            "+": V.add,
            "-": V.subtract,
            "*": V.multiply,
            "/": V.divide,
            "%": V.remainder,
            "||": V.concat,
        }[op]
        return lambda r: arith(lf(r), rf(r))

    def _compile_in(self, expr: ast.InList, ctx: Context) -> Fn:
        fn, aff = self._compile(expr.operand, ctx)
        item_fns = [self._compile(item, ctx)[0] for item in expr.items]
        if aff in (V.INTEGER, V.REAL, V.NUMERIC):
            aff = V.NUMERIC
        elif aff != V.TEXT:
            aff = None
        negated = expr.negated

        def in_(r):
            if not item_fns:
                return int(negated)
            value = fn(r)
            if value is None:
                return None
            if aff is not None:
                value = V.apply_affinity(value, aff)
            key = V.sort_key(value)
            saw_null = False
            for item in item_fns:
                other = item(r)
                if other is None:
                    saw_null = True
                    continue
                if aff is not None:
                    other = V.apply_affinity(other, aff)
                if V.sort_key(other) == key:
                    return 0 if negated else 1
            if saw_null:
                return None
            return 1 if negated else 0

        return in_

    def _compile_like(self, expr: ast.Like, ctx: Context) -> Fn:
        vf = self._compile(expr.operand, ctx)[0]
        pf = self._compile(expr.pattern, ctx)[0]
        ef = self._compile(expr.escape, ctx)[0] if expr.escape is not None else None
        negated = expr.negated

        def like_(r):
            escape = None
            if ef is not None:
                escape = ef(r)
                if escape is None:
                    return None
            result = V.like(vf(r), pf(r), escape)
            if result is None or not negated:
                return result
            return 1 - result

        return like_

    def _compile_case(self, expr: ast.Case, ctx: Context) -> Fn:
        whens = []
        if expr.operand is not None:
            of, oa = self._compile(expr.operand, ctx)
            for cond, result in expr.whens:
                cf, ca = self._compile(cond, ctx)
                test = _comparison("=", of, cf, V.comparison_affinity(oa, ca))
                whens.append((test, self._compile(result, ctx)[0]))
        else:
            for cond, result in expr.whens:
                whens.append((self._compile(cond, ctx)[0], self._compile(result, ctx)[0]))
        else_fn = self._compile(expr.else_, ctx)[0] if expr.else_ is not None else None

        def case_(r):
            for test, result in whens:
                if V.truth(test(r)):
                    return result(r)
            return None if else_fn is None else else_fn(r)

        return case_

    def _compile_cast(self, expr: ast.Cast, ctx: Context):
        fn = self._compile(expr.operand, ctx)[0]
        aff = V.type_affinity(expr.type_name)

        def cast_(r):
            value = fn(r)
            if value is None:
                return None
            if aff == V.INTEGER:
                return V.to_integer(value)
            if aff == V.REAL:
                return V.to_real(value)
            if aff == V.TEXT:
                return V.to_text(value)
            if aff == V.NUMERIC:
                if isinstance(value, str):
                    value = V.to_number(value)
                return V.apply_affinity(value, V.NUMERIC)
            return value

        return cast_, aff

    def _compile_func(self, expr: ast.Func, ctx: Context):
        name = expr.name
        nargs = len(expr.args)
        if is_aggregate_call(name, nargs, expr.star):
            if ctx.aggs is None:
                raise SQLError(f"misuse of aggregate function {name.lower()}()")
            if expr.star and name != "COUNT":
                raise SQLError(f"wrong number of arguments to function {name.lower()}()")
            arg = None
            if not expr.star:
                if name == "COUNT" and nargs == 0:
                    expr = ast.Func(name, (), star=True)
                elif nargs != 1:
                    raise SQLError(f"wrong number of arguments to function {name.lower()}()")
                else:
                    arg = self._compile(expr.args[0], ctx.derive(aggs=None))[0]
            ctx.aggs.append(AggSpec(name, arg, expr.star, expr.distinct))
            idx = ctx.agg_base + len(ctx.aggs) - 1
            return itemgetter(idx), None
        spec = SCALAR_FUNCTIONS.get(name)
        if spec is None:
            raise SQLError(f"no such function: {name.lower()}")
        impl, min_args, max_args = spec
        if expr.star or expr.distinct or not (min_args <= nargs <= max_args):
            raise SQLError(f"wrong number of arguments to function {name.lower()}()")
        fns = [self._compile(a, ctx)[0] for a in expr.args]
        return (lambda r: impl(*[f(r) for f in fns])), None


# ------------------------------------------------------------------ helpers


def _comparison(op: str, lf: Fn, rf: Fn, aff) -> Fn:
    null_safe = op in ("IS", "IS NOT")
    if op in ("=", "IS"):
        test = int.__eq__
    elif op in ("!=", "IS NOT"):
        test = int.__ne__
    elif op == "<":
        test = int.__lt__
    elif op == "<=":
        test = int.__le__
    elif op == ">":
        test = int.__gt__
    else:
        test = int.__ge__

    def cmp(r):
        a = lf(r)
        b = rf(r)
        if a is None or b is None:
            if not null_safe:
                return None
            return int(test(0 if a is b else 1, 0))
        if aff is not None:
            a = V.apply_affinity(a, aff)
            b = V.apply_affinity(b, aff)
        return int(test(V.compare(a, b), 0))

    return cmp


def _is_right(getter, source: Source) -> bool:
    """Whether a column getter reads from ``source`` (the table being joined)."""
    marker = (False,) * source.offset + (True,) * len(source.table.columns)
    return bool(getter(marker))


def _int_constant(expr) -> int | None:
    """Value of an integer literal term such as ``2`` or ``-1`` (ORDER BY/GROUP BY positions)."""
    if isinstance(expr, ast.Literal) and isinstance(expr.value, int):
        return expr.value
    if isinstance(expr, ast.Unary) and expr.op in ("-", "+"):
        inner = _int_constant(expr.operand)
        if inner is not None:
            return -inner if expr.op == "-" else inner
    return None


def _source_affinity(sources: list[Source], index: int):
    for s in sources:
        if s.offset <= index < s.offset + len(s.table.columns):
            return s.table.affinities[index - s.offset]
    return None


def _contains_aggregate(expr) -> bool:
    if isinstance(expr, ast.Func):
        if is_aggregate_call(expr.name, len(expr.args), expr.star):
            return True
        return any(_contains_aggregate(a) for a in expr.args)
    if isinstance(expr, ast.Binary):
        return _contains_aggregate(expr.left) or _contains_aggregate(expr.right)
    if isinstance(expr, ast.Unary):
        return _contains_aggregate(expr.operand)
    if isinstance(expr, ast.InList):
        return _contains_aggregate(expr.operand) or any(map(_contains_aggregate, expr.items))
    if isinstance(expr, ast.Between):
        return any(map(_contains_aggregate, (expr.operand, expr.low, expr.high)))
    if isinstance(expr, ast.Like):
        parts = [expr.operand, expr.pattern] + ([expr.escape] if expr.escape else [])
        return any(map(_contains_aggregate, parts))
    if isinstance(expr, ast.Case):
        parts = [expr.operand, expr.else_] + [x for pair in expr.whens for x in pair]
        return any(_contains_aggregate(p) for p in parts if p is not None)
    if isinstance(expr, ast.Cast):
        return _contains_aggregate(expr.operand)
    return False


def _abs(x):
    if x is None:
        return None
    if isinstance(x, int):
        if x == V.INT64_MIN:
            raise SQLError("integer overflow")
        return abs(x)
    return abs(V.to_real(x))


def _coalesce(*args):
    for a in args:
        if a is not None:
            return a
    return None


def _nullif(a, b):
    if a is not None and b is not None and V.compare(a, b) == 0:
        return None
    return a


def _length(x):
    if x is None:
        return None
    return len(V.to_text(x))


def _lower(x):
    return None if x is None else "".join(
        c.lower() if c.isascii() else c for c in V.to_text(x)
    )


def _upper(x):
    return None if x is None else "".join(
        c.upper() if c.isascii() else c for c in V.to_text(x)
    )


def _scalar_minmax(sign: int):
    def fn(*args):
        best = None
        for i, a in enumerate(args):
            if a is None:
                return None
            if i == 0 or V.compare(a, best) * sign > 0:
                best = a
        return best

    return fn


SCALAR_FUNCTIONS: dict[str, tuple[Callable, int, int]] = {
    "ABS": (_abs, 1, 1),
    "COALESCE": (_coalesce, 2, 1000),
    "IFNULL": (_coalesce, 2, 2),
    "NULLIF": (_nullif, 2, 2),
    "LENGTH": (_length, 1, 1),
    "LOWER": (_lower, 1, 1),
    "UPPER": (_upper, 1, 1),
    "TYPEOF": (V.typeof, 1, 1),
    "MIN": (_scalar_minmax(-1), 2, 1000),
    "MAX": (_scalar_minmax(1), 2, 1000),
}
