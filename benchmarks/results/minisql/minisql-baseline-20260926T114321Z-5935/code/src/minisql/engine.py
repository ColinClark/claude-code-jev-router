"""Statement execution."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ast
from . import values as V
from .aggregates import evaluate, representative_row
from .compiler import (
    AggSpec,
    Ctx,
    Fn,
    Scope,
    children,
    comparison_conversions,
    compile_expr,
    contains_aggregate,
)
from .errors import SQLError
from .parser import parse


@dataclass
class Table:
    name: str
    columns: list[str]  # lower-case names
    affinities: list[str]
    rows: list[tuple] = field(default_factory=list)


class Database:
    """An in-memory SQL database."""

    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}

    def execute(self, sql: str) -> list[tuple]:
        """Execute one SQL statement. SELECT returns its rows; other statements return []."""
        if not isinstance(sql, str):
            raise SQLError("SQL must be a string")
        try:
            stmt = parse(sql)
            if isinstance(stmt, ast.Select):
                return self._select(stmt)
            handler = {
                ast.CreateTable: self._create,
                ast.DropTable: self._drop,
                ast.Insert: self._insert,
                ast.Update: self._update,
                ast.Delete: self._delete,
            }[type(stmt)]
            handler(stmt)
            return []
        except RecursionError:
            raise SQLError("expression tree is too large") from None

    # -- helpers -------------------------------------------------------------

    def _table(self, name: str) -> Table:
        t = self.tables.get(name.lower())
        if t is None:
            raise SQLError(f"no such table: {name}")
        return t

    @staticmethod
    def _table_scope(t: Table, key: str | None = None) -> Scope:
        scope = Scope()
        scope.add(key or t.name.lower(), t.columns, t.affinities)
        return scope

    @staticmethod
    def _column_index(t: Table, name: str) -> int:
        try:
            return t.columns.index(name.lower())
        except ValueError:
            raise SQLError(f"table {t.name} has no column named {name}") from None

    # -- DDL -----------------------------------------------------------------

    def _create(self, stmt: ast.CreateTable) -> None:
        key = stmt.name.lower()
        if key in self.tables:
            if stmt.if_not_exists:
                return
            raise SQLError(f"table {stmt.name} already exists")
        names = [c.name.lower() for c in stmt.columns]
        if len(set(names)) != len(names):
            dup = next(n for n in names if names.count(n) > 1)
            raise SQLError(f"duplicate column name: {dup}")
        affs = [V.affinity_of_type(c.type_name) for c in stmt.columns]
        self.tables[key] = Table(stmt.name, names, affs)

    def _drop(self, stmt: ast.DropTable) -> None:
        key = stmt.name.lower()
        if key not in self.tables:
            if stmt.if_exists:
                return
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[key]

    # -- DML -----------------------------------------------------------------

    def _insert(self, stmt: ast.Insert) -> None:
        t = self._table(stmt.table)
        if stmt.columns is None:
            targets = list(range(len(t.columns)))
        else:
            targets = [self._column_index(t, c) for c in stmt.columns]
        ctx = Ctx(Scope())
        new_rows = []
        for row in stmt.rows:
            if len(row) != len(targets):
                if stmt.columns is None:
                    raise SQLError(
                        f"table {t.name} has {len(t.columns)} columns but {len(row)} values were supplied"
                    )
                raise SQLError(f"{len(row)} values for {len(targets)} columns")
            out = [None] * len(t.columns)
            for idx, e in zip(targets, row, strict=True):
                out[idx] = V.apply_storage_affinity(compile_expr(e, ctx)[0](()), t.affinities[idx])
            new_rows.append(tuple(out))
        t.rows.extend(new_rows)

    def _where(self, where: ast.Expr | None, ctx: Ctx) -> Fn | None:
        if where is None:
            return None
        return compile_expr(where, ctx)[0]

    def _update(self, stmt: ast.Update) -> None:
        t = self._table(stmt.table)
        ctx = Ctx(self._table_scope(t))
        sets = [(self._column_index(t, c), compile_expr(e, ctx)[0]) for c, e in stmt.assignments]
        where = self._where(stmt.where, ctx)
        truth = V.truth
        new_rows = []
        for r in t.rows:
            if where is None or truth(where(r)):
                out = list(r)
                for idx, f in sets:
                    out[idx] = V.apply_storage_affinity(f(r), t.affinities[idx])
                new_rows.append(tuple(out))
            else:
                new_rows.append(r)
        t.rows = new_rows

    def _delete(self, stmt: ast.Delete) -> None:
        t = self._table(stmt.table)
        where = self._where(stmt.where, Ctx(self._table_scope(t)))
        if where is None:
            t.rows = []
            return
        truth = V.truth
        t.rows = [r for r in t.rows if not truth(where(r))]

    # -- SELECT --------------------------------------------------------------

    def _from(self, stmt: ast.Select) -> tuple[Scope, list[tuple]]:
        """Build the scope and the joined source rows of a SELECT."""
        scope = Scope()
        if stmt.source is None:
            return scope, [()]
        first = self._table(stmt.source.name)
        scope.add(stmt.source.key, first.columns, first.affinities)
        rows = first.rows
        truth = V.truth
        for join in stmt.joins:
            t = self._table(join.table.name)
            left_width = scope.width
            scope.add(join.table.key, t.columns, t.affinities)
            on = None
            if join.on is not None:
                on = compile_expr(join.on, Ctx(scope))[0]
            pad = (None,) * len(t.columns)
            keys = _equi_join_keys(join.on, scope, left_width) if join.on is not None else None
            if keys is None:
                candidates = lambda left, right=t.rows: right  # noqa: E731
            else:
                left_key, right_key = keys
                buckets: dict[object, list[tuple]] = {}
                for rr in t.rows:
                    k = right_key(rr)
                    if k is not None:
                        buckets.setdefault(k, []).append(rr)
                empty: list[tuple] = []

                def candidates(left, left_key=left_key, buckets=buckets, empty=empty):
                    k = left_key(left)
                    return empty if k is None else buckets.get(k, empty)

            out = []
            for left in rows:
                matched = False
                for rr in candidates(left):
                    combined = left + rr
                    if on is None or truth(on(combined)):
                        out.append(combined)
                        matched = True
                if not matched and join.kind == "LEFT":
                    out.append(left + pad)
            rows = out
        return scope, rows

    def _expand_items(self, stmt: ast.Select, scope: Scope) -> list[tuple[ast.Expr | int, str | None]]:
        """Expand stars; each output column is an expression or a source column index."""
        items: list[tuple[ast.Expr | int, str | None]] = []
        for item in stmt.items:
            if item.expr is not None:
                items.append((item.expr, item.alias))
                continue
            if item.star_table is None:
                if not scope.tables:
                    raise SQLError("no tables specified")
                items.extend((i, None) for i in range(scope.width))
                continue
            key = item.star_table.lower()
            matched = [t for t in scope.tables if t.key == key]
            if not matched:
                raise SQLError(f"no such table: {item.star_table}")
            for t in matched:
                items.extend((t.start + i, None) for i in range(len(t.columns)))
        return items

    def _select(self, stmt: ast.Select) -> list[tuple]:
        scope, rows = self._from(stmt)
        items = self._expand_items(stmt, scope)
        aliases: dict[str, ast.Expr] = {}
        for e, alias in items:
            if alias is not None and not isinstance(e, int):
                aliases.setdefault(alias.lower(), e)

        truth = V.truth
        if stmt.where is not None:
            where = compile_expr(stmt.where, Ctx(scope, aliases))[0]
            rows = [r for r in rows if truth(where(r))]

        is_agg = (
            bool(stmt.group_by)
            or stmt.having is not None
            or any(not isinstance(e, int) and contains_aggregate(e) for e, _ in items)
            or any(contains_aggregate(o.expr) for o in stmt.order_by)
        )
        aggs: list[AggSpec] | None = [] if is_agg else None
        ctx = Ctx(scope, aliases, aggs, scope.width)

        def compile_item(e: ast.Expr | int) -> Fn:
            if isinstance(e, int):
                return lambda r: r[e]
            return compile_expr(e, ctx)[0]

        out_fns = [compile_item(e) for e, _ in items]
        n_out = len(out_fns)

        # ORDER BY terms: either an output column position or an expression.
        order_keys: list[int | Fn] = []
        for i, o in enumerate(stmt.order_by, 1):
            e = o.expr
            if isinstance(e, ast.Literal) and type(e.value) is int:
                if not 1 <= e.value <= n_out:
                    raise SQLError(
                        f"{_ordinal(i)} ORDER BY term out of range - should be between 1 and {n_out}"
                    )
                order_keys.append(e.value - 1)
                continue
            if isinstance(e, ast.Column) and e.table is None:
                pos = _alias_position(items, e.name)
                if pos is not None:
                    order_keys.append(pos)
                    continue
            order_keys.append(compile_expr(e, ctx)[0])

        having = compile_expr(stmt.having, ctx)[0] if stmt.having is not None else None

        # Produce (output row, sort keys) pairs.
        results: list[tuple[tuple, list]] = []

        def emit(r: tuple) -> None:
            out = tuple(f(r) for f in out_fns)
            keys = [out[k] if isinstance(k, int) else k(r) for k in order_keys]
            results.append((out, keys))

        if not is_agg:
            for r in rows:
                emit(r)
        else:
            assert aggs is not None
            group_ctx = Ctx(scope, aliases, None)
            group_fns = []
            for i, e in enumerate(stmt.group_by, 1):
                if isinstance(e, ast.Literal) and type(e.value) is int:
                    if not 1 <= e.value <= n_out:
                        raise SQLError(
                            f"{_ordinal(i)} GROUP BY term out of range - should be between 1 and {n_out}"
                        )
                    target = items[e.value - 1][0]
                    if isinstance(target, int):
                        group_fns.append(lambda r, k=target: r[k])
                        continue
                    e = target
                if contains_aggregate(e):
                    raise SQLError("aggregate functions are not allowed in the GROUP BY clause")
                group_fns.append(compile_expr(e, group_ctx)[0])
            if stmt.group_by:
                groups: dict[tuple, list[tuple]] = {}
                for r in rows:
                    groups.setdefault(tuple(g(r) for g in group_fns), []).append(r)
                group_rows = list(groups.values())
            else:
                group_rows = [rows]
            empty = (None,) * scope.width
            for g in group_rows:
                agg_values = tuple(evaluate(spec, g) for spec in aggs)
                rep = representative_row(aggs, g) if g else empty
                ext = rep + agg_values
                if having is not None and not truth(having(ext)):
                    continue
                emit(ext)

        if stmt.distinct:
            seen = set()
            unique = []
            for out, keys in results:
                if out not in seen:
                    seen.add(out)
                    unique.append((out, keys))
            results = unique

        if stmt.order_by:
            for i in range(len(stmt.order_by) - 1, -1, -1):
                o = stmt.order_by[i]
                nulls_first = (not o.desc) if o.nulls_first is None else o.nulls_first
                null_key = (0, 0) if nulls_first != o.desc else (3, 0)
                sort_key = V.sort_key

                def key(item, i=i, null_key=null_key, sort_key=sort_key):
                    v = item[1][i]
                    return null_key if v is None else sort_key(v)

                results.sort(key=key, reverse=o.desc)

        out_rows = [out for out, _ in results]
        if stmt.limit is not None:
            limit = _limit_value(stmt.limit)
            offset = _limit_value(stmt.offset) if stmt.offset is not None else 0
            offset = max(offset, 0)
            if limit < 0:
                out_rows = out_rows[offset:]
            else:
                out_rows = out_rows[offset : offset + limit]
        return out_rows


def _conjuncts(e: ast.Expr) -> list[ast.Expr]:
    if isinstance(e, ast.Binary) and e.op == "AND":
        return _conjuncts(e.left) + _conjuncts(e.right)
    return [e]


def _column_refs(e: ast.Expr) -> list[ast.Column]:
    if isinstance(e, ast.Column):
        return [e]
    return [c for child in children(e) for c in _column_refs(child)]


def _equi_join_keys(on: ast.Expr, scope: Scope, left_width: int) -> tuple[Fn, Fn] | None:
    """Find an ``a = b`` conjunct of an ON clause usable as a hash-join key.

    One side must reference only the joined (rightmost) table and the other only tables to
    its left. Returns (key of a left row, key of a right row); rows whose keys are equal
    are the only candidates for which the conjunct can be true. The full ON clause is still
    evaluated for every candidate pair.
    """
    right_table = scope.tables[-1]
    right_scope = Scope()
    right_scope.add(right_table.key, right_table.columns, right_table.affinities)
    for c in _conjuncts(on):
        if not (isinstance(c, ast.Binary) and c.op == "="):
            continue
        sides = []
        for side in (c.left, c.right):
            refs = _column_refs(side)
            try:
                positions = [scope.resolve(r.table, r.name) for r in refs]
            except SQLError:
                return None
            if not refs or any(p is None for p in positions) or contains_aggregate(side):
                sides.append(None)
            elif all(p[0] >= left_width for p in positions):
                sides.append("right")
            elif all(p[0] < left_width for p in positions):
                sides.append("left")
            else:
                sides.append(None)
        if sorted(sides, key=str) != ["left", "right"]:
            continue
        lf, la = compile_expr(c.left, Ctx(scope if sides[0] == "left" else right_scope))
        rf, ra = compile_expr(c.right, Ctx(scope if sides[1] == "left" else right_scope))
        # Apply the comparison affinity of "=" to each side, so that equal keys hash equal.
        lconv, rconv = comparison_conversions(la, ra)
        lk = lf if lconv is None else (lambda r, f=lf, conv=lconv: _conv(f(r), conv))
        rk = rf if rconv is None else (lambda r, f=rf, conv=rconv: _conv(f(r), conv))
        return (lk, rk) if sides[0] == "left" else (rk, lk)
    return None


def _conv(v, conv):
    return None if v is None else conv(v)


def _alias_position(items: list[tuple[ast.Expr | int, str | None]], name: str) -> int | None:
    for pos, (_, alias) in enumerate(items):
        if alias is not None and alias.lower() == name:
            return pos
    return None


def _limit_value(e: ast.Expr) -> int:
    v = compile_expr(e, Ctx(Scope()))[0](())
    v = V.numeric_affinity(v)
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if type(v) is not int:
        raise SQLError("datatype mismatch")
    return v


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
