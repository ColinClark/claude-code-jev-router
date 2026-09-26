"""Statement execution and the public :class:`Database` class."""

from __future__ import annotations

from dataclasses import dataclass

from . import ast
from . import values as v
from .aggregates import make_accumulator
from .compiler import (
    AggregateRegistry,
    Column,
    Env,
    Evaluator,
    ExprCompiler,
    Scope,
    Source,
    Table,
    contains_aggregate,
)
from .errors import SQLError
from .parser import parse
from .values import Value


class Database:
    """An in-memory SQL database with SQLite-compatible semantics."""

    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}

    def execute(self, sql: str) -> list[tuple[Value, ...]]:
        """Execute one SQL statement. SELECT returns its rows; other statements return []."""
        statement = parse(sql)
        match statement:
            case ast.Select():
                return SelectExecutor(self, statement).run()
            case ast.CreateTable():
                self._create(statement)
            case ast.DropTable():
                self._drop(statement)
            case ast.Insert():
                self._insert(statement)
            case ast.Update():
                self._update(statement)
            case ast.Delete():
                self._delete(statement)
        return []

    def table(self, name: str) -> Table:
        table = self.tables.get(name)
        if table is None:
            raise SQLError(f"no such table: {name}")
        return table

    # ------------------------------------------------------------------- DDL

    def _create(self, stmt: ast.CreateTable) -> None:
        if stmt.name in self.tables:
            if stmt.if_not_exists:
                return
            raise SQLError(f"table {stmt.name} already exists")
        columns: list[Column] = []
        for col in stmt.columns:
            if any(existing.name == col.name for existing in columns):
                raise SQLError(f"duplicate column name: {col.name}")
            columns.append(Column(col.name, v.affinity_for_type(col.type_name)))
        self.tables[stmt.name] = Table(stmt.name, columns)

    def _drop(self, stmt: ast.DropTable) -> None:
        if stmt.name not in self.tables:
            if stmt.if_exists:
                return
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[stmt.name]

    # ------------------------------------------------------------------- DML

    def _insert(self, stmt: ast.Insert) -> None:
        table = self.table(stmt.table)
        if stmt.columns is None:
            targets = list(range(len(table.columns)))
        else:
            targets = []
            for name in stmt.columns:
                index = table.column_index(name)
                if index is None:
                    raise SQLError(f"table {table.name} has no column named {name}")
                targets.append(index)
        compiler = ExprCompiler(Scope())
        env = Env()
        new_rows = []
        for row_exprs in stmt.rows:
            if len(row_exprs) != len(targets):
                raise SQLError(
                    f"{len(row_exprs)} values for {len(targets)} columns"
                    if stmt.columns is not None
                    else f"table {table.name} has {len(targets)} columns "
                    f"but {len(row_exprs)} values were supplied"
                )
            row: list[Value] = [None] * len(table.columns)
            for index, expr in zip(targets, row_exprs, strict=True):
                value = compiler.fn(expr)(env)
                row[index] = v.apply_affinity(value, table.columns[index].affinity)
            new_rows.append(row)
        table.rows.extend(new_rows)

    def _update(self, stmt: ast.Update) -> None:
        table = self.table(stmt.table)
        compiler = ExprCompiler(Scope([Source(table.name, table, 0)]))
        assignments: list[tuple[int, Evaluator]] = []
        for name, expr in stmt.assignments:
            index = table.column_index(name)
            if index is None:
                raise SQLError(f"no such column: {name}")
            assignments.append((index, compiler.fn(expr)))
        where = compiler.fn(stmt.where) if stmt.where is not None else None
        env = Env()
        updates = []
        for row in table.rows:
            env.row = tuple(row)
            if where is not None and v.truth(where(env)) is not True:
                continue
            updates.append((row, [(index, fn(env)) for index, fn in assignments]))
        for row, changes in updates:
            for index, value in changes:
                row[index] = v.apply_affinity(value, table.columns[index].affinity)

    def _delete(self, stmt: ast.Delete) -> None:
        table = self.table(stmt.table)
        if stmt.where is None:
            table.rows.clear()
            return
        where = ExprCompiler(Scope([Source(table.name, table, 0)])).fn(stmt.where)
        env = Env()
        kept = []
        for row in table.rows:
            env.row = tuple(row)
            if v.truth(where(env)) is not True:
                kept.append(row)
        table.rows[:] = kept


@dataclass(slots=True)
class ResultRow:
    values: tuple[Value, ...]
    keys: list[Value]


class SelectExecutor:
    def __init__(self, db: Database, stmt: ast.Select) -> None:
        self.db = db
        self.stmt = stmt

    def run(self) -> list[tuple[Value, ...]]:
        stmt = self.stmt
        scope, joins = self._build_sources()
        items = self._expand_items(scope)
        aliases: dict[str, ast.Expr] = {}
        for expr, alias in items:
            if alias is not None:
                aliases.setdefault(alias, expr)

        is_aggregate = bool(stmt.group_by) or any(
            contains_aggregate(e)
            for e in [*(e for e, _ in items), stmt.having, *(o.expr for o in stmt.order_by)]
        )
        if stmt.having is not None and not is_aggregate:
            raise SQLError("HAVING clause on a non-aggregate query")

        registry = AggregateRegistry() if is_aggregate else None
        row_compiler = ExprCompiler(scope, aliases=aliases)
        group_terms = [self._group_term(expr, items, aliases, scope) for expr in stmt.group_by]
        out_compiler = ExprCompiler(
            scope, aliases=aliases, aggregates=registry, group_terms=group_terms
        )

        where = row_compiler.fn(stmt.where) if stmt.where is not None else None
        group_fns = [row_compiler.fn(expr) for expr in group_terms]
        output_fns = [out_compiler.fn(expr) for expr, _ in items]
        having = out_compiler.fn(stmt.having) if stmt.having is not None else None
        order_fns = [
            out_compiler.fn(self._order_term(item.expr, items, aliases)) for item in stmt.order_by
        ]
        limit, offset = self._limit_offset()

        rows = self._join_rows(scope, joins)
        if where is not None:
            env = Env()
            filtered = []
            for row in rows:
                env.row = row
                if v.truth(where(env)) is True:
                    filtered.append(row)
            rows = filtered

        results: list[ResultRow] = []
        for env in self._environments(rows, scope, group_fns, registry):
            if having is not None and v.truth(having(env)) is not True:
                continue
            results.append(
                ResultRow(tuple(fn(env) for fn in output_fns), [fn(env) for fn in order_fns])
            )

        if stmt.distinct:
            seen: set[tuple[Value, ...]] = set()
            unique = []
            for result in results:
                if result.values not in seen:
                    seen.add(result.values)
                    unique.append(result)
            results = unique

        for position in reversed(range(len(stmt.order_by))):
            results.sort(
                key=lambda r, p=position: v.sort_key(r.keys[p]),
                reverse=stmt.order_by[position].descending,
            )

        rows_out = [r.values for r in results]
        if offset:
            rows_out = rows_out[offset:]
        if limit is not None:
            rows_out = rows_out[:limit]
        return rows_out

    # ----------------------------------------------------------------- FROM

    def _build_sources(self) -> tuple[Scope, list[tuple[ast.Join, Scope, Source]]]:
        stmt = self.stmt
        if stmt.source is None:
            return Scope(), []
        first = Source(stmt.source.alias, self.db.table(stmt.source.name), 0)
        sources = [first]
        joins = []
        offset = len(first.table.columns)
        for join in stmt.joins:
            table = self.db.table(join.table.name)
            source = Source(join.table.alias, table, offset)
            offset += len(table.columns)
            sources.append(source)
            joins.append((join, Scope(list(sources)), source))
        return Scope(sources), joins

    def _join_rows(
        self, scope: Scope, joins: list[tuple[ast.Join, Scope, Source]]
    ) -> list[tuple[Value, ...]]:
        if not scope.sources:
            return [()]
        rows = [tuple(row) for row in scope.sources[0].table.rows]
        env = Env()
        for join, join_scope, source in joins:
            condition = (
                ExprCompiler(join_scope).fn(join.condition) if join.condition is not None else None
            )
            right_rows = [tuple(row) for row in source.table.rows]
            null_row = (None,) * len(source.table.columns)
            joined = []
            for left in rows:
                matched = False
                for right in right_rows:
                    combined = left + right
                    if condition is not None:
                        env.row = combined
                        if v.truth(condition(env)) is not True:
                            continue
                    joined.append(combined)
                    matched = True
                if not matched and join.kind == "LEFT":
                    joined.append(left + null_row)
            rows = joined
        return rows

    # --------------------------------------------------------------- SELECT

    def _expand_items(self, scope: Scope) -> list[tuple[ast.Expr, str | None]]:
        items: list[tuple[ast.Expr, str | None]] = []
        for item in self.stmt.items:
            if isinstance(item, ast.Star):
                if item.table is None:
                    if not scope.sources:
                        raise SQLError("no tables specified")
                    sources = scope.sources
                else:
                    source = scope.find_source(item.table)
                    if source is None:
                        raise SQLError(f"no such table: {item.table}")
                    sources = [source]
                for source in sources:
                    for column in source.table.columns:
                        items.append((ast.ColumnRef(source.alias, column.name), None))
            else:
                items.append((item.expr, item.alias))
        return items

    @staticmethod
    def _positional(
        expr: ast.Expr, items: list[tuple[ast.Expr, str | None]], clause: str
    ) -> ast.Expr:
        """Integer literals in GROUP BY / ORDER BY refer to result columns (1-based)."""
        if isinstance(expr, ast.Literal) and type(expr.value) is int:
            position = expr.value
            if not 1 <= position <= len(items):
                raise SQLError(f"{clause} term out of range - should be between 1 and {len(items)}")
            return items[position - 1][0]
        return expr

    def _group_term(
        self,
        expr: ast.Expr,
        items: list[tuple[ast.Expr, str | None]],
        aliases: dict[str, ast.Expr],
        scope: Scope,
    ) -> ast.Expr:
        """Resolve positional and alias GROUP BY terms to the expressions they denote."""
        if (
            isinstance(expr, ast.ColumnRef)
            and expr.table is None
            and expr.name in aliases
            and scope.resolve(expr) is None
        ):
            return aliases[expr.name]
        return self._positional(expr, items, "GROUP BY")

    def _order_term(
        self,
        expr: ast.Expr,
        items: list[tuple[ast.Expr, str | None]],
        aliases: dict[str, ast.Expr],
    ) -> ast.Expr:
        if isinstance(expr, ast.ColumnRef) and expr.table is None and expr.name in aliases:
            return aliases[expr.name]
        return self._positional(expr, items, "ORDER BY")

    def _limit_offset(self) -> tuple[int | None, int]:
        stmt = self.stmt
        compiler = ExprCompiler(Scope())
        limit = offset = None
        if stmt.limit is not None:
            limit = _integer_value(compiler.fn(stmt.limit)(Env()))
        if stmt.offset is not None:
            offset = _integer_value(compiler.fn(stmt.offset)(Env()))
        if limit is not None and limit < 0:
            limit = None
        return limit, max(offset or 0, 0)

    def _environments(
        self,
        rows: list[tuple[Value, ...]],
        scope: Scope,
        group_fns: list[Evaluator],
        registry: AggregateRegistry | None,
    ):
        """Yield one evaluation environment per output row (per group for aggregates)."""
        if registry is None:
            env = Env()
            for row in rows:
                env.row = row
                yield env
            return

        # Groups are keyed by value (1 and 1.0 compare equal, as in SQLite). The dict keeps
        # the key of the group's first row, which SQLite reports for GROUP BY terms; bare
        # columns are evaluated against the group's last row.
        groups: dict[tuple[Value, ...], _Group] = {}
        env = Env()
        for row in rows:
            env.row = row
            key = tuple(fn(env) for fn in group_fns)
            group = groups.get(key)
            if group is None:
                group = groups[key] = _Group(row, registry)
            group.add(row, env)
        if not groups and not group_fns:
            groups[()] = _Group((None,) * scope.width, registry)
        for key, group in groups.items():
            yield Env(group.last_row, group.finish(), key)


class _Group:
    """Accumulator state for one GROUP BY group."""

    def __init__(self, row: tuple[Value, ...], registry: AggregateRegistry) -> None:
        self.last_row = row
        self.specs = registry.specs
        self.accumulators = [
            make_accumulator(s.name, star=s.star, distinct=s.distinct) for s in self.specs
        ]

    def add(self, row: tuple[Value, ...], env: Env) -> None:
        self.last_row = row
        for spec, accumulator in zip(self.specs, self.accumulators, strict=True):
            accumulator.step(None if spec.arg is None else spec.arg(env))

    def finish(self) -> list[Value]:
        return [accumulator.finish() for accumulator in self.accumulators]


def _integer_value(value: Value) -> int:
    """LIMIT/OFFSET operands must be integers (or losslessly convertible)."""
    if isinstance(value, str):
        value = v.parse_full_number(value)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int):
        raise SQLError("datatype mismatch")
    return value
