from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key

from . import values as V
from .ast_nodes import (
    And,
    Between,
    BinOp,
    ColumnRef,
    CreateTable,
    Delete,
    Expr,
    FuncCall,
    InList,
    Insert,
    IsNull,
    Like,
    Literal,
    Not,
    Or,
    Select,
    UnaryOp,
    Update,
)
from .errors import SQLError
from .parser import parse

_AGGREGATE_NAMES = {"count", "sum", "avg", "min", "max"}


@dataclass
class ColumnDef:
    name: str
    type: str


class Table:
    def __init__(self, name: str, columns: list[ColumnDef]):
        self.name = name
        self.columns = columns
        self.rows: list[list] = []

    def column_index(self, name: str) -> int:
        low = name.lower()
        for i, c in enumerate(self.columns):
            if c.name.lower() == low:
                return i
        raise SQLError(f"no such column: {name}")


class EvalContext:
    __slots__ = ("flat_columns", "row", "group_rows")

    def __init__(self, flat_columns, row, group_rows=None):
        self.flat_columns = flat_columns
        self.row = row
        self.group_rows = group_rows

    def resolve_index(self, qualifier: str | None, name: str) -> int:
        candidates = []
        for i, (alias, colname) in enumerate(self.flat_columns):
            if colname.lower() == name.lower():
                if qualifier is None or (alias is not None and alias.lower() == qualifier.lower()):
                    candidates.append(i)
        if qualifier is not None and not candidates:
            alias_exists = any(a and a.lower() == qualifier.lower() for a, _ in self.flat_columns)
            if not alias_exists:
                raise SQLError(f"no such table or alias: {qualifier}")
            raise SQLError(f"no such column: {qualifier}.{name}")
        if not candidates:
            raise SQLError(f"no such column: {name}")
        if len(candidates) > 1:
            raise SQLError(f"ambiguous column name: {name}")
        return candidates[0]


def validate_refs(expr: Expr | None, ctx: EvalContext) -> None:
    """Statically resolve column references and function names, independent of row data,
    so that errors surface even when the underlying tables/groups are empty."""
    if expr is None:
        return
    if isinstance(expr, Literal):
        return
    if isinstance(expr, ColumnRef):
        if expr.name != "*":
            ctx.resolve_index(expr.table, expr.name)
        return
    if isinstance(expr, UnaryOp):
        validate_refs(expr.expr, ctx)
        return
    if isinstance(expr, BinOp):
        validate_refs(expr.left, ctx)
        validate_refs(expr.right, ctx)
        return
    if isinstance(expr, (And, Or)):
        validate_refs(expr.left, ctx)
        validate_refs(expr.right, ctx)
        return
    if isinstance(expr, Not):
        validate_refs(expr.expr, ctx)
        return
    if isinstance(expr, IsNull):
        validate_refs(expr.expr, ctx)
        return
    if isinstance(expr, InList):
        validate_refs(expr.expr, ctx)
        for v in expr.values:
            validate_refs(v, ctx)
        return
    if isinstance(expr, Between):
        validate_refs(expr.expr, ctx)
        validate_refs(expr.low, ctx)
        validate_refs(expr.high, ctx)
        return
    if isinstance(expr, Like):
        validate_refs(expr.expr, ctx)
        validate_refs(expr.pattern, ctx)
        return
    if isinstance(expr, FuncCall):
        if expr.name not in _AGGREGATE_NAMES:
            raise SQLError(f"Unknown function: {expr.name}")
        for a in expr.args:
            validate_refs(a, ctx)
        return
    raise SQLError(f"Cannot validate expression: {expr!r}")


def contains_aggregate(expr: Expr | None) -> bool:
    if expr is None:
        return False
    if isinstance(expr, FuncCall):
        if expr.name in _AGGREGATE_NAMES:
            return True
        return any(contains_aggregate(a) for a in expr.args)
    if isinstance(expr, Literal):
        return False
    if isinstance(expr, ColumnRef):
        return False
    if isinstance(expr, UnaryOp):
        return contains_aggregate(expr.expr)
    if isinstance(expr, BinOp):
        return contains_aggregate(expr.left) or contains_aggregate(expr.right)
    if isinstance(expr, (And, Or)):
        return contains_aggregate(expr.left) or contains_aggregate(expr.right)
    if isinstance(expr, Not):
        return contains_aggregate(expr.expr)
    if isinstance(expr, IsNull):
        return contains_aggregate(expr.expr)
    if isinstance(expr, InList):
        return contains_aggregate(expr.expr) or any(contains_aggregate(v) for v in expr.values)
    if isinstance(expr, Between):
        return (
            contains_aggregate(expr.expr)
            or contains_aggregate(expr.low)
            or contains_aggregate(expr.high)
        )
    if isinstance(expr, Like):
        return contains_aggregate(expr.expr) or contains_aggregate(expr.pattern)
    return False


def evaluate(expr: Expr, ctx: EvalContext) -> object:
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ColumnRef):
        idx = ctx.resolve_index(expr.table, expr.name)
        return ctx.row[idx]
    if isinstance(expr, UnaryOp):
        v = evaluate(expr.expr, ctx)
        if expr.op == "-":
            return V.unary_minus(v)
        return v  # unary '+' is a no-op in SQLite
    if isinstance(expr, BinOp):
        left = evaluate(expr.left, ctx)
        right = evaluate(expr.right, ctx)
        if expr.op == "||":
            return V.concat(left, right)
        if expr.op in ("+", "-", "*", "/", "%"):
            return V.arith(expr.op, left, right)
        return V.compare(expr.op, left, right)
    if isinstance(expr, And):
        return V.logical_and(evaluate(expr.left, ctx), evaluate(expr.right, ctx))
    if isinstance(expr, Or):
        return V.logical_or(evaluate(expr.left, ctx), evaluate(expr.right, ctx))
    if isinstance(expr, Not):
        return V.logical_not(evaluate(expr.expr, ctx))
    if isinstance(expr, IsNull):
        v = evaluate(expr.expr, ctx)
        res = 1 if v is None else 0
        if expr.negated:
            res = 1 - res
        return res
    if isinstance(expr, InList):
        v = evaluate(expr.expr, ctx)
        if v is None:
            return None
        found = False
        saw_null = False
        for item in expr.values:
            iv = evaluate(item, ctx)
            if iv is None:
                saw_null = True
                continue
            if V.compare("=", v, iv) == 1:
                found = True
                break
        if found:
            result = 1
        elif saw_null:
            result = None
        else:
            result = 0
        if expr.negated and result is not None:
            result = 1 - result
        return result
    if isinstance(expr, Between):
        v = evaluate(expr.expr, ctx)
        low = evaluate(expr.low, ctx)
        high = evaluate(expr.high, ctx)
        ge = V.compare(">=", v, low)
        le = V.compare("<=", v, high)
        result = V.logical_and(ge, le)
        if expr.negated:
            result = V.logical_not(result)
        return result
    if isinstance(expr, Like):
        v = evaluate(expr.expr, ctx)
        pattern = evaluate(expr.pattern, ctx)
        result = V.like_match(v, pattern)
        if expr.negated and result is not None:
            result = 1 - result
        return result
    if isinstance(expr, FuncCall):
        return _evaluate_func(expr, ctx)
    raise SQLError(f"Cannot evaluate expression: {expr!r}")


def _evaluate_func(func: FuncCall, ctx: EvalContext) -> object:
    if func.name not in _AGGREGATE_NAMES:
        raise SQLError(f"Unknown function: {func.name}")
    if ctx.group_rows is None:
        raise SQLError(f"Aggregate function {func.name} used outside of aggregate context")
    rows = ctx.group_rows
    if func.name == "count":
        if func.star:
            return len(rows)
        vals = [evaluate(func.args[0], EvalContext(ctx.flat_columns, r)) for r in rows]
        vals = [v for v in vals if v is not None]
        if func.distinct:
            vals = list(dict.fromkeys(vals))
        return len(vals)
    vals = [evaluate(func.args[0], EvalContext(ctx.flat_columns, r)) for r in rows]
    nonnull = [v for v in vals if v is not None]
    if func.distinct:
        nonnull = list(dict.fromkeys(nonnull))
    if func.name == "sum":
        if not nonnull:
            return None
        total = 0
        for v in nonnull:
            total = total + V.to_number_for_arith(v)
        return total
    if func.name == "avg":
        if not nonnull:
            return None
        total = 0
        for v in nonnull:
            total = total + V.to_number_for_arith(v)
        return total / len(nonnull)
    if func.name == "min":
        if not nonnull:
            return None
        return min(nonnull, key=cmp_to_key(V.compare_for_sort))
    if func.name == "max":
        if not nonnull:
            return None
        return max(nonnull, key=cmp_to_key(V.compare_for_sort))
    raise SQLError(f"Unknown aggregate function: {func.name}")


class Database:
    def __init__(self):
        self.tables: dict[str, Table] = {}

    def get_table(self, name: str) -> Table:
        table = self.tables.get(name.lower())
        if table is None:
            raise SQLError(f"no such table: {name}")
        return table

    def execute(self, sql: str) -> list[tuple]:
        if not isinstance(sql, str) or not sql.strip():
            raise SQLError("empty SQL statement")
        try:
            stmt = parse(sql)
            return self._execute_stmt(stmt)
        except SQLError:
            raise
        except Exception as exc:  # pragma: no cover - defensive wrapper
            raise SQLError(str(exc)) from exc

    def _execute_stmt(self, stmt) -> list[tuple]:
        if isinstance(stmt, CreateTable):
            self._exec_create_table(stmt)
            return []
        if isinstance(stmt, Insert):
            self._exec_insert(stmt)
            return []
        if isinstance(stmt, Update):
            self._exec_update(stmt)
            return []
        if isinstance(stmt, Delete):
            self._exec_delete(stmt)
            return []
        if isinstance(stmt, Select):
            return self._exec_select(stmt)
        raise SQLError(f"Unsupported statement: {stmt!r}")

    # -- CREATE TABLE ---------------------------------------------------

    def _exec_create_table(self, stmt: CreateTable) -> None:
        if stmt.name.lower() in self.tables:
            raise SQLError(f"table {stmt.name} already exists")
        seen = set()
        columns = []
        for c in stmt.columns:
            low = c.name.lower()
            if low in seen:
                raise SQLError(f"duplicate column name: {c.name}")
            seen.add(low)
            columns.append(ColumnDef(c.name, c.type))
        self.tables[stmt.name.lower()] = Table(stmt.name, columns)

    # -- INSERT -----------------------------------------------------------

    def _exec_insert(self, stmt: Insert) -> None:
        table = self.get_table(stmt.table)
        if stmt.columns is None:
            target_indices = list(range(len(table.columns)))
        else:
            target_indices = [table.column_index(c) for c in stmt.columns]
            if len(set(target_indices)) != len(target_indices):
                raise SQLError("duplicate column in INSERT column list")
        for row_exprs in stmt.rows:
            if len(row_exprs) != len(target_indices):
                raise SQLError("INSERT value count does not match column count")
            new_row = [None] * len(table.columns)
            ctx = EvalContext([], ())
            for idx, expr in zip(target_indices, row_exprs):
                value = evaluate(expr, ctx)
                new_row[idx] = V.coerce_to_column_type(value, table.columns[idx].type)
            table.rows.append(new_row)

    # -- UPDATE -------------------------------------------------------------

    def _exec_update(self, stmt: Update) -> None:
        table = self.get_table(stmt.table)
        flat_columns = [(table.name, c.name) for c in table.columns]
        assignment_indices = []
        for a in stmt.assignments:
            assignment_indices.append((table.column_index(a.column), a.expr))
        static_ctx = EvalContext(flat_columns, tuple(None for _ in flat_columns))
        if stmt.where is not None:
            validate_refs(stmt.where, static_ctx)
        for _idx, expr in assignment_indices:
            validate_refs(expr, static_ctx)
        for i, row in enumerate(table.rows):
            row_tuple = tuple(row)
            ctx = EvalContext(flat_columns, row_tuple)
            if stmt.where is not None:
                if V.truth(evaluate(stmt.where, ctx)) is not True:
                    continue
            new_row = list(row)
            for idx, expr in assignment_indices:
                value = evaluate(expr, ctx)
                new_row[idx] = V.coerce_to_column_type(value, table.columns[idx].type)
            table.rows[i] = new_row

    # -- DELETE ---------------------------------------------------------------

    def _exec_delete(self, stmt: Delete) -> None:
        table = self.get_table(stmt.table)
        flat_columns = [(table.name, c.name) for c in table.columns]
        if stmt.where is None:
            table.rows = []
            return
        validate_refs(stmt.where, EvalContext(flat_columns, tuple(None for _ in flat_columns)))
        kept = []
        for row in table.rows:
            ctx = EvalContext(flat_columns, tuple(row))
            if V.truth(evaluate(stmt.where, ctx)) is True:
                continue
            kept.append(row)
        table.rows = kept

    # -- SELECT -----------------------------------------------------------------

    def _build_joined_rows(self, stmt: Select):
        base_table = self.get_table(stmt.from_table)
        base_alias = stmt.from_alias or stmt.from_table
        flat_columns = [(base_alias, c.name) for c in base_table.columns]
        rows = [tuple(r) for r in base_table.rows]
        for j in stmt.joins:
            right_table = self.get_table(j.table)
            right_alias = j.alias or j.table
            right_cols = [(right_alias, c.name) for c in right_table.columns]
            new_flat = flat_columns + right_cols
            validate_refs(j.on, EvalContext(new_flat, tuple(None for _ in new_flat)))
            new_rows = []
            for lrow in rows:
                matched = False
                for rrow_raw in right_table.rows:
                    rrow = tuple(rrow_raw)
                    combined = lrow + rrow
                    cond = evaluate(j.on, EvalContext(new_flat, combined))
                    if V.truth(cond) is True:
                        matched = True
                        new_rows.append(combined)
                if not matched and j.kind == "LEFT":
                    new_rows.append(lrow + tuple(None for _ in right_cols))
            flat_columns = new_flat
            rows = new_rows
        return flat_columns, rows

    def _expand_select_list(self, stmt: Select, flat_columns):
        """Return list of (kind, payload) where kind is 'star' or 'expr'."""
        items = []
        for item in stmt.select_list:
            if isinstance(item.expr, ColumnRef) and item.expr.name == "*":
                qualifier = item.expr.table
                indices = []
                if qualifier is not None:
                    if not any(a and a.lower() == qualifier.lower() for a, _ in flat_columns):
                        raise SQLError(f"no such table or alias: {qualifier}")
                for i, (alias, _colname) in enumerate(flat_columns):
                    if qualifier is None or (alias and alias.lower() == qualifier.lower()):
                        indices.append(i)
                items.append(("star", indices))
            else:
                items.append(("expr", item))
        return items

    def _exec_select(self, stmt: Select) -> list[tuple]:
        flat_columns, rows = self._build_joined_rows(stmt)

        static_ctx = EvalContext(flat_columns, tuple(None for _ in flat_columns))
        if stmt.where is not None:
            validate_refs(stmt.where, static_ctx)
        for g in stmt.group_by:
            validate_refs(g, static_ctx)
        if stmt.having is not None:
            validate_refs(stmt.having, static_ctx)
        select_alias_names = {item.alias.lower() for item in stmt.select_list if item.alias}
        for term in stmt.order_by:
            if isinstance(term.expr, ColumnRef) and term.expr.table is None:
                if term.expr.name.lower() in select_alias_names:
                    continue
            validate_refs(term.expr, static_ctx)
        for item in stmt.select_list:
            if isinstance(item.expr, ColumnRef) and item.expr.name == "*":
                continue
            validate_refs(item.expr, static_ctx)

        if stmt.where is not None:
            rows = [
                r
                for r in rows
                if V.truth(evaluate(stmt.where, EvalContext(flat_columns, r))) is True
            ]

        has_agg = (
            any(contains_aggregate(item.expr) for item in stmt.select_list)
            or contains_aggregate(stmt.having)
            or any(contains_aggregate(t.expr) for t in stmt.order_by)
        )

        if stmt.group_by:
            groups: dict[tuple, list] = {}
            order: list[tuple] = []
            for r in rows:
                key = tuple(evaluate(g, EvalContext(flat_columns, r)) for g in stmt.group_by)
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append(r)
            group_list = [groups[k] for k in order]
        elif has_agg:
            group_list = [rows]
        else:
            group_list = [[r] for r in rows]

        expanded = self._expand_select_list(stmt, flat_columns)

        records = []  # (output_tuple, ctx)
        for grp in group_list:
            rep_row = grp[0] if grp else tuple(None for _ in flat_columns)
            ctx = EvalContext(flat_columns, rep_row, group_rows=grp)
            if stmt.having is not None:
                if V.truth(evaluate(stmt.having, ctx)) is not True:
                    continue
            out_values = []
            out_names = []
            for kind, payload in expanded:
                if kind == "star":
                    for i in payload:
                        out_values.append(rep_row[i])
                        out_names.append(flat_columns[i][1])
                else:
                    item = payload
                    out_values.append(evaluate(item.expr, ctx))
                    out_names.append(item.alias)
            records.append((tuple(out_values), out_names, ctx))

        if stmt.distinct:
            seen = set()
            deduped = []
            for rec in records:
                if rec[0] in seen:
                    continue
                seen.add(rec[0])
                deduped.append(rec)
            records = deduped

        if stmt.order_by:
            def cmp_records(r1, r2):
                for term in stmt.order_by:
                    v1 = self._resolve_order_value(term.expr, r1)
                    v2 = self._resolve_order_value(term.expr, r2)
                    c = V.compare_for_sort(v1, v2)
                    if term.desc:
                        c = -c
                    if c != 0:
                        return c
                return 0

            records = sorted(records, key=cmp_to_key(cmp_records))

        if stmt.offset is not None:
            records = records[stmt.offset :]
        if stmt.limit is not None:
            records = records[: stmt.limit]

        return [rec[0] for rec in records]

    def _resolve_order_value(self, expr: Expr, record):
        out_tuple, out_names, ctx = record
        if isinstance(expr, ColumnRef) and expr.table is None:
            for i, name in enumerate(out_names):
                if name is not None and name.lower() == expr.name.lower():
                    return out_tuple[i]
        return evaluate(expr, ctx)
