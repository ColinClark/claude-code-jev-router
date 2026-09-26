from __future__ import annotations

from dataclasses import dataclass, field
from functools import cmp_to_key

from .ast_nodes import (
    ColumnRef,
    CreateTable,
    Delete,
    Insert,
    Select,
    Star,
    Update,
)
from .errors import SQLError
from .evaluator import EvalContext, evaluate, has_aggregate, is_truthy, sql_str
from .parser import parse_sql

_VALID_TYPES = {"INTEGER", "REAL", "TEXT"}


@dataclass
class Table:
    name: str
    columns: list[tuple[str, str]]  # (name_lower, type)
    rows: list[dict] = field(default_factory=list)

    @property
    def column_names(self) -> list[str]:
        return [c[0] for c in self.columns]

    def column_type(self, name_lower: str) -> str | None:
        for cname, ctype in self.columns:
            if cname == name_lower:
                return ctype
        return None

    def has_column(self, name_lower: str) -> bool:
        return any(c[0] == name_lower for c in self.columns)


@dataclass
class Source:
    alias: str  # lowercase
    table: Table


def _coerce(value, col_type: str):
    if value is None:
        return None
    if col_type == "REAL":
        if isinstance(value, int):
            return float(value)
        return value
    if col_type == "INTEGER":
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    if col_type == "TEXT":
        if not isinstance(value, str):
            return sql_str(value)
        return value
    return value


class Database:
    def __init__(self):
        self.tables: dict[str, Table] = {}

    def execute(self, sql: str) -> list[tuple]:
        sql = sql.strip()
        if sql.endswith(";"):
            sql = sql[:-1]
        stmt = parse_sql(sql)
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
        raise SQLError(f"Unsupported statement {stmt!r}")

    def _get_table(self, name: str) -> Table:
        table = self.tables.get(name.lower())
        if table is None:
            raise SQLError(f"Unknown table {name!r}")
        return table

    # ---- DDL ----

    def _exec_create_table(self, stmt: CreateTable) -> None:
        key = stmt.name.lower()
        if key in self.tables:
            raise SQLError(f"Table {stmt.name!r} already exists")
        columns = []
        seen = set()
        for col in stmt.columns:
            cname = col.name.lower()
            if cname in seen:
                raise SQLError(f"Duplicate column {col.name!r}")
            seen.add(cname)
            if col.type not in _VALID_TYPES:
                raise SQLError(f"Unknown column type {col.type!r}")
            columns.append((cname, col.type))
        self.tables[key] = Table(name=stmt.name, columns=columns)

    # ---- INSERT ----

    def _exec_insert(self, stmt: Insert) -> None:
        table = self._get_table(stmt.table)
        if stmt.columns is not None:
            col_names = [c.lower() for c in stmt.columns]
            for c in col_names:
                if not table.has_column(c):
                    raise SQLError(f"Unknown column {c!r}")
        else:
            col_names = table.column_names

        empty_ctx = EvalContext(row=None, resolver={})
        for value_exprs in stmt.rows:
            if len(value_exprs) != len(col_names):
                raise SQLError("INSERT column count does not match VALUES count")
            row = {cname: None for cname in table.column_names}
            for cname, expr in zip(col_names, value_exprs):
                value = evaluate(expr, empty_ctx)
                col_type = table.column_type(cname)
                row[cname] = _coerce(value, col_type)
            table.rows.append(row)

    # ---- UPDATE ----

    def _exec_update(self, stmt: Update) -> None:
        table = self._get_table(stmt.table)
        alias = table.name.lower()
        resolver = {cname: [alias] for cname in table.column_names}
        for cname, _ in stmt.assignments:
            if not table.has_column(cname.lower()):
                raise SQLError(f"Unknown column {cname!r}")

        for row in table.rows:
            row_key = {(alias, cname): val for cname, val in row.items()}
            ctx = EvalContext(row=row_key, resolver=resolver)
            if stmt.where is not None:
                if not is_truthy(evaluate(stmt.where, ctx)):
                    continue
            new_values = {}
            for cname, expr in stmt.assignments:
                new_values[cname.lower()] = evaluate(expr, ctx)
            for cname, value in new_values.items():
                col_type = table.column_type(cname)
                row[cname] = _coerce(value, col_type)

    # ---- DELETE ----

    def _exec_delete(self, stmt: Delete) -> None:
        table = self._get_table(stmt.table)
        alias = table.name.lower()
        resolver = {cname: [alias] for cname in table.column_names}
        if stmt.where is None:
            table.rows = []
            return
        kept = []
        for row in table.rows:
            row_key = {(alias, cname): val for cname, val in row.items()}
            ctx = EvalContext(row=row_key, resolver=resolver)
            if not is_truthy(evaluate(stmt.where, ctx)):
                kept.append(row)
        table.rows = kept

    # ---- SELECT ----

    def _resolve_sources(self, stmt: Select) -> tuple[list[Source], dict]:
        sources: list[Source] = []
        used_aliases: set[str] = set()

        def add_source(table_ref):
            table = self._get_table(table_ref.name)
            alias = (table_ref.alias or table_ref.name).lower()
            if alias in used_aliases:
                raise SQLError(f"Duplicate table alias {alias!r}")
            used_aliases.add(alias)
            sources.append(Source(alias=alias, table=table))

        add_source(stmt.from_table)
        for join in stmt.joins:
            add_source(join.table)

        resolver: dict[str, list[str]] = {}
        for src in sources:
            for cname in src.table.column_names:
                resolver.setdefault(cname, []).append(src.alias)
        return sources, resolver

    def _base_rows(self, sources: list[Source], joins, resolver) -> list[dict]:
        first = sources[0]
        rows = [{(first.alias, c): v for c, v in r.items()} for r in first.table.rows]

        for join, src in zip(joins, sources[1:]):
            new_rows = []
            for row in rows:
                matched = False
                for r in src.table.rows:
                    candidate = dict(row)
                    for c, v in r.items():
                        candidate[(src.alias, c)] = v
                    on_ctx = EvalContext(row=candidate, resolver=resolver)
                    if is_truthy(evaluate(join.on, on_ctx)):
                        new_rows.append(candidate)
                        matched = True
                if not matched and join.kind == "LEFT":
                    candidate = dict(row)
                    for c in src.table.column_names:
                        candidate[(src.alias, c)] = None
                    new_rows.append(candidate)
            rows = new_rows
        return rows

    def _expand_items(self, stmt: Select, sources: list[Source]):
        expanded: list[tuple] = []  # (expr, alias_or_None)
        for item in stmt.items:
            if isinstance(item.expr, Star):
                if item.expr.table is not None:
                    matches = [s for s in sources if s.alias == item.expr.table.lower()]
                    if not matches:
                        raise SQLError(f"Unknown table alias {item.expr.table!r}")
                    src = matches[0]
                    for cname in src.table.column_names:
                        expanded.append((ColumnRef(src.alias, cname), cname))
                else:
                    for src in sources:
                        for cname in src.table.column_names:
                            expanded.append((ColumnRef(src.alias, cname), cname))
            else:
                alias = item.alias
                if alias is None and isinstance(item.expr, ColumnRef):
                    alias = item.expr.name
                expanded.append((item.expr, alias))
        return expanded

    def _exec_select(self, stmt: Select) -> list[tuple]:
        sources, resolver = self._resolve_sources(stmt)
        rows = self._base_rows(sources, stmt.joins, resolver)

        if stmt.where is not None:
            rows = [
                r
                for r in rows
                if is_truthy(evaluate(stmt.where, EvalContext(row=r, resolver=resolver)))
            ]

        expanded_items = self._expand_items(stmt, sources)

        uses_aggregate = (
            any(has_aggregate(e) for e, _ in expanded_items)
            or (stmt.having is not None and has_aggregate(stmt.having))
            or any(has_aggregate(oi.expr) for oi in stmt.order_by)
        )

        groups: list[list[dict]]
        if stmt.group_by:
            group_map: dict[tuple, list[dict]] = {}
            order: list[tuple] = []
            for r in rows:
                ctx = EvalContext(row=r, resolver=resolver)
                key = tuple(evaluate(e, ctx) for e in stmt.group_by)
                if key not in group_map:
                    group_map[key] = []
                    order.append(key)
                group_map[key].append(r)
            groups = [group_map[k] for k in order]
        elif uses_aggregate:
            groups = [rows]
        else:
            groups = [[r] for r in rows]

        records = []
        for group_rows in groups:
            rep_row = group_rows[0] if group_rows else None
            ctx = EvalContext(row=rep_row, resolver=resolver, group_rows=group_rows)
            if stmt.having is not None:
                if not is_truthy(evaluate(stmt.having, ctx)):
                    continue
            values = tuple(evaluate(e, ctx) for e, _ in expanded_items)
            records.append((values, ctx))

        if stmt.distinct:
            seen = set()
            deduped = []
            for values, ctx in records:
                if values in seen:
                    continue
                seen.add(values)
                deduped.append((values, ctx))
            records = deduped

        if stmt.order_by:
            alias_index = {}
            for idx, (_, alias) in enumerate(expanded_items):
                if alias is not None and alias.lower() not in alias_index:
                    alias_index[alias.lower()] = idx

            def order_value(item, rec):
                values, ctx = rec
                expr = item.expr
                if isinstance(expr, ColumnRef) and expr.table is None:
                    idx = alias_index.get(expr.name.lower())
                    if idx is not None:
                        return values[idx]
                return evaluate(expr, ctx)

            def cmp_values(a, b):
                if a is None and b is None:
                    return 0
                if a is None:
                    return -1
                if b is None:
                    return 1
                if a < b:
                    return -1
                if a > b:
                    return 1
                return 0

            def full_cmp(rec1, rec2):
                for item in stmt.order_by:
                    v1 = order_value(item, rec1)
                    v2 = order_value(item, rec2)
                    c = cmp_values(v1, v2)
                    if item.desc:
                        c = -c
                    if c != 0:
                        return c
                return 0

            records = sorted(records, key=cmp_to_key(full_cmp))

        offset = stmt.offset or 0
        if stmt.limit is not None:
            records = records[offset : offset + stmt.limit]
        elif offset:
            records = records[offset:]

        return [values for values, _ in records]
