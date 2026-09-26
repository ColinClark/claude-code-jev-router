"""Statement execution against in-memory tables."""

from __future__ import annotations

from dataclasses import dataclass, field

from minisql import values as V
from minisql.errors import SQLError
from minisql.parser import (
    Between,
    Binary,
    BoolTest,
    Bound,
    Call,
    ColumnRef,
    CreateTable,
    Delete,
    Expr,
    In,
    Insert,
    Like,
    Literal,
    OrderTerm,
    Select,
    Star,
    TableRef,
    TrueFalse,
    Unary,
    Update,
)

AGGREGATES = frozenset({"COUNT", "SUM", "TOTAL", "AVG", "MIN", "MAX"})


@dataclass
class Table:
    name: str
    columns: list[str]
    affinities: list[str]
    rows: list[list[object]] = field(default_factory=list)

    def column_index(self, name: str) -> int:
        lname = name.lower()
        for i, c in enumerate(self.columns):
            if c.lower() == lname:
                return i
        raise SQLError(f"table {self.name} has no column named {name}")


@dataclass
class ScopeEntry:
    alias: str
    table: Table
    offset: int


class NoSuchColumn(SQLError):
    """Raised when a column reference matches nothing (as opposed to being ambiguous)."""


class Scope:
    """Column-resolution scope for a FROM clause: a list of tables laid out side by side."""

    def __init__(self) -> None:
        self.entries: list[ScopeEntry] = []
        self.width = 0

    def add(self, alias: str, table: Table) -> ScopeEntry:
        entry = ScopeEntry(alias, table, self.width)
        self.entries.append(entry)
        self.width += len(table.columns)
        return entry

    def resolve(self, ref: ColumnRef) -> Bound:
        lname = ref.name.lower()
        matches: list[Bound] = []
        for entry in self.entries:
            if ref.table is not None and entry.alias.lower() != ref.table.lower():
                continue
            for i, col in enumerate(entry.table.columns):
                if col.lower() == lname:
                    matches.append(Bound(entry.offset + i, entry.table.affinities[i], col))
        if not matches:
            if ref.table is not None:
                raise NoSuchColumn(f"no such column: {ref.table}.{ref.name}")
            raise NoSuchColumn(f"no such column: {ref.name}")
        if len(matches) > 1:
            raise SQLError(f"ambiguous column name: {ref.name}")
        return matches[0]

    def expand_star(self, table: str | None) -> list[Bound]:
        out: list[Bound] = []
        found = False
        for entry in self.entries:
            if table is not None and entry.alias.lower() != table.lower():
                continue
            found = True
            for i, col in enumerate(entry.table.columns):
                out.append(Bound(entry.offset + i, entry.table.affinities[i], col))
        if not found:
            if table is None:
                raise SQLError("no tables specified")
            raise SQLError(f"no such table: {table}")
        return out


# ----------------------------------------------------------------------------
# Binding: resolve column references, validate functions
# ----------------------------------------------------------------------------

SCALAR_FUNCTIONS = frozenset(
    {"TYPEOF", "COALESCE", "IFNULL", "NULLIF", "ABS", "LENGTH", "UPPER", "LOWER"}
)


def bind(expr: Expr, scope: Scope, aliases: dict[str, Expr] | None = None) -> Expr:
    """Return a copy of ``expr`` with column references resolved against ``scope``.

    ``aliases`` maps lower-cased explicit output aliases to already-bound expressions; an
    unqualified name that is not found in the scope falls back to them (WHERE / GROUP BY /
    HAVING / ORDER BY), as in SQLite.
    """
    match expr:
        case Literal() | TrueFalse() | Bound():
            return expr
        case ColumnRef():
            try:
                return scope.resolve(expr)
            except NoSuchColumn:
                if aliases is not None and expr.table is None and expr.name.lower() in aliases:
                    return aliases[expr.name.lower()]
                raise
        case Star():
            raise SQLError("'*' is not allowed here")
        case Unary(op, operand):
            return Unary(op, bind(operand, scope, aliases))
        case Binary(op, left, right):
            return Binary(op, bind(left, scope, aliases), bind(right, scope, aliases))
        case BoolTest(operand, target, negated):
            return BoolTest(bind(operand, scope, aliases), target, negated)
        case In(operand, items, negated):
            return In(bind(operand, scope, aliases), [bind(i, scope, aliases) for i in items],
                      negated)
        case Between(operand, low, high, negated):
            return Between(bind(operand, scope, aliases), bind(low, scope, aliases),
                           bind(high, scope, aliases), negated)
        case Like(operand, pattern, negated):
            return Like(bind(operand, scope, aliases), bind(pattern, scope, aliases), negated)
        case Call(name, args, distinct, star):
            if name in ("MIN", "MAX") and len(args) >= 2 and not distinct:
                pass  # scalar multi-argument min()/max()
            elif name in AGGREGATES:
                if star:
                    if name != "COUNT":
                        raise SQLError(f"wrong number of arguments to function {name}()")
                elif len(args) != 1:
                    raise SQLError(f"wrong number of arguments to function {name}()")
            elif name in SCALAR_FUNCTIONS:
                if star or distinct:
                    raise SQLError(f"syntax error in call to {name}()")
                _check_scalar_arity(name, len(args))
            else:
                raise SQLError(f"no such function: {name}")
            return Call(name, [bind(a, scope, aliases) for a in args], distinct, star)
    raise SQLError("unsupported expression")


def _check_scalar_arity(name: str, n: int) -> None:
    ok = {
        "TYPEOF": (1, 1), "COALESCE": (2, None), "IFNULL": (2, 2), "NULLIF": (2, 2),
        "ABS": (1, 1), "LENGTH": (1, 1), "UPPER": (1, 1), "LOWER": (1, 1),
    }[name]
    if n < ok[0] or (ok[1] is not None and n > ok[1]):
        raise SQLError(f"wrong number of arguments to function {name}()")


def is_aggregate_call(call: Call) -> bool:
    if call.name in ("MIN", "MAX"):
        return call.star or len(call.args) == 1
    return call.name in AGGREGATES


def contains_aggregate(expr: Expr) -> bool:
    return bool(collect_aggregates(expr))


def collect_aggregates(expr: Expr, out: list[Call] | None = None) -> list[Call]:
    if out is None:
        out = []
    match expr:
        case Call(_, args):
            if is_aggregate_call(expr):
                out.append(expr)
            else:
                for a in args:
                    collect_aggregates(a, out)
        case Unary(_, operand) | BoolTest(operand):
            collect_aggregates(operand, out)
        case Binary(_, left, right):
            collect_aggregates(left, out)
            collect_aggregates(right, out)
        case In(operand, items, _):
            collect_aggregates(operand, out)
            for i in items:
                collect_aggregates(i, out)
        case Between(operand, low, high, _):
            for e in (operand, low, high):
                collect_aggregates(e, out)
        case Like(operand, pattern, _):
            collect_aggregates(operand, out)
            collect_aggregates(pattern, out)
    return out


def constant_integer(expr: Expr) -> int | None:
    """Integer value of an integer literal under any number of unary +/- (SQLite treats such
    ORDER BY / GROUP BY terms as positional column references)."""
    sign = 1
    while isinstance(expr, Unary) and expr.op in ("-", "+"):
        if expr.op == "-":
            sign = -sign
        expr = expr.operand
    if isinstance(expr, Literal) and isinstance(expr.value, int):
        return sign * expr.value
    return None


def expr_affinity(expr: Expr) -> str | None:
    if isinstance(expr, Bound):
        return expr.affinity
    return None


# ----------------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------------

Row = list


class Context:
    """Evaluation context: the current row plus, for aggregate queries, the group rows."""

    __slots__ = ("row", "group")

    def __init__(self, row: Row, group: list[Row] | None) -> None:
        self.row = row
        self.group = group


def evaluate(expr: Expr, ctx: Context) -> object:
    match expr:
        case Literal(value):
            return value
        case TrueFalse(value):
            return int(value)
        case Bound(index):
            return ctx.row[index]
        case Unary(op, operand):
            v = evaluate(operand, ctx)
            if op == "-":
                return V.negate(v)
            if op == "+":
                return v
            return V.bool_to_int(V.not3(V.truth(v)))
        case Binary(op, left, right):
            return _eval_binary(op, left, right, ctx)
        case BoolTest(operand, target, negated):
            t = V.truth(evaluate(operand, ctx))
            hit = t is not None and t == target
            return int(hit != negated)
        case In(operand, items, negated):
            v = evaluate(operand, ctx)
            if not items:
                return int(negated)
            if v is None:
                return None
            aff = expr_affinity(operand)
            result: bool | None = False
            for item in items:
                iv = evaluate(item, ctx)
                a, b = V.coerce_for_comparison(v, iv, aff, None)
                c = V.compare_op("=", a, b)
                if c is True:
                    result = True
                    break
                if c is None:
                    result = None
            if negated:
                result = V.not3(result)
            return V.bool_to_int(result)
        case Between(operand, low, high, negated):
            v = evaluate(operand, ctx)
            lo = evaluate(low, ctx)
            hi = evaluate(high, ctx)
            aff = expr_affinity(operand)
            a, b = V.coerce_for_comparison(v, lo, aff, expr_affinity(low))
            ge = V.compare_op(">=", a, b)
            a, b = V.coerce_for_comparison(v, hi, aff, expr_affinity(high))
            le = V.compare_op("<=", a, b)
            result = V.and3(ge, le)
            if negated:
                result = V.not3(result)
            return V.bool_to_int(result)
        case Like(operand, pattern, negated):
            result = V.like(evaluate(operand, ctx), evaluate(pattern, ctx))
            if negated:
                result = V.not3(result)
            return V.bool_to_int(result)
        case Call(name, args, distinct, star):
            if is_aggregate_call(expr):
                if ctx.group is None:
                    raise SQLError(f"misuse of aggregate function {name}()")
                return _eval_aggregate(name, args, distinct, star, ctx.group)
            return _eval_scalar(name, [evaluate(a, ctx) for a in args])
    raise SQLError("unsupported expression")


def _eval_binary(op: str, left: Expr, right: Expr, ctx: Context) -> object:
    if op == "AND":
        a = V.truth(evaluate(left, ctx))
        if a is False:
            return 0
        return V.bool_to_int(V.and3(a, V.truth(evaluate(right, ctx))))
    if op == "OR":
        a = V.truth(evaluate(left, ctx))
        if a is True:
            return 1
        return V.bool_to_int(V.or3(a, V.truth(evaluate(right, ctx))))
    lv = evaluate(left, ctx)
    rv = evaluate(right, ctx)
    if op in ("+", "-", "*", "/", "%"):
        return V.arith(op, lv, rv)
    if op == "||":
        return V.concat(lv, rv)
    a, b = V.coerce_for_comparison(lv, rv, expr_affinity(left), expr_affinity(right))
    if op == "IS":
        return int(V.is_op(a, b))
    if op == "IS NOT":
        return int(not V.is_op(a, b))
    return V.bool_to_int(V.compare_op(op, a, b))


def _eval_scalar(name: str, args: list[object]) -> object:
    if name == "TYPEOF":
        v = args[0]
        if v is None:
            return "null"
        if isinstance(v, int):
            return "integer"
        if isinstance(v, float):
            return "real"
        return "text"
    if name == "COALESCE":
        for v in args:
            if v is not None:
                return v
        return None
    if name == "IFNULL":
        return args[0] if args[0] is not None else args[1]
    if name == "NULLIF":
        a, b = args
        if a is None or b is None:
            return a
        return None if V.compare(a, b) == 0 else a
    if name == "ABS":
        v = V.to_numeric(args[0])
        if v is None:
            return None
        if isinstance(args[0], str):
            return abs(float(v))
        if isinstance(v, int) and v == V.INT_MIN:
            raise SQLError("integer overflow")
        return abs(v)
    if name in ("MIN", "MAX"):
        if any(a is None for a in args):
            return None
        best = args[0]
        for a in args[1:]:
            c = V.compare(a, best)
            if (name == "MIN" and c < 0) or (name == "MAX" and c > 0):
                best = a
        return best
    if name == "LENGTH":
        t = V.to_text(args[0])
        return None if t is None else len(t)
    if name == "UPPER":
        t = V.to_text(args[0])
        return None if t is None else "".join(c.upper() if c.isascii() else c for c in t)
    if name == "LOWER":
        t = V.to_text(args[0])
        return None if t is None else "".join(c.lower() if c.isascii() else c for c in t)
    raise SQLError(f"no such function: {name}")


def _aggregate_values(arg: Expr, distinct: bool, group: list[Row]) -> list[object]:
    vals: list[object] = []
    seen: set = set()
    for row in group:
        v = evaluate(arg, Context(row, None))
        if v is None:
            continue
        if distinct:
            if v in seen:
                continue
            seen.add(v)
        vals.append(v)
    return vals


class _Sum:
    """SQLite's SUM accumulator: exact integer sum until a non-integer arrives, then
    Kahan-Babuska-Neumaier compensated floating-point summation."""

    __slots__ = ("isum", "rsum", "rerr", "approx", "overflow")

    def __init__(self) -> None:
        self.isum = 0
        self.rsum = 0.0
        self.rerr = 0.0
        self.approx = False
        self.overflow = False

    def add(self, v: object) -> None:
        if isinstance(v, str):
            n = V.text_to_number(v)
            if n is None:
                n = float(V.numeric_prefix(v))
        else:
            n = v
        if not self.approx:
            if isinstance(n, int):
                total = self.isum + n
                if V.INT_MIN <= total <= V.INT_MAX:
                    self.isum = total
                    return
                self.overflow = True
            self._init_real()
        elif not isinstance(n, int):
            self.overflow = False
        self._step(float(n))  # type: ignore[arg-type]

    def _init_real(self) -> None:
        self.rsum = float(self.isum)
        self.rerr = 0.0
        self.approx = True

    def _step(self, r: float) -> None:
        s = self.rsum
        t = s + r
        if abs(s) > abs(r):
            self.rerr += (s - t) + r
        else:
            self.rerr += (r - t) + s
        self.rsum = t

    def real_value(self) -> float:
        if not self.approx:
            return float(self.isum)
        return self.rsum + self.rerr

    def value(self) -> int | float:
        if not self.approx:
            return self.isum
        if self.overflow:
            raise SQLError("integer overflow")
        return self.rsum + self.rerr


def _eval_aggregate(
    name: str, args: list[Expr], distinct: bool, star: bool, group: list[Row]
) -> object:
    if name == "COUNT":
        if star:
            return len(group)
        return len(_aggregate_values(args[0], distinct, group))
    vals = _aggregate_values(args[0], distinct, group)
    if name in ("SUM", "TOTAL", "AVG"):
        if not vals:
            return 0.0 if name == "TOTAL" else None
        total = _Sum()
        for v in vals:
            total.add(v)
        if name == "AVG":
            return total.real_value() / len(vals)
        if name == "TOTAL":
            return total.real_value()
        return total.value()
    if name in ("MIN", "MAX"):
        best: object = None
        for v in vals:
            if best is None:
                best = v
            else:
                c = V.compare(v, best)
                if (name == "MIN" and c < 0) or (name == "MAX" and c > 0):
                    best = v
        return best
    raise SQLError(f"no such function: {name}")


def _min_max_row(call: Call, group: list[Row]) -> Row:
    """Row whose values SQLite reports for bare columns when ``call`` is the deciding
    MIN()/MAX(): the first row attaining the extreme (rows whose argument is NULL only
    count while no non-NULL value has been seen yet)."""
    rep = group[0]
    best: object = None
    for row in group:
        v = evaluate(call.args[0], Context(row, None))
        if v is None:
            if best is None:
                rep = row
            continue
        if best is None:
            best, rep = v, row
        else:
            c = V.compare(v, best)
            if (call.name == "MIN" and c < 0) or (call.name == "MAX" and c > 0):
                best, rep = v, row
    return rep


# ----------------------------------------------------------------------------
# Executor
# ----------------------------------------------------------------------------


class Executor:
    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}

    def get_table(self, name: str) -> Table:
        table = self.tables.get(name.lower())
        if table is None:
            raise SQLError(f"no such table: {name}")
        return table

    # -- DDL / DML ------------------------------------------------------------

    def create_table(self, stmt: CreateTable) -> list[tuple]:
        key = stmt.name.lower()
        if key in self.tables:
            raise SQLError(f"table {stmt.name} already exists")
        seen: set[str] = set()
        for col in stmt.columns:
            if col.name.lower() in seen:
                raise SQLError(f"duplicate column name: {col.name}")
            seen.add(col.name.lower())
        self.tables[key] = Table(
            stmt.name,
            [c.name for c in stmt.columns],
            [V.affinity_from_type(c.type_name) for c in stmt.columns],
        )
        return []

    def insert(self, stmt: Insert) -> list[tuple]:
        table = self.get_table(stmt.table)
        if stmt.columns is None:
            targets = list(range(len(table.columns)))
        else:
            targets = [table.column_index(c) for c in stmt.columns]
            if len(set(targets)) != len(targets):
                raise SQLError("duplicate column in INSERT column list")
        scope = Scope()
        new_rows: list[Row] = []
        for values in stmt.rows:
            if len(values) != len(targets):
                raise SQLError(
                    f"table {table.name} has {len(targets)} columns but "
                    f"{len(values)} values were supplied"
                )
            row: Row = [None] * len(table.columns)
            ctx = Context([], None)
            for idx, expr in zip(targets, values, strict=True):
                row[idx] = V.apply_affinity(evaluate(bind(expr, scope), ctx),
                                            table.affinities[idx])
            new_rows.append(row)
        table.rows.extend(new_rows)
        return []

    def update(self, stmt: Update) -> list[tuple]:
        table = self.get_table(stmt.table)
        scope = Scope()
        scope.add(table.name, table)
        assignments = [(table.column_index(c), bind(e, scope)) for c, e in stmt.assignments]
        where = bind(stmt.where, scope) if stmt.where is not None else None
        for row in table.rows:
            ctx = Context(row, None)
            if where is not None and V.truth(evaluate(where, ctx)) is not True:
                continue
            new_values = [(idx, evaluate(e, ctx)) for idx, e in assignments]
            for idx, v in new_values:
                row[idx] = V.apply_affinity(v, table.affinities[idx])
        return []

    def delete(self, stmt: Delete) -> list[tuple]:
        table = self.get_table(stmt.table)
        if stmt.where is None:
            table.rows.clear()
            return []
        scope = Scope()
        scope.add(table.name, table)
        where = bind(stmt.where, scope)
        table.rows = [
            row for row in table.rows if V.truth(evaluate(where, Context(row, None))) is not True
        ]
        return []

    # -- SELECT ---------------------------------------------------------------

    def select(self, stmt: Select) -> list[tuple]:
        scope = Scope()
        rows = self._from_rows(stmt, scope)

        # Output columns; only explicit aliases (AS name / bare name) are visible by name.
        out_exprs: list[Expr] = []
        out_names: list[str | None] = []
        for item in stmt.items:
            if isinstance(item.expr, Star):
                for b in scope.expand_star(item.expr.table):
                    out_exprs.append(b)
                    out_names.append(None)
            else:
                out_exprs.append(bind(item.expr, scope))
                out_names.append(item.alias)
        aliases: dict[str, Expr] = {}
        for name, e in zip(out_names, out_exprs, strict=True):
            if name is not None and name.lower() not in aliases:
                aliases[name.lower()] = e

        if stmt.where is not None:
            where = bind(stmt.where, scope, aliases)
            if contains_aggregate(where):
                raise SQLError("misuse of aggregate in WHERE clause")
            rows = [r for r in rows if V.truth(evaluate(where, Context(r, None))) is True]

        group_by = [self._bind_group_term(g, scope, aliases, out_exprs) for g in stmt.group_by]
        having = bind(stmt.having, scope, aliases) if stmt.having is not None else None

        # ORDER BY terms: either an output column index or an expression.
        order_keys: list[tuple[int | None, Expr | None, bool]] = []
        for term in stmt.order_by:
            idx, expr = self._bind_order_term(term, scope, aliases, out_names, len(out_exprs))
            order_keys.append((idx, expr, term.desc))

        aggregate_mode = (
            bool(group_by)
            or having is not None
            or any(contains_aggregate(e) for e in out_exprs)
            or any(e is not None and contains_aggregate(e) for _, e, _ in order_keys)
        )

        results: list[tuple] = []
        sort_keys: list[list[object]] = []
        if aggregate_mode:
            deciding = self._last_min_max(out_exprs, having, order_keys)
            for group in self._groups(rows, group_by, scope):
                rep = self._representative_row(group, deciding, scope.width)
                ctx = Context(rep, group)
                if having is not None and V.truth(evaluate(having, ctx)) is not True:
                    continue
                self._emit(ctx, out_exprs, order_keys, results, sort_keys)
        else:
            for row in rows:
                self._emit(Context(row, None), out_exprs, order_keys, results, sort_keys)

        if stmt.distinct:
            seen: set[tuple] = set()
            kept: list[tuple] = []
            kept_keys: list[list[object]] = []
            for r, k in zip(results, sort_keys, strict=True):
                if r in seen:
                    continue
                seen.add(r)
                kept.append(r)
                kept_keys.append(k)
            results, sort_keys = kept, kept_keys

        if order_keys:
            order = list(range(len(results)))
            for pos in range(len(order_keys) - 1, -1, -1):
                desc = order_keys[pos][2]
                order.sort(key=lambda i, p=pos: V.sort_key(sort_keys[i][p]), reverse=desc)
            results = [results[i] for i in order]

        if stmt.limit is not None:
            limit = self._constant_int(stmt.limit, "LIMIT")
            offset = self._constant_int(stmt.offset, "OFFSET") if stmt.offset is not None else 0
            offset = max(offset, 0)
            if limit < 0:
                results = results[offset:]
            else:
                results = results[offset:offset + limit]
        return results

    def _from_rows(self, stmt: Select, scope: Scope) -> list[Row]:
        if stmt.from_table is None:
            return [[]]
        first = self.get_table(stmt.from_table.name)
        scope.add(stmt.from_table.alias, first)
        entries = [self._add_join_table(scope, j.table) for j in stmt.joins]
        width = scope.width
        rows: list[Row] = [list(r) + [None] * (width - len(r)) for r in first.rows]
        for join, entry in zip(stmt.joins, entries, strict=True):
            on = bind(join.on, scope) if join.on is not None else None
            if on is not None and contains_aggregate(on):
                raise SQLError("misuse of aggregate in ON clause")
            off = entry.offset
            n = len(entry.table.columns)
            joined: list[Row] = []
            for left in rows:
                matched = False
                for right in entry.table.rows:
                    cand = left[:]
                    cand[off:off + n] = right
                    if on is None or V.truth(evaluate(on, Context(cand, None))) is True:
                        joined.append(cand)
                        matched = True
                if not matched and join.kind == "LEFT":
                    joined.append(left[:])
            rows = joined
        return rows

    def _add_join_table(self, scope: Scope, ref: TableRef) -> ScopeEntry:
        table = self.get_table(ref.name)
        return scope.add(ref.alias, table)

    def _bind_group_term(
        self, term: Expr, scope: Scope, aliases: dict[str, Expr], out_exprs: list[Expr]
    ) -> Expr:
        position = constant_integer(term)
        if position is not None:
            if not 1 <= position <= len(out_exprs):
                raise SQLError(
                    f"GROUP BY term out of range - should be between 1 and {len(out_exprs)}"
                )
            bound = out_exprs[position - 1]
        else:
            bound = bind(term, scope, aliases)
        if contains_aggregate(bound):
            raise SQLError("aggregate functions are not allowed in the GROUP BY clause")
        return bound

    def _bind_order_term(
        self,
        term: OrderTerm,
        scope: Scope,
        aliases: dict[str, Expr],
        out_names: list[str | None],
        n_out: int,
    ) -> tuple[int | None, Expr | None]:
        expr = term.expr
        position = constant_integer(expr)
        if position is not None:
            if not 1 <= position <= n_out:
                raise SQLError(f"ORDER BY term out of range - should be between 1 and {n_out}")
            return position - 1, None
        if isinstance(expr, ColumnRef) and expr.table is None:
            lname = expr.name.lower()
            for i, name in enumerate(out_names):
                if name is not None and name.lower() == lname:
                    return i, None
        return None, bind(expr, scope, aliases)

    @staticmethod
    def _last_min_max(
        out_exprs: list[Expr],
        having: Expr | None,
        order_keys: list[tuple[int | None, Expr | None, bool]],
    ) -> Call | None:
        """The MIN()/MAX() aggregate that decides bare-column values, as in SQLite: the last
        distinct one in analysis order (select list, ORDER BY, then HAVING)."""
        calls: list[Call] = []
        found: list[Call] = []
        for e in out_exprs:
            collect_aggregates(e, found)
        for _, e, _ in order_keys:
            if e is not None:
                collect_aggregates(e, found)
        if having is not None:
            collect_aggregates(having, found)
        for c in found:
            if c not in calls:
                calls.append(c)
        for c in reversed(calls):
            if c.name in ("MIN", "MAX") and not c.star and len(c.args) == 1:
                return c
        return None

    @staticmethod
    def _groups(rows: list[Row], group_by: list[Expr], scope: Scope) -> list[list[Row]]:
        if not group_by:
            return [rows]
        groups: dict[tuple, list[Row]] = {}
        for row in rows:
            ctx = Context(row, None)
            key = tuple(evaluate(g, ctx) for g in group_by)
            groups.setdefault(key, []).append(row)
        return list(groups.values())

    @staticmethod
    def _representative_row(group: list[Row], deciding: Call | None, width: int) -> Row:
        """Row used for non-aggregated column references in an aggregate query."""
        if not group:
            return [None] * width
        if deciding is not None:
            return _min_max_row(deciding, group)
        return group[0]

    @staticmethod
    def _emit(
        ctx: Context,
        out_exprs: list[Expr],
        order_keys: list[tuple[int | None, Expr | None, bool]],
        results: list[tuple],
        sort_keys: list[list[object]],
    ) -> None:
        row = tuple(evaluate(e, ctx) for e in out_exprs)
        results.append(row)
        if order_keys:
            keys: list[object] = []
            for idx, expr, _ in order_keys:
                if idx is not None:
                    keys.append(row[idx])
                else:
                    assert expr is not None
                    keys.append(evaluate(expr, ctx))
            sort_keys.append(keys)
        else:
            sort_keys.append([])

    @staticmethod
    def _constant_int(expr: Expr, what: str) -> int:
        bound = bind(expr, Scope())
        if contains_aggregate(bound):
            raise SQLError(f"misuse of aggregate in {what}")
        v = evaluate(bound, Context([], None))
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if not isinstance(v, int):
            raise SQLError(f"datatype mismatch in {what}")
        return v

    # -- entry point ----------------------------------------------------------

    def execute(self, stmt: object) -> list[tuple]:
        match stmt:
            case CreateTable():
                return self.create_table(stmt)
            case Insert():
                return self.insert(stmt)
            case Update():
                return self.update(stmt)
            case Delete():
                return self.delete(stmt)
            case Select():
                return self.select(stmt)
        raise SQLError("unsupported statement")
