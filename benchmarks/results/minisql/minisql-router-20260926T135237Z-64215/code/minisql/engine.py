"""Statement execution."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import ast as A
from . import values as V
from .compiler import AggSpec, Compiler, Fn, Scope, contains_aggregate
from .errors import SQLError
from .parser import parse


@dataclass(slots=True)
class Table:
    name: str
    columns: list[str]  # original spelling
    affinities: list[str]
    rows: list[tuple] = field(default_factory=list)

    @property
    def lower_columns(self) -> list[str]:
        return [c.lower() for c in self.columns]


class Database:
    """An in-memory SQL database.

    >>> db = Database()
    >>> db.execute("CREATE TABLE t (a INTEGER)")
    []
    >>> db.execute("INSERT INTO t VALUES (1), (2)")
    []
    >>> db.execute("SELECT a * 10 FROM t ORDER BY a DESC")
    [(20,), (10,)]
    """

    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}

    # -- public API --------------------------------------------------------

    def execute(self, sql: str) -> list[tuple]:
        if not isinstance(sql, str):
            raise SQLError("SQL must be a string")
        try:
            stmt = parse(sql)
            if stmt is None:  # empty statement / only comments
                return []
            return self._run(stmt)
        except RecursionError:
            raise SQLError("expression tree is too large") from None

    # -- dispatch ----------------------------------------------------------

    def _run(self, stmt: A.Statement) -> list[tuple]:
        if isinstance(stmt, A.Select):
            return self._select(stmt)
        if isinstance(stmt, A.Insert):
            self._insert(stmt)
        elif isinstance(stmt, A.Update):
            self._update(stmt)
        elif isinstance(stmt, A.Delete):
            self._delete(stmt)
        elif isinstance(stmt, A.CreateTable):
            self._create(stmt)
        elif isinstance(stmt, A.DropTable):
            self._drop(stmt)
        else:  # pragma: no cover
            raise SQLError("unsupported statement")
        return []

    def _table(self, name: str) -> Table:
        t = self.tables.get(name.lower())
        if t is None:
            raise SQLError(f"no such table: {name}")
        return t

    # -- DDL ---------------------------------------------------------------

    def _create(self, stmt: A.CreateTable) -> None:
        key = stmt.name.lower()
        if key in self.tables:
            if stmt.if_not_exists:
                return
            raise SQLError(f"table {stmt.name} already exists")
        if not stmt.columns:
            raise SQLError("table must have at least one column")
        seen: set[str] = set()
        for c in stmt.columns:
            if c.name.lower() in seen:
                raise SQLError(f"duplicate column name: {c.name}")
            seen.add(c.name.lower())
        self.tables[key] = Table(
            stmt.name,
            [c.name for c in stmt.columns],
            [V.affinity_of_type(c.type_name) for c in stmt.columns],
        )

    def _drop(self, stmt: A.DropTable) -> None:
        key = stmt.name.lower()
        if key not in self.tables:
            if stmt.if_exists:
                return
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[key]

    # -- DML ---------------------------------------------------------------

    def _table_scope(self, table: Table, alias: str | None = None) -> Scope:
        scope = Scope()
        scope.add(alias or table.name, table.lower_columns, table.affinities)
        return scope

    def _insert(self, stmt: A.Insert) -> None:
        table = self._table(stmt.table)
        ncols = len(table.columns)
        lower = table.lower_columns
        if stmt.columns is None:
            targets = list(range(ncols))
        else:
            targets = []
            for c in stmt.columns:
                if c.lower() not in lower:
                    raise SQLError(f"table {table.name} has no column named {c}")
                targets.append(lower.index(c.lower()))
        if stmt.select is not None:
            value_rows: list[tuple] = self._select(stmt.select)
            width = len(value_rows[0]) if value_rows else self._select_width(stmt.select)
            self._check_insert_width(table, stmt, targets, width)
        else:
            assert stmt.rows is not None
            self._check_insert_width(table, stmt, targets, len(stmt.rows[0]))
            comp = Compiler(Scope())
            value_rows = []
            for row in stmt.rows:
                fns = [comp.fn(e) for e in row]
                value_rows.append(tuple(f(()) for f in fns))
        new_rows = []
        for vals in value_rows:
            out: list[object] = [None] * ncols
            for idx, v in zip(targets, vals, strict=True):
                out[idx] = V.apply_affinity(v, table.affinities[idx])  # type: ignore[arg-type]
            new_rows.append(tuple(out))
        table.rows.extend(new_rows)

    @staticmethod
    def _check_insert_width(table: Table, stmt: A.Insert, targets: list[int], width: int):
        if width != len(targets):
            if stmt.columns is None:
                raise SQLError(
                    f"table {table.name} has {len(targets)} columns "
                    f"but {width} values were supplied"
                )
            raise SQLError(f"{width} values for {len(targets)} columns")

    def _select_width(self, sel: A.Select) -> int:
        n = 0
        scope = self._build_scope(sel)
        for item in sel.items:
            if isinstance(item, A.Star):
                n += len(self._expand_star(scope, item))
            else:
                n += 1
        return n

    def _update(self, stmt: A.Update) -> None:
        table = self._table(stmt.table)
        scope = self._table_scope(table)
        comp = Compiler(scope)
        lower = table.lower_columns
        assigns: list[tuple[int, Fn]] = []
        for col, expr in stmt.assignments:
            if col.lower() not in lower:
                raise SQLError(f"no such column: {col}")
            assigns.append((lower.index(col.lower()), comp.fn(expr)))
        where = comp.fn(stmt.where) if stmt.where is not None else None
        new_rows = []
        for row in table.rows:
            if where is None or V.to_bool(where(row)):
                new = list(row)
                for idx, f in assigns:
                    new[idx] = V.apply_affinity(f(row), table.affinities[idx])  # type: ignore
                new_rows.append(tuple(new))
            else:
                new_rows.append(row)
        table.rows = new_rows

    def _delete(self, stmt: A.Delete) -> None:
        table = self._table(stmt.table)
        if stmt.where is None:
            table.rows = []
            return
        where = Compiler(self._table_scope(table)).fn(stmt.where)
        table.rows = [r for r in table.rows if not V.to_bool(where(r))]

    # -- SELECT ------------------------------------------------------------

    def _build_scope(self, sel: A.Select) -> Scope:
        scope = Scope()
        if sel.from_ is None:
            return scope
        for ref in [sel.from_] + [j.table for j in sel.joins]:
            t = self._table(ref.name)
            scope.add(ref.alias or t.name, t.lower_columns, t.affinities)
        return scope

    def _source_rows(self, sel: A.Select) -> tuple[Scope, list[tuple]]:
        scope = Scope()
        if sel.from_ is None:
            return scope, [()]
        first = self._table(sel.from_.name)
        scope.add(sel.from_.alias or first.name, first.lower_columns, first.affinities)
        rows = list(first.rows)
        for join in sel.joins:
            t = self._table(join.table.name)
            scope.add(join.table.alias or t.name, t.lower_columns, t.affinities)
            on = None
            if join.on is not None:
                if contains_aggregate(join.on):
                    raise SQLError("misuse of aggregate function in ON clause")
                on = Compiler(scope.copy()).fn(join.on)
            right = t.rows
            pad = (None,) * len(t.columns)
            out = []
            for lrow in rows:
                matched = False
                for rrow in right:
                    comb = lrow + rrow
                    if on is None or V.to_bool(on(comb)):
                        out.append(comb)
                        matched = True
                if join.kind == "LEFT" and not matched:
                    out.append(lrow + pad)
            rows = out
        return scope, rows

    @staticmethod
    def _expand_star(scope: Scope, star: A.Star) -> list[A.Expr]:
        if star.table is None:
            if not scope.entries:
                raise SQLError("no tables specified")
            entries = scope.entries
        else:
            e = scope.find_entry(star.table)
            if e is None:
                raise SQLError(f"no such table: {star.table}")
            entries = [e]
        exprs: list[A.Expr] = []
        for e in entries:
            for c in e.columns:
                exprs.append(A.Column(e.alias, c))
        return exprs

    def _select(self, sel: A.Select) -> list[tuple]:
        scope, rows = self._source_rows(sel)

        # Expand the select list.
        exprs: list[A.Expr] = []
        aliases: dict[str, A.Expr] = {}
        alias_index: dict[str, int] = {}
        for item in sel.items:
            if isinstance(item, A.Star):
                exprs.extend(self._expand_star(scope, item))
            else:
                if item.alias is not None:
                    key = item.alias.lower()
                    aliases.setdefault(key, item.expr)
                    alias_index.setdefault(key, len(exprs))
                exprs.append(item.expr)

        # WHERE
        if sel.where is not None:
            if contains_aggregate(sel.where):
                raise SQLError("misuse of aggregate function in WHERE clause")
            where = Compiler(scope, aliases=aliases).fn(sel.where)
            rows = [r for r in rows if V.to_bool(where(r))]

        is_agg = (
            bool(sel.group_by)
            or any(contains_aggregate(e) for e in exprs)
            or (sel.having is not None)
            or any(contains_aggregate(t.expr) for t in sel.order_by)
        )
        if sel.having is not None and not sel.group_by and not (
            any(contains_aggregate(e) for e in exprs)
            or contains_aggregate(sel.having)
            or any(contains_aggregate(t.expr) for t in sel.order_by)
        ):
            raise SQLError("HAVING clause on a non-aggregate query")

        # ORDER BY term resolution: output column index or expression.
        order_specs: list[tuple[int | None, A.Expr | None, bool, bool]] = []
        for i, term in enumerate(sel.order_by):
            desc = term.desc
            nulls_first = term.nulls_first if term.nulls_first is not None else not desc
            out_idx = self._output_ref(term.expr, alias_index, len(exprs), i, "ORDER")
            if out_idx is not None:
                order_specs.append((out_idx, None, desc, nulls_first))
            else:
                order_specs.append((None, term.expr, desc, nulls_first))

        records: list[tuple[tuple, tuple]] = []
        if is_agg:
            records = self._aggregate(sel, scope, rows, exprs, aliases, alias_index, order_specs)
        else:
            comp = Compiler(scope, aliases=aliases)
            item_fns = [comp.fn(e) for e in exprs]
            key_fns = [comp.fn(e) if e is not None else None for _, e, _, _ in order_specs]
            for r in rows:
                out = tuple(f(r) for f in item_fns)
                keys = tuple(
                    out[idx] if idx is not None else kf(r)  # type: ignore[misc]
                    for (idx, _, _, _), kf in zip(order_specs, key_fns, strict=True)
                )
                records.append((out, keys))

        if sel.distinct:
            seen: set[tuple] = set()
            uniq = []
            for rec in records:
                if rec[0] not in seen:
                    seen.add(rec[0])
                    uniq.append(rec)
            records = uniq

        # Sort: stable multi-pass from the least significant key.
        for k in range(len(order_specs) - 1, -1, -1):
            _, _, desc, nulls_first = order_specs[k]
            null_rank = 0 if nulls_first != desc else 2

            def key(rec, k=k, null_rank=null_rank):
                v = rec[1][k]
                if v is None:
                    return (null_rank, 0)
                return (1, V.sort_key(v))

            records.sort(key=key, reverse=desc)

        result = [rec[0] for rec in records]

        if sel.limit is not None:
            limit = self._int_constant(sel.limit)
            offset = self._int_constant(sel.offset) if sel.offset is not None else 0
            if offset < 0:
                offset = 0
            if limit < 0:
                result = result[offset:]
            else:
                result = result[offset : offset + limit]
        return result

    @staticmethod
    def _output_ref(
        expr: A.Expr, alias_index: dict[str, int], n: int, pos: int, clause: str
    ) -> int | None:
        k = _integer_constant(expr)
        if k is not None:
            if not 1 <= k <= n:
                raise SQLError(
                    f"{_ordinal(pos + 1)} {clause} BY term out of range - "
                    f"should be between 1 and {n}"
                )
            return k - 1
        if clause == "ORDER" and isinstance(expr, A.Column) and expr.table is None:
            return alias_index.get(expr.name.lower())
        return None

    def _aggregate(self, sel, scope, rows, exprs, aliases, alias_index, order_specs):
        # GROUP BY key functions.
        group_fns: list[Fn] = []
        gcomp = Compiler(scope, aliases=aliases)
        for i, g in enumerate(sel.group_by):
            idx = self._output_ref(g, alias_index, len(exprs), i, "GROUP")
            target = exprs[idx] if idx is not None else g
            if contains_aggregate(target):
                raise SQLError("aggregate functions are not allowed in the GROUP BY clause")
            if idx is None and isinstance(g, A.Column) and g.table is None:
                # Prefer real columns; fall back to output aliases.
                if scope.resolve(None, g.name) is None and g.name.lower() in aliases:
                    target = aliases[g.name.lower()]
                    if contains_aggregate(target):
                        raise SQLError(
                            "aggregate functions are not allowed in the GROUP BY clause"
                        )
            group_fns.append(gcomp.fn(target))

        aggs: list[AggSpec] = []
        acomp = Compiler(scope, aggs=aggs, agg_base=scope.width, aliases=aliases)
        item_fns = [acomp.fn(e) for e in exprs]
        having_fn = acomp.fn(sel.having) if sel.having is not None else None
        key_fns = [acomp.fn(e) if e is not None else None for _, e, _, _ in order_specs]

        groups: dict[tuple, list[tuple]] = {}
        if group_fns:
            for r in rows:
                k = tuple(f(r) for f in group_fns)
                groups.setdefault(k, []).append(r)
            ordered = sorted(groups.items(), key=lambda kv: tuple(V.sort_key(v) for v in kv[0]))
            group_rows = [g for _, g in ordered]
        else:
            group_rows = [rows]

        records = []
        empty_row = (None,) * scope.width
        for grows in group_rows:
            rep = grows[0] if grows else empty_row
            vals = []
            for spec in aggs:
                v, best_row = compute_aggregate(spec, grows)
                if best_row is not None:
                    rep = best_row
                vals.append(v)
            env = rep + tuple(vals)
            if having_fn is not None and not V.to_bool(having_fn(env)):
                continue
            out = tuple(f(env) for f in item_fns)
            keys = tuple(
                out[idx] if idx is not None else kf(env)  # type: ignore[misc]
                for (idx, _, _, _), kf in zip(order_specs, key_fns, strict=True)
            )
            records.append((out, keys))
        return records

    def _int_constant(self, expr: A.Expr) -> int:
        if contains_aggregate(expr):
            raise SQLError("misuse of aggregate function")
        v = Compiler(Scope()).fn(expr)(())
        if isinstance(v, str):
            v = V.apply_numeric_for_compare(v)
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if not isinstance(v, int):
            raise SQLError("datatype mismatch")
        return v


def _integer_constant(expr: A.Expr) -> int | None:
    """Integer value of an integer literal, optionally with unary +/- (as SQLite checks)."""
    if isinstance(expr, A.Literal):
        v = expr.value
        return v if isinstance(v, int) else None
    if isinstance(expr, A.Unary) and expr.op in ("+", "-"):
        v = _integer_constant(expr.operand)
        if v is None:
            return None
        return -v if expr.op == "-" else v
    return None


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ---------------------------------------------------------------------------
# Aggregate computation


class _KBNSum:
    """Integer-then-Kahan-Babuska-Neumaier summation mirroring SQLite's sum()."""

    __slots__ = ("i_sum", "r_sum", "r_err", "approx", "overflow", "count")

    def __init__(self) -> None:
        self.i_sum = 0
        self.r_sum = 0.0
        self.r_err = 0.0
        self.approx = False
        self.overflow = False
        self.count = 0

    def _step(self, r: float) -> None:
        s = self.r_sum
        t = s + r
        if abs(s) > abs(r):
            self.r_err += (s - t) + r
        else:
            self.r_err += (r - t) + s
        self.r_sum = t

    def _step_int(self, i: int) -> None:
        if i <= -4503599627370496 or i >= 4503599627370496:
            rem = abs(i) % 16384
            if i < 0:
                rem = -rem
            big = i - rem
            self._step(float(big))
            self._step(float(i - big))
        else:
            self._step(float(i))

    def _init(self, i: int) -> None:
        self.r_sum = 0.0
        self.r_err = 0.0
        self._step_int(i)

    def add(self, v: object) -> None:
        self.count += 1
        n: object
        if isinstance(v, str):
            exact = V.text_to_exact_number(v)
            n = exact if exact is not None else float(V.to_number(v))  # type: ignore[arg-type]
        else:
            n = v
        if isinstance(n, int):
            if not self.approx:
                s = self.i_sum + n
                if V.INT_MIN <= s <= V.INT_MAX:
                    self.i_sum = s
                else:
                    self.overflow = True
                    self._init(self.i_sum)
                    self.approx = True
                    self._step_int(n)
            else:
                self._step_int(n)
        else:
            if not self.approx:
                self.approx = True
                self._init(self.i_sum)
            self._step(float(n))  # type: ignore[arg-type]

    def real_value(self) -> float:
        if not self.approx:
            return float(self.i_sum)
        if math.isinf(self.r_err) or math.isnan(self.r_err):
            return self.r_sum
        return self.r_sum + self.r_err

    def sum_value(self) -> object:
        if self.count == 0:
            return None
        if self.approx:
            if self.overflow:
                raise SQLError("integer overflow")
            return self.real_value()
        return self.i_sum


def compute_aggregate(spec: AggSpec, rows: list[tuple]) -> tuple[object, tuple | None]:
    """Compute one aggregate over rows. Returns (value, row_for_bare_columns_or_None)."""
    name = spec.name
    if spec.arg is None:  # COUNT(*)
        return len(rows), None
    arg = spec.arg
    pairs = [(arg(r), r) for r in rows]
    pairs = [(v, r) for v, r in pairs if v is not None]
    if spec.distinct:
        seen: set = set()
        uniq = []
        for v, r in pairs:
            if v not in seen:
                seen.add(v)
                uniq.append((v, r))
        pairs = uniq
    if name == "COUNT":
        return len(pairs), None
    if name in ("MIN", "MAX"):
        if not pairs:
            return None, None
        best, best_row = pairs[0]
        for v, r in pairs[1:]:
            c = V.compare(v, best)
            if (name == "MAX" and c > 0) or (name == "MIN" and c < 0):
                best, best_row = v, r
        return best, best_row
    if name in ("SUM", "TOTAL", "AVG"):
        acc = _KBNSum()
        for v, _ in pairs:
            acc.add(v)
        if name == "SUM":
            return acc.sum_value(), None
        if name == "TOTAL":
            return acc.real_value(), None
        if not pairs:
            return None, None
        return acc.real_value() / acc.count, None
    if name == "GROUP_CONCAT":
        if not pairs:
            return None, None
        parts: list[str] = []
        for i, (v, r) in enumerate(pairs):
            if i:
                sep = spec.extra(r) if spec.extra is not None else ","
                parts.append("" if sep is None else V.to_text(sep))  # type: ignore[arg-type]
            parts.append(V.to_text(v))  # type: ignore[arg-type]
        return "".join(parts), None
    raise SQLError(f"no such function: {name}")  # pragma: no cover
