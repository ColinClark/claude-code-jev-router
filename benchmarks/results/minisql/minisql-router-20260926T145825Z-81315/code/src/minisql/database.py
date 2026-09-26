"""Statement execution for minisql."""

from minisql.compiler import AggSpec, Compiler, Scope, Source, contains_aggregate
from minisql.errors import SQLError
from minisql.parser import (
    CreateTable,
    Delete,
    DropTable,
    Insert,
    OrderTerm,
    Select,
    Update,
    parse,
)
from minisql.values import (
    INT_MAX,
    INT_MIN,
    apply_storage_affinity,
    compare,
    is_true,
    numeric_affinity,
    parse_exact_number,
    sort_key,
    text_to_number,
    type_affinity,
)


class Table:
    def __init__(self, name: str, columns: list[tuple[str, str]]):
        self.name = name
        self.columns = [c for c, _ in columns]
        self.affinities = [type_affinity(t) for _, t in columns]
        self._index = {c.lower(): i for i, c in enumerate(self.columns)}
        self.rows: list[list] = []

    def index_of(self, lname: str) -> int | None:
        return self._index.get(lname)


class Database:
    def __init__(self):
        self.tables: dict[str, Table] = {}

    def execute(self, sql: str) -> list[tuple]:
        try:
            stmt = parse(sql)
            if isinstance(stmt, Select):
                return self._select(stmt)
            if isinstance(stmt, CreateTable):
                self._create(stmt)
            elif isinstance(stmt, DropTable):
                self._drop(stmt)
            elif isinstance(stmt, Insert):
                self._insert(stmt)
            elif isinstance(stmt, Update):
                self._update(stmt)
            elif isinstance(stmt, Delete):
                self._delete(stmt)
            return []
        except RecursionError:
            raise SQLError("expression tree is too large") from None

    # -- helpers ---------------------------------------------------------
    def _table(self, name: str) -> Table:
        table = self.tables.get(name.lower())
        if table is None:
            raise SQLError(f"no such table: {name}")
        return table

    # -- DDL -------------------------------------------------------------
    def _create(self, stmt: CreateTable) -> None:
        key = stmt.name.lower()
        if key in self.tables:
            if stmt.if_not_exists:
                return
            raise SQLError(f"table {stmt.name} already exists")
        seen = set()
        for col, _ in stmt.columns:
            if col.lower() in seen:
                raise SQLError(f"duplicate column name: {col}")
            seen.add(col.lower())
        self.tables[key] = Table(stmt.name, stmt.columns)

    def _drop(self, stmt: DropTable) -> None:
        key = stmt.name.lower()
        if key not in self.tables:
            if stmt.if_exists:
                return
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[key]

    # -- DML -------------------------------------------------------------
    def _insert(self, stmt: Insert) -> None:
        table = self._table(stmt.table)
        if stmt.columns is None:
            targets = list(range(len(table.columns)))
        else:
            targets = []
            for col in stmt.columns:
                idx = table.index_of(col.lower())
                if idx is None:
                    raise SQLError(f"table {table.name} has no column named {col}")
                targets.append(idx)
        if stmt.select is not None:
            values_rows = self._select(stmt.select)
        else:
            compiler = Compiler(Scope())
            values_rows = []
            for exprs in stmt.rows:
                if len(exprs) != len(targets):
                    raise SQLError(f"{len(exprs)} values for {len(targets)} columns")
                fns = [compiler.compile(e) for e in exprs]
                values_rows.append([f(((), None)) for f in fns])
        new_rows = []
        for values in values_rows:
            if len(values) != len(targets):
                raise SQLError(f"{len(values)} values for {len(targets)} columns")
            row = [None] * len(table.columns)
            for idx, value in zip(targets, values, strict=True):
                row[idx] = apply_storage_affinity(value, table.affinities[idx])
            new_rows.append(row)
        table.rows.extend(new_rows)

    def _single_table_scope(self, name: str) -> tuple[Table, Scope]:
        table = self._table(name)
        return table, Scope([Source(name.lower(), table, 0)])

    def _update(self, stmt: Update) -> None:
        table, scope = self._single_table_scope(stmt.table)
        compiler = Compiler(scope)
        where = compiler.compile(stmt.where) if stmt.where is not None else None
        sets = []
        for col, expr in stmt.assignments:
            idx = table.index_of(col.lower())
            if idx is None:
                raise SQLError(f"no such column: {col}")
            sets.append((idx, compiler.compile(expr)))
        updates = []
        for pos, row in enumerate(table.rows):
            env = (row, None)
            if where is not None and not is_true(where(env)):
                continue
            new_row = list(row)
            for idx, fn in sets:
                new_row[idx] = apply_storage_affinity(fn(env), table.affinities[idx])
            updates.append((pos, new_row))
        for pos, new_row in updates:
            table.rows[pos] = new_row

    def _delete(self, stmt: Delete) -> None:
        table, scope = self._single_table_scope(stmt.table)
        if stmt.where is None:
            table.rows = []
            return
        where = Compiler(scope).compile(stmt.where)
        table.rows = [row for row in table.rows if not is_true(where((row, None)))]

    # -- SELECT ----------------------------------------------------------
    def _select(self, sel: Select) -> list[tuple]:
        sources: list[Source] = []
        offset = 0
        refs = []
        if sel.table is not None:
            refs.append((sel.table, None))
            refs.extend((j.table, j) for j in sel.joins)
        for ref, _ in refs:
            table = self._table(ref.name)
            sources.append(Source((ref.alias or ref.name).lower(), table, offset))
            offset += len(table.columns)
        scope = Scope(sources)

        # Build the joined row set.
        if sel.table is None:
            rows: list[list] = [[]]
        else:
            rows = [list(r) for r in sources[0].table.rows]
            for k, join in enumerate(sel.joins, start=1):
                on = None
                if join.on is not None:
                    on = Compiler(Scope(sources[: k + 1])).compile(join.on)
                right_rows = sources[k].table.rows
                pad = [None] * len(sources[k].table.columns)
                joined = []
                for left in rows:
                    matched = False
                    for right in right_rows:
                        combined = left + right
                        if on is None or is_true(on((combined, None))):
                            joined.append(combined)
                            matched = True
                    if not matched and join.kind == "LEFT":
                        joined.append(left + pad)
                rows = joined

        items = self._expand_items(sel, sources)
        aliases = {}
        for node, alias in items:
            if alias is not None:
                aliases.setdefault(alias.lower(), node)

        if sel.where is not None:
            where = Compiler(scope, aliases).compile(sel.where)
            rows = [r for r in rows if is_true(where((r, None)))]

        is_agg = (
            bool(sel.group_by)
            or sel.having is not None
            or any(contains_aggregate(node) for node, _ in items)
        )

        output: list[tuple[tuple, list]] = []
        if not is_agg:
            compiler = Compiler(scope, aliases)
            item_fns = [compiler.compile(node) for node, _ in items]
            order = [self._order_term(t, items, compiler) for t in sel.order_by]
            for row in rows:
                env = (row, None)
                out = tuple(f(env) for f in item_fns)
                output.append((out, self._order_keys(order, out, env)))
        else:
            aggs: list[AggSpec] = []
            compiler = Compiler(scope, aliases, aggs)
            item_fns = [compiler.compile(node) for node, _ in items]
            having = compiler.compile(sel.having) if sel.having is not None else None
            order = [self._order_term(t, items, compiler) for t in sel.order_by]
            groups = self._group(sel, items, scope, aliases, rows)
            width = scope.width
            for group_rows in groups:
                env = _aggregate(aggs, group_rows, width)
                if having is not None and not is_true(having(env)):
                    continue
                out = tuple(f(env) for f in item_fns)
                output.append((out, self._order_keys(order, out, env)))

        if sel.distinct:
            seen = set()
            unique = []
            for entry in output:
                if entry[0] not in seen:
                    seen.add(entry[0])
                    unique.append(entry)
            output = unique

        for idx in range(len(sel.order_by) - 1, -1, -1):
            term = sel.order_by[idx]
            output.sort(key=lambda e, i=idx: sort_key(e[1][i]), reverse=term.desc)
            if term.nulls_first is not None:
                nulls = [e for e in output if e[1][idx] is None]
                rest = [e for e in output if e[1][idx] is not None]
                output = nulls + rest if term.nulls_first else rest + nulls

        result = [out for out, _ in output]
        if sel.limit is not None or sel.offset is not None:
            start = 0
            if sel.offset is not None:
                start = max(0, _eval_int(sel.offset))
            result = result[start:]
            if sel.limit is not None:
                limit = _eval_int(sel.limit)
                if limit >= 0:
                    result = result[:limit]
        return result

    def _expand_items(self, sel: Select, sources: list[Source]) -> list:
        items = []
        for item in sel.items:
            if item[0] != "*":
                items.append(item)
                continue
            table = item[1]
            if table is None:
                if not sources:
                    raise SQLError("no tables specified")
                chosen = sources
            else:
                chosen = [s for s in sources if s.key == table.lower()]
                if not chosen:
                    raise SQLError(f"no such table: {table}")
            for src in chosen:
                for i, aff in enumerate(src.table.affinities):
                    items.append((("colidx", src.offset + i, aff), None))
        return items

    def _order_term(self, term: OrderTerm, items: list, compiler: Compiler):
        expr = term.expr
        if expr[0] == "lit" and isinstance(expr[1], int):
            k = expr[1]
            if not 1 <= k <= len(items):
                raise SQLError(f"ORDER BY term out of range - should be between 1 and {len(items)}")
            return ("out", k - 1)
        if expr[0] == "col" and expr[1] is None:
            name = expr[2].lower()
            for i, (_, alias) in enumerate(items):
                if alias is not None and alias.lower() == name:
                    return ("out", i)
        return ("fn", compiler.compile(expr))

    @staticmethod
    def _order_keys(order: list, out: tuple, env) -> list:
        return [out[v] if kind == "out" else v(env) for kind, v in order]

    def _group(self, sel: Select, items: list, scope: Scope, aliases: dict, rows: list):
        if not sel.group_by:
            return [rows]
        compiler = Compiler(scope, aliases)
        fns = []
        for expr in sel.group_by:
            if expr[0] == "lit" and isinstance(expr[1], int):
                k = expr[1]
                if not 1 <= k <= len(items):
                    raise SQLError(
                        f"GROUP BY term out of range - should be between 1 and {len(items)}"
                    )
                expr = items[k - 1][0]
            if contains_aggregate(expr):
                raise SQLError("aggregate functions are not allowed in the GROUP BY clause")
            fns.append(compiler.compile(expr))
        groups: dict[tuple, list] = {}
        for row in rows:
            env = (row, None)
            key = tuple(f(env) for f in fns)
            groups.setdefault(key, []).append(row)
        return list(groups.values())


def _eval_int(expr) -> int:
    value = Compiler(Scope()).compile(expr)(((), None))
    value = numeric_affinity(value)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int):
        raise SQLError("datatype mismatch")
    return value


# -- aggregation --------------------------------------------------------------

_KBN_LIMIT = 4503599627370496  # 2**52


def _c_mod(a: int, b: int) -> int:
    r = abs(a) % b
    return -r if a < 0 else r


class _Sum:
    """SQLite's sum()/total()/avg() accumulator (Kahan-Babuska-Neumaier summation)."""

    def __init__(self):
        self.cnt = 0
        self.isum = 0
        self.rsum = 0.0
        self.rerr = 0.0
        self.approx = False
        self.overflow = False

    def _kbn(self, r: float) -> None:
        s = self.rsum
        t = s + r
        if abs(s) > abs(r):
            self.rerr += (s - t) + r
        else:
            self.rerr += (r - t) + s
        self.rsum = t

    def _kbn_int(self, v: int) -> None:
        if v <= -_KBN_LIMIT or v >= _KBN_LIMIT:
            small = _c_mod(v, 16384)
            self._kbn(float(v - small))
            self._kbn(float(small))
        else:
            self._kbn(float(v))

    def _kbn_init(self, v: int) -> None:
        if v <= -_KBN_LIMIT or v >= _KBN_LIMIT:
            small = _c_mod(v, 16384)
            self.rsum = float(v - small)
            self.rerr = float(small)
        else:
            self.rsum = float(v)
            self.rerr = 0.0

    def step(self, value) -> None:
        if value is None:
            return
        self.cnt += 1
        if isinstance(value, str):
            num = parse_exact_number(value)
            value = float(text_to_number(value)) if num is None else num
        if isinstance(value, int):
            if not self.approx:
                total = self.isum + value
                if INT_MIN <= total <= INT_MAX:
                    self.isum = total
                    return
                self.approx = True
                self.overflow = True
                self._kbn_init(self.isum)
            self._kbn_int(value)
        else:
            if not self.approx:
                self.approx = True
                self._kbn_init(self.isum)
            self._kbn(value)

    def _real(self) -> float:
        if self.rerr in (float("inf"), float("-inf")) or self.rerr != self.rerr:
            return self.rsum
        return self.rsum + self.rerr

    def sum(self):
        if self.cnt == 0:
            return None
        if self.approx:
            if self.overflow:
                raise SQLError("integer overflow")
            return self._real()
        return self.isum

    def total(self) -> float:
        if self.cnt == 0:
            return 0.0
        return self._real() if self.approx else float(self.isum)

    def avg(self):
        if self.cnt == 0:
            return None
        total = self._real() if self.approx else float(self.isum)
        return total / self.cnt


def _dedup(values: list) -> list:
    seen = set()
    out = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _aggregate(aggs: list[AggSpec], rows: list, width: int):
    """Compute aggregate values for one group; return the evaluation env for the group.

    Bare columns are evaluated against a representative row, chosen like SQLite does: the
    row that most recently updated a MIN()/MAX() aggregate, otherwise the group's first row.
    """
    values = []
    rep_index = None
    for spec in aggs:
        if spec.arg is None:
            values.append(len(rows))
            continue
        pairs = [(spec.arg((row, None)), i) for i, row in enumerate(rows)]
        pairs = [(v, i) for v, i in pairs if v is not None]
        name = spec.name
        if name in ("min", "max"):
            want = 1 if name == "max" else -1
            best = None
            best_index = None
            for v, i in pairs:
                if best_index is None or compare(v, best) == want:
                    best, best_index = v, i
            values.append(best)
            if best_index is not None and (rep_index is None or best_index > rep_index):
                rep_index = best_index
            continue
        vals = [v for v, _ in pairs]
        if spec.distinct:
            vals = _dedup(vals)
        if name == "count":
            values.append(len(vals))
            continue
        acc = _Sum()
        for v in vals:
            acc.step(v)
        if name == "sum":
            values.append(acc.sum())
        elif name == "total":
            values.append(acc.total())
        else:
            values.append(acc.avg())
    if not rows:
        rep = [None] * width
    else:
        rep = rows[rep_index if rep_index is not None else 0]
    return (rep, values)
