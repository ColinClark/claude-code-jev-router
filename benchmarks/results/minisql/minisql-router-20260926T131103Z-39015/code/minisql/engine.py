"""Database object, expression compiler and statement executor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cmp_to_key

from minisql import values as V
from minisql.errors import SQLError
from minisql.functions import (
    AGGREGATE_FUNCTIONS,
    SCALAR_FUNCTIONS,
    Aggregate,
    CountStar,
    Distinct,
    is_aggregate_call,
)
from minisql.parser import (
    Between,
    Binary,
    Case,
    Cast,
    ColumnRef,
    CreateTable,
    Delete,
    DropTable,
    Expr,
    FuncCall,
    InList,
    Insert,
    Like,
    Literal,
    Select,
    Unary,
    Update,
    parse,
)
from minisql.values import Value

Row = tuple
Fn = Callable[[Row], Value]

_NUMERIC_AFFS = (V.INTEGER, V.REAL, V.NUMERIC)


@dataclass
class Table:
    name: str
    columns: list[str]
    affinities: list[str]
    rows: list[tuple] = field(default_factory=list)

    def column_index(self, name: str) -> int | None:
        low = name.lower()
        for i, c in enumerate(self.columns):
            if c.lower() == low:
                return i
        return None


@dataclass
class Source:
    alias: str
    table: Table
    offset: int


@dataclass
class AggSlot:
    node: FuncCall
    slot: int


class Context:
    """Name-resolution and compilation context for expressions."""

    def __init__(
        self,
        sources: list[Source],
        aliases: dict[str, Expr] | None = None,
        agg_mode: bool = False,
        agg_base: int = 0,
        clause: str = "",
    ):
        self.sources = sources
        self.aliases = aliases
        self.agg_mode = agg_mode
        self.agg_base = agg_base
        self.aggs: list[FuncCall] = []
        self._agg_index: dict[int, int] = {}
        self.clause = clause

    def without_aliases(self) -> Context:
        ctx = Context(self.sources, None, self.agg_mode, self.agg_base, self.clause)
        ctx.aggs = self.aggs
        ctx._agg_index = self._agg_index
        return ctx

    def agg_slot(self, node: FuncCall) -> int:
        key = id(node)
        if key not in self._agg_index:
            self._agg_index[key] = len(self.aggs)
            self.aggs.append(node)
        return self._agg_index[key]

    def resolve(self, ref: ColumnRef) -> tuple[int, str] | None:
        """Return (row index, affinity) for a column reference, or None if unknown."""
        name = ref.name
        if ref.table is not None:
            tlow = ref.table.lower()
            matches = [s for s in self.sources if s.alias.lower() == tlow]
            if not matches:
                return None
            src = matches[0]
            idx = src.table.column_index(name)
            if idx is None:
                return None
            return src.offset + idx, src.table.affinities[idx]
        found: list[tuple[int, str]] = []
        for src in self.sources:
            idx = src.table.column_index(name)
            if idx is not None:
                found.append((src.offset + idx, src.table.affinities[idx]))
        if len(found) > 1:
            raise SQLError(f"ambiguous column name: {name}")
        return found[0] if found else None


def _contains_aggregate(node: object) -> bool:
    if isinstance(node, FuncCall):
        if is_aggregate_call(node.name, len(node.args), node.star):
            return True
        return any(_contains_aggregate(a) for a in node.args)
    if isinstance(node, Unary):
        return _contains_aggregate(node.operand)
    if isinstance(node, Binary):
        return _contains_aggregate(node.left) or _contains_aggregate(node.right)
    if isinstance(node, InList):
        return _contains_aggregate(node.expr) or any(_contains_aggregate(i) for i in node.items)
    if isinstance(node, Between):
        return any(_contains_aggregate(x) for x in (node.expr, node.low, node.high))
    if isinstance(node, Like):
        return any(_contains_aggregate(x) for x in (node.expr, node.pattern, node.escape))
    if isinstance(node, Case):
        parts = [node.base, node.else_] + [x for pair in node.whens for x in pair]
        return any(_contains_aggregate(x) for x in parts)
    if isinstance(node, Cast):
        return _contains_aggregate(node.expr)
    return False


# ---------------------------------------------------------------------------
# Expression compiler: AST -> closure(row) -> value
# ---------------------------------------------------------------------------


def _cmp_op(op: str) -> Callable[[Value, Value], Value]:
    compare = V.compare
    if op == "=":
        return lambda a, b: None if a is None or b is None else int(compare(a, b) == 0)
    if op == "!=":
        return lambda a, b: None if a is None or b is None else int(compare(a, b) != 0)
    if op == "<":
        return lambda a, b: None if a is None or b is None else int(compare(a, b) < 0)
    if op == "<=":
        return lambda a, b: None if a is None or b is None else int(compare(a, b) <= 0)
    if op == ">":
        return lambda a, b: None if a is None or b is None else int(compare(a, b) > 0)
    if op == ">=":
        return lambda a, b: None if a is None or b is None else int(compare(a, b) >= 0)
    if op == "IS":
        return lambda a, b: int(compare(a, b) == 0)
    if op == "IS NOT":
        return lambda a, b: int(compare(a, b) != 0)
    raise SQLError(f"unknown operator {op}")


def _affinity_converters(
    aff_l: str | None, aff_r: str | None
) -> tuple[Callable[[Value], Value] | None, Callable[[Value], Value] | None]:
    """Converters applied to (left, right) operands before comparison (SQLite rules)."""
    num = V.numeric_affinity_for_compare

    def text(v: Value) -> Value:
        return V.to_text(v)

    if aff_l is not None and aff_r is not None:
        if aff_l in _NUMERIC_AFFS or aff_r in _NUMERIC_AFFS:
            return (
                num if aff_l not in _NUMERIC_AFFS else None,
                num if aff_r not in _NUMERIC_AFFS else None,
            )
        return None, None
    if aff_l is None and aff_r is None:
        return None, None
    aff = aff_l if aff_l is not None else aff_r
    conv: Callable[[Value], Value] | None
    if aff in _NUMERIC_AFFS:
        conv = num
    elif aff == V.TEXT:
        conv = text
    else:
        conv = None
    if aff_l is None:
        return conv, None
    return None, conv


class Compiler:
    def __init__(self, ctx: Context):
        self.ctx = ctx

    def compile(self, node: Expr) -> Fn:
        return self._compile(node)[0]

    def _compile(self, node: Expr) -> tuple[Fn, str | None]:
        method = getattr(self, "_c_" + type(node).__name__, None)
        if method is None:  # pragma: no cover - parser only yields known nodes
            raise SQLError(f"unsupported expression: {type(node).__name__}")
        return method(node)

    def _c_Literal(self, node: Literal) -> tuple[Fn, str | None]:
        value = node.value
        return (lambda row: value), None

    def _c_ColumnRef(self, node: ColumnRef) -> tuple[Fn, str | None]:
        ctx = self.ctx
        resolved = ctx.resolve(node)
        if resolved is None:
            if node.table is None and ctx.aliases and node.name.lower() in ctx.aliases:
                target = ctx.aliases[node.name.lower()]
                return Compiler(ctx.without_aliases())._compile(target)
            full = f"{node.table}.{node.name}" if node.table else node.name
            raise SQLError(f"no such column: {full}")
        idx, aff = resolved
        return (lambda row: row[idx]), aff

    def _c_Unary(self, node: Unary) -> tuple[Fn, str | None]:
        f, aff = self._compile(node.operand)
        if node.op == "-":
            neg = V.negate
            return (lambda row: neg(f(row))), None
        if node.op == "+":
            return f, None
        if node.op == "~":
            bnot = V.bit_not
            return (lambda row: bnot(f(row))), None
        truth = V.truth

        def not_(row: Row) -> Value:
            t = truth(f(row))
            return None if t is None else int(not t)

        return not_, None

    def _c_Binary(self, node: Binary) -> tuple[Fn, str | None]:
        op = node.op
        lf, laff = self._compile(node.left)
        rf, raff = self._compile(node.right)
        truth = V.truth
        if op == "AND":

            def and_(row: Row) -> Value:
                a = truth(lf(row))
                if a is False:
                    return 0
                b = truth(rf(row))
                if b is False:
                    return 0
                if a is None or b is None:
                    return None
                return 1

            return and_, None
        if op == "OR":

            def or_(row: Row) -> Value:
                a = truth(lf(row))
                if a is True:
                    return 1
                b = truth(rf(row))
                if b is True:
                    return 1
                if a is None or b is None:
                    return None
                return 0

            return or_, None
        if op in ("+", "-", "*", "/", "%"):
            arith = V.arith
            return (lambda row: arith(op, lf(row), rf(row))), None
        if op in ("&", "|", "<<", ">>"):
            bitwise = V.bitwise
            return (lambda row: bitwise(op, lf(row), rf(row))), None
        if op == "||":
            concat = V.concat
            return (lambda row: concat(lf(row), rf(row))), None
        return self._comparison(op, lf, laff, rf, raff), None

    def _comparison(
        self, op: str, lf: Fn, laff: str | None, rf: Fn, raff: str | None
    ) -> Fn:
        cmp = _cmp_op(op)
        cl, cr = _affinity_converters(laff, raff)
        if cl is None and cr is None:
            return lambda row: cmp(lf(row), rf(row))
        if cl is None:
            assert cr is not None
            return lambda row: cmp(lf(row), cr(rf(row)))
        if cr is None:
            return lambda row: cmp(cl(lf(row)), rf(row))
        return lambda row: cmp(cl(lf(row)), cr(rf(row)))

    def _c_InList(self, node: InList) -> tuple[Fn, str | None]:
        ef, eaff = self._compile(node.expr)
        items = [self._compile(i)[0] for i in node.items]
        negated = node.negated
        conv: Callable[[Value], Value] | None = None
        if eaff in _NUMERIC_AFFS:
            conv = V.numeric_affinity_for_compare
        elif eaff == V.TEXT:
            conv = V.to_text
        compare = V.compare

        def in_(row: Row) -> Value:
            if not items:
                return int(negated)
            v = ef(row)
            if v is None:
                return None
            saw_null = False
            for f in items:
                x = f(row)
                if x is None:
                    saw_null = True
                    continue
                if conv is not None:
                    x = conv(x)
                if compare(v, x) == 0:
                    return int(not negated)
            if saw_null:
                return None
            return int(negated)

        return in_, None

    def _c_Between(self, node: Between) -> tuple[Fn, str | None]:
        ef, eaff = self._compile(node.expr)
        lof, loaff = self._compile(node.low)
        hif, hiaff = self._compile(node.high)
        ge = self._comparison(">=", lambda r: r[0], eaff, lambda r: r[1], loaff)
        le = self._comparison("<=", lambda r: r[0], eaff, lambda r: r[1], hiaff)
        negated = node.negated
        truth = V.truth

        def between(row: Row) -> Value:
            v = ef(row)
            a = truth(ge((v, lof(row))))
            if a is False:
                result: bool | None = False
            else:
                b = truth(le((v, hif(row))))
                if b is False:
                    result = False
                elif a is None or b is None:
                    result = None
                else:
                    result = True
            if result is None:
                return None
            return int(result != negated)

        return between, None

    def _c_Like(self, node: Like) -> tuple[Fn, str | None]:
        ef = self.compile(node.expr)
        pf = self.compile(node.pattern)
        xf = self.compile(node.escape) if node.escape is not None else None
        negated = node.negated
        like = V.like

        def like_(row: Row) -> Value:
            esc = xf(row) if xf is not None else None
            if xf is not None and esc is None:
                return None
            r = like(ef(row), pf(row), esc)
            if r is None:
                return None
            return 1 - r if negated else r

        return like_, None

    def _c_Cast(self, node: Cast) -> tuple[Fn, str | None]:
        f = self.compile(node.expr)
        type_name = node.type_name
        cast = V.cast
        return (lambda row: cast(f(row), type_name)), V.type_affinity(type_name)

    def _c_Case(self, node: Case) -> tuple[Fn, str | None]:
        whens: list[tuple[Fn, Fn]] = []
        if node.base is not None:
            bf, baff = self._compile(node.base)
            for cond, result in node.whens:
                cf, caff = self._compile(cond)
                eq = self._comparison("=", lambda r: r[0], baff, lambda r: r[1], caff)
                whens.append((self._bind_eq(eq, bf, cf), self.compile(result)))
        else:
            for cond, result in node.whens:
                whens.append((self.compile(cond), self.compile(result)))
        else_f = self.compile(node.else_) if node.else_ is not None else None
        truth = V.truth

        def case(row: Row) -> Value:
            for cf, rf in whens:
                if truth(cf(row)):
                    return rf(row)
            return else_f(row) if else_f is not None else None

        return case, None

    @staticmethod
    def _bind_eq(eq: Fn, bf: Fn, cf: Fn) -> Fn:
        return lambda row: eq((bf(row), cf(row)))

    def _c_FuncCall(self, node: FuncCall) -> tuple[Fn, str | None]:
        name = node.name
        ctx = self.ctx
        if is_aggregate_call(name, len(node.args), node.star):
            _factory, lo, hi = AGGREGATE_FUNCTIONS[name]
            nargs = len(node.args)
            if node.star:
                if name != "count":
                    raise SQLError(f"wrong number of arguments to function {name}()")
            elif not lo <= nargs <= hi or (name == "count" and nargs == 0):
                raise SQLError(f"wrong number of arguments to function {name}()")
            if node.distinct and nargs != 1:
                raise SQLError(
                    f"DISTINCT aggregates must have exactly one argument: {name}()"
                )
            if not ctx.agg_mode:
                if ctx.clause == "GROUP BY":
                    raise SQLError("aggregate functions are not allowed in the GROUP BY clause")
                raise SQLError(f"misuse of aggregate function {name}()")
            idx = ctx.agg_base + ctx.agg_slot(node)
            return (lambda row: row[idx]), None
        if name not in SCALAR_FUNCTIONS:
            if name in AGGREGATE_FUNCTIONS:
                raise SQLError(f"wrong number of arguments to function {name}()")
            raise SQLError(f"no such function: {name}")
        if node.star or node.distinct:
            raise SQLError(f"wrong number of arguments to function {name}()")
        fn, lo, hi = SCALAR_FUNCTIONS[name]
        nargs = len(node.args)
        if nargs < lo or (hi is not None and nargs > hi):
            raise SQLError(f"wrong number of arguments to function {name}()")
        arg_fns = [self.compile(a) for a in node.args]
        if name in ("coalesce", "ifnull"):

            def coalesce(row: Row) -> Value:
                for f in arg_fns:
                    v = f(row)
                    if v is not None:
                        return v
                return None

            return coalesce, None
        if nargs == 1:
            f0 = arg_fns[0]
            return (lambda row: fn(f0(row))), None
        return (lambda row: fn(*[f(row) for f in arg_fns])), None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def _const_int(expr: Expr, what: str) -> int:
    value = Compiler(Context([])).compile(expr)(())
    if isinstance(value, str):
        value = V.numeric_affinity_for_compare(value)
    if isinstance(value, float) and value == int(value):
        value = int(value)
    if not isinstance(value, int):
        raise SQLError("datatype mismatch")
    return value


_ORDINALS = {1: "st", 2: "nd", 3: "rd"}


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else _ORDINALS.get(n % 10, "th")
    return f"{n}{suffix}"


class Database:
    """An in-memory SQL database."""

    def __init__(self) -> None:
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
        except SQLError:
            raise
        except RecursionError as exc:
            raise SQLError("expression tree is too large") from exc
        except (ZeroDivisionError, TypeError, IndexError, KeyError, ValueError,
                OverflowError, AttributeError) as exc:
            raise SQLError(f"internal error: {exc}") from exc

    # -- helpers -------------------------------------------------------------
    def _table(self, name: str) -> Table:
        table = self.tables.get(name.lower())
        if table is None:
            raise SQLError(f"no such table: {name}")
        return table

    # -- DDL -------------------------------------------------------------------
    def _create(self, stmt: CreateTable) -> None:
        key = stmt.name.lower()
        if key in self.tables:
            if stmt.if_not_exists:
                return
            raise SQLError(f"table {stmt.name} already exists")
        seen: set[str] = set()
        for col in stmt.columns:
            if col.name.lower() in seen:
                raise SQLError(f"duplicate column name: {col.name}")
            seen.add(col.name.lower())
        self.tables[key] = Table(
            stmt.name,
            [c.name for c in stmt.columns],
            [V.type_affinity(c.type_name) for c in stmt.columns],
        )

    def _drop(self, stmt: DropTable) -> None:
        key = stmt.name.lower()
        if key not in self.tables:
            if stmt.if_exists:
                return
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[key]

    # -- DML -------------------------------------------------------------------
    def _insert(self, stmt: Insert) -> None:
        table = self._table(stmt.table)
        ncols = len(table.columns)
        if stmt.columns is None:
            targets = list(range(ncols))
        else:
            targets = []
            for name in stmt.columns:
                idx = table.column_index(name)
                if idx is None:
                    raise SQLError(f"table {table.name} has no column named {name}")
                targets.append(idx)
        if stmt.select is not None:
            value_rows: list[tuple] = self._select(stmt.select)
            if value_rows and len(value_rows[0]) != len(targets):
                raise SQLError(
                    f"table {table.name} has {ncols} columns but "
                    f"{len(value_rows[0])} values were supplied"
                )
        else:
            assert stmt.rows is not None
            compiler = Compiler(Context([]))
            value_rows = []
            for exprs in stmt.rows:
                if len(exprs) != len(targets):
                    if stmt.columns is None:
                        raise SQLError(
                            f"table {table.name} has {ncols} columns but "
                            f"{len(exprs)} values were supplied"
                        )
                    raise SQLError(f"{len(exprs)} values for {len(targets)} columns")
                value_rows.append(tuple(compiler.compile(e)(()) for e in exprs))
        new_rows = []
        for vals in value_rows:
            row: list[Value] = [None] * ncols
            for idx, v in zip(targets, vals, strict=True):
                row[idx] = V.apply_affinity(v, table.affinities[idx])
            new_rows.append(tuple(row))
        table.rows.extend(new_rows)

    def _update(self, stmt: Update) -> None:
        table = self._table(stmt.table)
        ctx = Context([Source(table.name, table, 0)])
        compiler = Compiler(ctx)
        where = compiler.compile(stmt.where) if stmt.where is not None else None
        assigns: list[tuple[int, Fn]] = []
        for name, expr in stmt.assignments:
            idx = table.column_index(name)
            if idx is None:
                raise SQLError(f"no such column: {name}")
            assigns.append((idx, compiler.compile(expr)))
        truth = V.truth
        updated: list[tuple] = []
        for row in table.rows:
            if where is None or truth(where(row)):
                new = list(row)
                for idx, f in assigns:
                    new[idx] = V.apply_affinity(f(row), table.affinities[idx])
                updated.append(tuple(new))
            else:
                updated.append(row)
        table.rows = updated

    def _delete(self, stmt: Delete) -> None:
        table = self._table(stmt.table)
        if stmt.where is None:
            table.rows = []
            return
        where = Compiler(Context([Source(table.name, table, 0)])).compile(stmt.where)
        truth = V.truth
        table.rows = [r for r in table.rows if not truth(where(r))]

    # -- SELECT ----------------------------------------------------------------
    def _select(self, stmt: Select) -> list[tuple]:
        # 1. FROM: build sources and the joined row set.
        sources: list[Source] = []
        rows: list[tuple]
        if stmt.from_ is None:
            rows = [()]
        else:
            first = self._table(stmt.from_.first.name)
            sources.append(Source(stmt.from_.first.alias or first.name, first, 0))
            rows = list(first.rows)
            width = len(first.columns)
            truth = V.truth
            for join in stmt.from_.joins:
                table = self._table(join.table.name)
                sources.append(Source(join.table.alias or table.name, table, width))
                on = None
                if join.on is not None:
                    if _contains_aggregate(join.on):
                        raise SQLError("misuse of aggregate function in ON clause")
                    on = Compiler(Context(list(sources))).compile(join.on)
                right = table.rows
                pad = (None,) * len(table.columns)
                joined: list[tuple] = []
                left_join = join.kind == "LEFT"
                for lrow in rows:
                    matched = False
                    for rrow in right:
                        combined = lrow + rrow
                        if on is None or truth(on(combined)):
                            joined.append(combined)
                            matched = True
                    if left_join and not matched:
                        joined.append(lrow + pad)
                rows = joined
                width += len(table.columns)

        aliases: dict[str, Expr] = {}
        for item in stmt.items:
            if item.kind == "expr" and item.alias is not None:
                aliases.setdefault(item.alias.lower(), item.expr)  # type: ignore[arg-type]

        # 2. WHERE
        if stmt.where is not None:
            where = Compiler(Context(sources, aliases, clause="WHERE")).compile(stmt.where)
            truth = V.truth
            rows = [r for r in rows if truth(where(r))]

        is_agg = bool(stmt.group_by) or any(
            item.kind == "expr" and _contains_aggregate(item.expr) for item in stmt.items
        )
        if stmt.having is not None and not is_agg:
            raise SQLError("HAVING clause on a non-aggregate query")

        width = sum(len(s.table.columns) for s in sources)
        ctx = Context(sources, aliases, agg_mode=is_agg, agg_base=width)
        compiler = Compiler(ctx)

        # 3. Output columns
        out_fns: list[Fn] = []
        for item in stmt.items:
            if item.kind == "star":
                if not sources:
                    raise SQLError("no tables specified")
                for src in sources:
                    for i in range(len(src.table.columns)):
                        out_fns.append(self._index_fn(src.offset + i))
            elif item.kind == "table_star":
                assert item.table is not None
                matches = [s for s in sources if s.alias.lower() == item.table.lower()]
                if not matches:
                    raise SQLError(f"no such table: {item.table}")
                src = matches[0]
                for i in range(len(src.table.columns)):
                    out_fns.append(self._index_fn(src.offset + i))
            else:
                assert item.expr is not None
                out_fns.append(compiler.compile(item.expr))
        ncols = len(out_fns)

        # 4. ORDER BY keys: either an output column index or an expression.
        order_specs: list[tuple[int | None, Fn | None, bool, bool | None]] = []
        output_alias_index: dict[str, int] = {}
        pos = 0
        for item in stmt.items:
            if item.kind == "expr":
                if item.alias is not None:
                    output_alias_index.setdefault(item.alias.lower(), pos)
                pos += 1
            elif item.kind == "star":
                pos += sum(len(s.table.columns) for s in sources)
            else:
                pos += self._star_width(sources, item.table)
        for n, term in enumerate(stmt.order_by, start=1):
            e = term.expr
            if isinstance(e, Literal) and isinstance(e.value, int):
                k = e.value
                if not 1 <= k <= ncols:
                    raise SQLError(
                        f"{_ordinal(n)} ORDER BY term out of range - should be between 1 "
                        f"and {ncols}"
                    )
                order_specs.append((k - 1, None, term.desc, term.nulls_first))
            elif (
                isinstance(e, ColumnRef)
                and e.table is None
                and e.name.lower() in output_alias_index
            ):
                order_specs.append(
                    (output_alias_index[e.name.lower()], None, term.desc, term.nulls_first)
                )
            else:
                order_specs.append((None, compiler.compile(e), term.desc, term.nulls_first))

        # 5. Produce (output row, sort key values) pairs.
        results: list[tuple[tuple, list[Value]]] = []
        key_fns = [(i, f) for i, f, _d, _n in order_specs]

        def emit(src_row: tuple) -> None:
            out = tuple(f(src_row) for f in out_fns)
            keys = [out[i] if f is None else f(src_row) for i, f in key_fns]  # type: ignore[index]
            results.append((out, keys))

        if is_agg:
            having = compiler.compile(stmt.having) if stmt.having is not None else None
            self._aggregate(stmt, sources, rows, ctx, width, emit, having)
        else:
            for r in rows:
                emit(r)

        # 6. DISTINCT
        if stmt.distinct:
            seen: set[tuple] = set()
            unique = []
            for out, keys in results:
                k = tuple(V.value_key(v) for v in out)
                if k not in seen:
                    seen.add(k)
                    unique.append((out, keys))
            results = unique

        # 7. ORDER BY
        if order_specs:
            dirs = [(desc, nulls_first) for _i, _f, desc, nulls_first in order_specs]

            def cmp(a: tuple[tuple, list[Value]], b: tuple[tuple, list[Value]]) -> int:
                for (x, y), (desc, nulls_first) in zip(zip(a[1], b[1], strict=True), dirs,
                                                        strict=True):
                    if nulls_first is not None and (x is None) != (y is None):
                        return -1 if (x is None) == nulls_first else 1
                    c = V.compare(x, y)
                    if c:
                        return -c if desc else c
                return 0

            results.sort(key=cmp_to_key(cmp))

        # 8. LIMIT / OFFSET
        out_rows = [out for out, _k in results]
        if stmt.limit is not None:
            limit = _const_int(stmt.limit, "LIMIT")
            offset = _const_int(stmt.offset, "OFFSET") if stmt.offset is not None else 0
            if offset < 0:
                offset = 0
            if limit < 0:
                out_rows = out_rows[offset:]
            else:
                out_rows = out_rows[offset : offset + limit]
        return out_rows

    @staticmethod
    def _star_width(sources: list[Source], table: str | None) -> int:
        for s in sources:
            if s.alias.lower() == str(table).lower():
                return len(s.table.columns)
        return 0

    @staticmethod
    def _index_fn(idx: int) -> Fn:
        return lambda row: row[idx]

    def _aggregate(
        self,
        stmt: Select,
        sources: list[Source],
        rows: list[tuple],
        ctx: Context,
        width: int,
        emit: Callable[[tuple], None],
        having: Fn | None,
    ) -> None:
        # GROUP BY keys
        group_fns: list[Fn] = []
        if stmt.group_by:
            gctx = Context(sources, ctx.aliases, clause="GROUP BY")
            gcompiler = Compiler(gctx)
            for n, e in enumerate(stmt.group_by, start=1):
                if isinstance(e, Literal) and isinstance(e.value, int):
                    k = e.value
                    exprs = [i for i in stmt.items]
                    if not 1 <= k <= len(exprs) or exprs[k - 1].kind != "expr":
                        raise SQLError(
                            f"{_ordinal(n)} GROUP BY term out of range - should be between 1 "
                            f"and {len(exprs)}"
                        )
                    target = exprs[k - 1].expr
                    assert target is not None
                    group_fns.append(gcompiler.compile(target))
                else:
                    group_fns.append(gcompiler.compile(e))

        # Aggregate argument evaluators (compiled in a plain, non-aggregate context).
        actx = Context(sources)
        acompiler = Compiler(actx)
        agg_specs: list[tuple[FuncCall, list[Fn]]] = []
        for node in ctx.aggs:
            agg_specs.append((node, [acompiler.compile(a) for a in node.args]))
        minmax_positions = [
            i for i, (node, _a) in enumerate(agg_specs) if node.name in ("min", "max")
        ]
        track_minmax = bool(minmax_positions)
        last_minmax = minmax_positions[-1] if minmax_positions else -1

        def new_accumulators() -> list[Aggregate]:
            accs: list[Aggregate] = []
            for node, _args in agg_specs:
                if node.star:
                    acc: Aggregate = CountStar()
                else:
                    acc = AGGREGATE_FUNCTIONS[node.name][0]()
                    if node.distinct:
                        acc = Distinct(acc)
                accs.append(acc)
            return accs

        groups: dict[tuple, list] = {}  # key -> [accs, rep_row, group values]
        if not stmt.group_by:
            groups[()] = [new_accumulators(), None, ()]
        for row in rows:
            gvals = tuple(f(row) for f in group_fns)
            key = tuple(V.value_key(v) for v in gvals)
            state = groups.get(key)
            first = state is None
            if state is None:
                state = [new_accumulators(), None, gvals]
                groups[key] = state
            accs = state[0]
            hit = False
            for i, ((_node, arg_fns), acc) in enumerate(zip(agg_specs, accs, strict=True)):
                r = acc.step(tuple(f(row) for f in arg_fns))
                if i == last_minmax:
                    hit = r
            if track_minmax:
                if hit:
                    state[1] = row
            elif first or state[1] is None:
                state[1] = row

        states = list(groups.values())
        if stmt.group_by:
            states.sort(key=lambda s: [V.sort_key(v) for v in s[2]])
        null_row = (None,) * width
        for accs, rep, _g in states:
            ext = (rep if rep is not None else null_row) + tuple(a.final() for a in accs)
            if having is not None and not V.truth(having(ext)):
                continue
            emit(ext)
