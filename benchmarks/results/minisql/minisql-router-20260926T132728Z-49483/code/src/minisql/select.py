"""SELECT execution.

Pipeline (mirrors SQLite's logical evaluation order):

1. FROM / JOIN: nested-loop join producing "joined rows" -- one tuple per
   source (``None`` for a NULL-extended LEFT JOIN side), evaluated with a
   :class:`RowContext` over a :class:`Scope` containing every source.
2. WHERE filter.
3. Aggregation (if the query has GROUP BY, HAVING or any aggregate call):
   rows are grouped by the GROUP BY values (NULLs group together, numeric
   values compare numerically, so ``1`` and ``1.0`` share a group), each
   aggregate call is computed per group and HAVING filters groups.
4. Projection of the select list, ORDER BY (stable multi-key sort using
   :func:`compare_values`, so NULLs come first in ASC and last in DESC),
   DISTINCT, then OFFSET/LIMIT.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Sequence
from functools import cmp_to_key
from typing import TYPE_CHECKING

from .errors import SQLError
from .expressions import (
    EMPTY_SCOPE,
    RowContext,
    Scope,
    Source,
    eval_expr,
    validate_expr,
)
from .nodes import (
    Case,
    ColumnRef,
    Expr,
    ExprItem,
    FunctionCall,
    Literal,
    Select,
    StarItem,
    find_aggregates,
    walk,
)
from .values import (
    SortKey,
    apply_numeric_affinity_for_compare,
    compare_values,
    fits_int64,
    is_true,
    to_number,
    to_text,
)

if TYPE_CHECKING:
    from .engine import Database

JoinedRow = tuple  # tuple[tuple | None, ...]: one entry per source


# ---------------------------------------------------------------------------
# Expression rewriting helpers
# ---------------------------------------------------------------------------


def _transform(node: Expr, fn: Callable[[Expr], Expr | None]) -> Expr:
    """Rebuild ``node`` bottom-up-ish: ``fn`` may replace a node (returning non-None)."""
    replaced = fn(node)
    if replaced is not None:
        return replaced
    if isinstance(node, Case):
        return Case(
            _transform(node.operand, fn) if node.operand is not None else None,
            tuple((_transform(w, fn), _transform(r, fn)) for w, r in node.whens),
            _transform(node.else_, fn) if node.else_ is not None else None,
        )
    changes: dict[str, object] = {}
    for f in dataclasses.fields(node):  # type: ignore[arg-type]
        value = getattr(node, f.name)
        if isinstance(value, Expr):
            new = _transform(value, fn)
            if new is not value:
                changes[f.name] = new
        elif isinstance(value, tuple) and any(isinstance(v, Expr) for v in value):
            new_t = tuple(_transform(v, fn) if isinstance(v, Expr) else v for v in value)
            if new_t != value:
                changes[f.name] = new_t
    return dataclasses.replace(node, **changes) if changes else node  # type: ignore[type-var]


def _column_visible(scope: Scope, name: str) -> bool:
    return any(s.column_index(name) is not None for s in scope.sources)


def _substitute_aliases(node: Expr, aliases: dict[str, Expr], scope: Scope) -> Expr:
    """Replace unqualified names that are not table columns by result-column aliases.

    SQLite allows result aliases in WHERE/GROUP BY/HAVING/ORDER BY expressions
    as long as the name does not resolve to a real column.
    """
    if not aliases:
        return node

    def fn(n: Expr) -> Expr | None:
        if (
            isinstance(n, ColumnRef)
            and n.table is None
            and n.name.lower() in aliases
            and not _column_visible(scope, n.name)
        ):
            return aliases[n.name.lower()]
        return None

    return _transform(node, fn)


def _ordinal(node: Expr) -> int | None:
    if isinstance(node, Literal) and type(node.value) is int:
        return node.value
    return None


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


def _dedupe(values: list[object]) -> list[object]:
    seen: set[SortKey] = set()
    out: list[object] = []
    for v in values:
        k = SortKey(v)
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out


def _sum(values: list[object], name: str) -> object:
    """SUM / TOTAL / AVG accumulation with SQLite's integer-vs-real rules."""
    isum = 0
    floats: list[float] = []
    approx = False
    overflow = False
    for v in values:
        n = apply_numeric_affinity_for_compare(v)
        if isinstance(n, int):
            if approx or overflow:
                floats.append(float(n))
            else:
                isum += n
                if not fits_int64(isum):
                    overflow = True
                    approx = True
                    floats.append(float(isum))
                    isum = 0
        else:
            if not approx:
                approx = True
                floats.append(float(isum))
                isum = 0
            floats.append(float(to_number(n)))  # type: ignore[arg-type]
    count = len(values)
    if name == "TOTAL":
        return math.fsum(floats) + float(isum) if approx else float(isum)
    if count == 0:
        return None
    if name == "AVG":
        total = math.fsum(floats) if approx else float(isum)
        return total / count
    # SUM
    if overflow:
        raise SQLError("integer overflow")
    return math.fsum(floats) if approx else isum


def compute_aggregate(call: FunctionCall, scope: Scope, rows: Sequence[JoinedRow]) -> object:
    """Evaluate one aggregate call over the joined rows of a group."""
    name = call.name
    if call.star:  # COUNT(*)
        return len(rows)
    ctxs = [RowContext(scope, r) for r in rows]
    values = [eval_expr(call.args[0], c) for c in ctxs]
    values_nn = [v for v in values if v is not None]
    if call.distinct:
        values_nn = _dedupe(values_nn)
    if name == "COUNT":
        return len(values_nn)
    if name in ("SUM", "AVG", "TOTAL"):
        return _sum(values_nn, name)
    if name in ("MIN", "MAX"):
        best: object = None
        for v in values_nn:
            if best is None:
                best = v
                continue
            c = compare_values(v, best)
            if (name == "MIN" and c < 0) or (name == "MAX" and c > 0):
                best = v
        return best
    if name == "GROUP_CONCAT":
        parts: list[str] = []
        seps: list[str] = []
        seen: set[SortKey] = set()
        for v, c in zip(values, ctxs):
            if v is None:
                continue
            if call.distinct:
                k = SortKey(v)
                if k in seen:
                    continue
                seen.add(k)
            if len(call.args) > 1:
                sep = to_text(eval_expr(call.args[1], c))
                sep = "" if sep is None else sep
            else:
                sep = ","
            seps.append(sep)
            parts.append(to_text(v))  # type: ignore[arg-type]
        if not parts:
            return None
        out = parts[0]
        for sep, p in zip(seps[1:], parts[1:]):
            out += sep + p
        return out
    raise SQLError(f"no such function: {name}")


def _minmax_row(call: FunctionCall, scope: Scope, rows: Sequence[JoinedRow]) -> JoinedRow | None:
    """Row at which a lone MIN()/MAX() attains its value (SQLite bare-column rule)."""
    best_row = None
    best: object = None
    for r in rows:
        v = eval_expr(call.args[0], RowContext(scope, r))
        if v is None:
            continue
        if best is None:
            best, best_row = v, r
            continue
        c = compare_values(v, best)
        if (call.name == "MIN" and c < 0) or (call.name == "MAX" and c > 0):
            best, best_row = v, r
    return best_row


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def _to_limit_int(v: object, what: str) -> int:
    n = apply_numeric_affinity_for_compare(v)
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    if not isinstance(n, int):
        raise SQLError(f"datatype mismatch in {what}")
    return n


def execute_select(db: Database, stmt: Select) -> list[tuple]:
    # -- FROM: sources and scope ----------------------------------------------
    tables = []
    sources: list[Source] = []
    if stmt.from_table is not None:
        for ref in (stmt.from_table, *(j.table for j in stmt.joins)):
            table, source = db.source_for(ref)
            tables.append(table)
            sources.append(source)
    scope = Scope(sources) if sources else EMPTY_SCOPE
    nsrc = len(sources)

    # -- select list: expand stars into (source, column) slots ---------------
    # Each output slot is either ("col", si, ci) or ("expr", Expr).
    slots: list[tuple] = []
    aliases: dict[str, Expr] = {}
    for item in stmt.columns:
        if isinstance(item, StarItem):
            if not sources:
                raise SQLError("no tables specified")
            if item.table is None:
                picked = list(range(nsrc))
            else:
                lt = item.table.lower()
                picked = [i for i, s in enumerate(sources) if s.name.lower() == lt]
                if not picked:
                    raise SQLError(f"no such table: {item.table}")
            for si in picked:
                src = sources[si]
                for ci, col in enumerate(src.columns):
                    slots.append(("col", si, ci, ColumnRef(col, src.name)))
        else:
            assert isinstance(item, ExprItem)
            validate_expr(item.expr, scope, allow_aggregates=True)
            slots.append(("expr", item.expr))
            if item.alias is not None:
                aliases.setdefault(item.alias.lower(), item.expr)
    slot_exprs: list[Expr] = [s[3] if s[0] == "col" else s[1] for s in slots]

    # -- JOIN conditions --------------------------------------------------------
    join_conds: list[Expr | None] = []
    deferred: list[Expr] = []
    for i, join in enumerate(stmt.joins, start=1):
        on = join.on
        if on is not None:
            validate_expr(on, scope)
            refs = [scope.resolve(n)[0] for n in walk(on) if isinstance(n, ColumnRef)]
            if any(si > i for si in refs):
                if join.kind == "LEFT":
                    raise SQLError("ON clause references tables to its right")
                deferred.append(on)
                on = None
        join_conds.append(on)

    # -- WHERE ------------------------------------------------------------------
    where = stmt.where
    if where is not None:
        where = _substitute_aliases(where, aliases, scope)
        validate_expr(where, scope)

    # -- GROUP BY / HAVING ---------------------------------------------------
    group_by: list[Expr] = []
    for g in stmt.group_by:
        n = _ordinal(g)
        if n is not None:
            if not 1 <= n <= len(slot_exprs):
                raise SQLError(
                    f"GROUP BY term out of range - should be between 1 and {len(slot_exprs)}"
                )
            g = slot_exprs[n - 1]
        else:
            g = _substitute_aliases(g, aliases, scope)
        if find_aggregates(g):
            raise SQLError("aggregate functions are not allowed in the GROUP BY clause")
        validate_expr(g, scope)
        group_by.append(g)

    having = stmt.having
    if having is not None:
        having = _substitute_aliases(having, aliases, scope)
        validate_expr(having, scope, allow_aggregates=True)

    # -- ORDER BY: resolve each term to an output slot index or an expression --
    order_terms: list[tuple[int | None, Expr | None, bool]] = []
    for item in stmt.order_by:
        e = item.expr
        n = _ordinal(e)
        if n is not None:
            if not 1 <= n <= len(slot_exprs):
                raise SQLError(
                    f"ORDER BY term out of range - should be between 1 and {len(slot_exprs)}"
                )
            order_terms.append((n - 1, None, item.descending))
            continue
        if isinstance(e, ColumnRef) and e.table is None:
            idx = next(
                (
                    k
                    for k, it in enumerate(stmt.columns)
                    if isinstance(it, ExprItem)
                    and it.alias is not None
                    and it.alias.lower() == e.name.lower()
                ),
                None,
            )
            if idx is not None:
                # map select-item index to slot index (stars expand to many slots)
                slot_idx = _item_to_slot(stmt, sources, idx)
                order_terms.append((slot_idx, None, item.descending))
                continue
        e = _substitute_aliases(e, aliases, scope)
        validate_expr(e, scope, allow_aggregates=True)
        order_terms.append((None, e, item.descending))

    # -- aggregate detection ----------------------------------------------------
    agg_calls: list[FunctionCall] = []
    for e in (
        *slot_exprs,
        *([having] if having is not None else []),
        *(t[1] for t in order_terms if t[1] is not None),
    ):
        for call in find_aggregates(e):
            if call not in agg_calls:
                agg_calls.append(call)
    is_aggregate = bool(group_by) or having is not None or bool(agg_calls)

    # -- LIMIT / OFFSET (validated up front) ---------------------------------
    limit = offset = None
    if stmt.limit is not None:
        validate_expr(stmt.limit, EMPTY_SCOPE)
        limit = _to_limit_int(eval_expr(stmt.limit), "LIMIT")
    if stmt.offset is not None:
        validate_expr(stmt.offset, EMPTY_SCOPE)
        offset = _to_limit_int(eval_expr(stmt.offset), "OFFSET")

    # -- execute FROM/JOIN ------------------------------------------------------
    if not sources:
        joined: list[JoinedRow] = [()]
    else:
        pad = (None,) * (nsrc - 1)
        joined = [(r, *pad) for r in tables[0].rows]
        for i, join in enumerate(stmt.joins, start=1):
            cond = join_conds[i - 1]
            right_rows = tables[i].rows
            tail = (None,) * (nsrc - i - 1)
            out: list[JoinedRow] = []
            for left in joined:
                prefix = left[:i]
                matched = False
                for r in right_rows:
                    cand = (*prefix, r, *tail)
                    if cond is None or is_true(eval_expr(cond, RowContext(scope, cand))):
                        out.append(cand)
                        matched = True
                if not matched and join.kind == "LEFT":
                    out.append((*prefix, None, *tail))
            joined = out
        for cond in deferred:
            joined = [r for r in joined if is_true(eval_expr(cond, RowContext(scope, r)))]

    if where is not None:
        joined = [r for r in joined if is_true(eval_expr(where, RowContext(scope, r)))]

    # -- grouping ------------------------------------------------------------------
    contexts: list[RowContext] = []
    if is_aggregate:
        groups: dict[tuple, list[JoinedRow]] = {}
        for r in joined:
            ctx = RowContext(scope, r)
            key = tuple(SortKey(eval_expr(g, ctx)) for g in group_by)
            groups.setdefault(key, []).append(r)
        if not group_by and not groups:
            groups[()] = []
        lone_minmax = (
            agg_calls[0]
            if len(agg_calls) == 1 and agg_calls[0].name in ("MIN", "MAX")
            else None
        )
        for key in sorted(groups, key=lambda k: tuple(k)):
            rows = groups[key]
            aggs = {call: compute_aggregate(call, scope, rows) for call in agg_calls}
            rep: JoinedRow | None = None
            if lone_minmax is not None:
                rep = _minmax_row(lone_minmax, scope, rows)
            if rep is None:
                rep = rows[0] if rows else (None,) * nsrc
            ctx = RowContext(scope, rep, aggs)
            if having is not None and not is_true(eval_expr(having, ctx)):
                continue
            contexts.append(ctx)
    else:
        contexts = [RowContext(scope, r) for r in joined]

    # -- projection + order keys -------------------------------------------------
    results: list[tuple[tuple, tuple]] = []
    for ctx in contexts:
        values = []
        for s in slots:
            if s[0] == "col":
                row = ctx.rows[s[1]]
                values.append(None if row is None else row[s[2]])
            else:
                values.append(eval_expr(s[1], ctx))
        vt = tuple(values)
        keys = tuple(
            vt[idx] if idx is not None else eval_expr(e, ctx)  # type: ignore[arg-type]
            for idx, e, _ in order_terms
        )
        results.append((vt, keys))

    if order_terms:
        descs = [d for _, _, d in order_terms]

        def cmp(a: tuple[tuple, tuple], b: tuple[tuple, tuple]) -> int:
            for x, y, desc in zip(a[1], b[1], descs):
                c = compare_values(x, y)
                if c:
                    return -c if desc else c
            return 0

        results.sort(key=cmp_to_key(cmp))

    output = [vt for vt, _ in results]

    if stmt.distinct:
        seen: set[tuple] = set()
        deduped: list[tuple] = []
        for vt in output:
            k = tuple(SortKey(v) for v in vt)
            if k not in seen:
                seen.add(k)
                deduped.append(vt)
        output = deduped

    if offset is not None and offset > 0:
        output = output[offset:]
    if limit is not None and limit >= 0:
        output = output[:limit]
    return output


def _item_to_slot(stmt: Select, sources: list[Source], item_index: int) -> int:
    """Index of the output slot produced by select item ``item_index``."""
    slot = 0
    for k, item in enumerate(stmt.columns):
        if k == item_index:
            return slot
        if isinstance(item, StarItem):
            if item.table is None:
                slot += sum(len(s.columns) for s in sources)
            else:
                lt = item.table.lower()
                slot += sum(len(s.columns) for s in sources if s.name.lower() == lt)
        else:
            slot += 1
    raise AssertionError(item_index)
