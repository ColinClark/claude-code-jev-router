"""Storage and statement execution.

``Database`` owns a catalog of :class:`Table` objects (schema + rows stored as
a list of tuples) and executes parsed statements.  Statement dispatch lives in
``Database._executors``; SELECT execution lives in :mod:`minisql.select`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    CreateTable,
    Delete,
    DropTable,
    Insert,
    Select,
    Statement,
    TableRef,
    Update,
)
from .parser import parse
from .select import execute_select
from .values import apply_affinity, is_true, type_affinity


@dataclass
class Table:
    name: str
    columns: tuple[str, ...]
    types: tuple[str, ...]  # declared type names as written
    affinities: tuple[str, ...]
    rows: list[tuple] = field(default_factory=list)

    def column_index(self, name: str) -> int:
        lname = name.lower()
        for i, c in enumerate(self.columns):
            if c.lower() == lname:
                return i
        raise SQLError(f"table {self.name} has no column named {name}")

    def source(self, ref_name: str | None = None) -> Source:
        return Source(ref_name or self.name, self.columns, self.affinities)


class Database:
    """An in-memory SQL database with SQLite-compatible semantics."""

    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}  # keyed by lower-cased table name
        self._executors = {
            CreateTable: self._exec_create,
            DropTable: self._exec_drop,
            Insert: self._exec_insert,
            Update: self._exec_update,
            Delete: self._exec_delete,
            Select: self._exec_select,
        }

    # -- public API ------------------------------------------------------------

    def execute(self, sql: str) -> list[tuple]:
        """Parse and run a single SQL statement; returns result rows ([] for DML/DDL)."""
        return self.execute_statement(parse(sql))

    def execute_statement(self, stmt: Statement) -> list[tuple]:
        executor = self._executors.get(type(stmt))
        if executor is None:
            raise SQLError(f"unsupported statement: {type(stmt).__name__}")
        return executor(stmt)

    @staticmethod
    def parse(sql: str) -> Statement:
        """Parse a statement without executing it."""
        return parse(sql)

    # -- catalog helpers (also intended for SELECT execution) ----------------

    def get_table(self, name: str) -> Table:
        table = self.tables.get(name.lower())
        if table is None:
            raise SQLError(f"no such table: {name}")
        return table

    def source_for(self, ref: TableRef) -> tuple[Table, Source]:
        """Resolve a FROM/JOIN table reference to its Table and a named Source.

        A SELECT executor builds ``Scope([source_for(from)[1], *join sources])``
        and evaluates expressions with ``RowContext(scope, (row_a, row_b, ...))``.
        """
        table = self.get_table(ref.name)
        return table, table.source(ref.ref_name)

    # -- executors ---------------------------------------------------------

    def _exec_select(self, stmt: Select) -> list[tuple]:
        return execute_select(self, stmt)

    def _exec_create(self, stmt: CreateTable) -> list[tuple]:
        key = stmt.name.lower()
        if key in self.tables:
            if stmt.if_not_exists:
                return []
            raise SQLError(f"table {stmt.name} already exists")
        seen: set[str] = set()
        for col in stmt.columns:
            lc = col.name.lower()
            if lc in seen:
                raise SQLError(f"duplicate column name: {col.name}")
            seen.add(lc)
        self.tables[key] = Table(
            name=stmt.name,
            columns=tuple(c.name for c in stmt.columns),
            types=tuple(c.type_name for c in stmt.columns),
            affinities=tuple(type_affinity(c.type_name) for c in stmt.columns),
        )
        return []

    def _exec_drop(self, stmt: DropTable) -> list[tuple]:
        key = stmt.name.lower()
        if key not in self.tables:
            if stmt.if_exists:
                return []
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[key]
        return []

    def _exec_insert(self, stmt: Insert) -> list[tuple]:
        table = self.get_table(stmt.table)
        ncols = len(table.columns)
        if stmt.columns is None:
            targets = list(range(ncols))
        else:
            targets = [table.column_index(c) for c in stmt.columns]
        for values in stmt.rows:
            if len(values) != len(targets):
                if stmt.columns is None:
                    raise SQLError(
                        f"table {table.name} has {ncols} columns but {len(values)} values were supplied"
                    )
                raise SQLError(f"{len(values)} values for {len(targets)} columns")
            for expr in values:
                validate_expr(expr, EMPTY_SCOPE)
        new_rows: list[tuple] = []
        for values in stmt.rows:
            row: list[object] = [None] * ncols
            for idx, expr in zip(targets, values):
                row[idx] = apply_affinity(eval_expr(expr), table.affinities[idx])
            new_rows.append(tuple(row))
        table.rows.extend(new_rows)
        return []

    def _exec_update(self, stmt: Update) -> list[tuple]:
        table = self.get_table(stmt.table)
        scope = Scope([table.source()])
        assignments = [(table.column_index(col), expr) for col, expr in stmt.assignments]
        for _, expr in assignments:
            validate_expr(expr, scope)
        if stmt.where is not None:
            validate_expr(stmt.where, scope)
        new_rows: list[tuple] = []
        for row in table.rows:
            ctx = RowContext(scope, (row,))
            if stmt.where is not None and not is_true(eval_expr(stmt.where, ctx)):
                new_rows.append(row)
                continue
            updated = list(row)
            for idx, expr in assignments:
                updated[idx] = apply_affinity(eval_expr(expr, ctx), table.affinities[idx])
            new_rows.append(tuple(updated))
        table.rows = new_rows
        return []

    def _exec_delete(self, stmt: Delete) -> list[tuple]:
        table = self.get_table(stmt.table)
        if stmt.where is None:
            table.rows = []
            return []
        scope = Scope([table.source()])
        validate_expr(stmt.where, scope)
        table.rows = [
            row
            for row in table.rows
            if not is_true(eval_expr(stmt.where, RowContext(scope, (row,))))
        ]
        return []
