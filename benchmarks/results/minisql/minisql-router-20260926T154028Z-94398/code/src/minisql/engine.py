"""Query compilation and execution."""

from __future__ import annotations

import math
from collections.abc import Callable

from . import values as V
from .errors import SQLError
from .parser import (
    AGGREGATES,
    Between,
    Binary,
    Case,
    Column,
    CreateTable,
    Delete,
    DropTable,
    Func,
    InList,
    Insert,
    IsNull,
    Like,
    Literal,
    Select,
    Unary,
    Update,
    parse,
)

Row = list
Fn = Callable[[Row], object]


class Table:
    def __init__(self, name: str, columns: list[tuple[str, str]]):
        self.name = name
        self.columns = [c for c, _ in columns]
        self.affinities = [V.type_affinity(t) for _, t in columns]
        self.index = {c.lower(): i for i, c in enumerate(self.columns)}
        self.rows: list[list] = []


class Scope:
    """The set of tables visible to an expression, laid out as one flat row."""

    def __init__(self):
        self.entries: list[tuple[str, Table, int]] = []  # (alias_lower, table, offset)
        self.width = 0

    def add(self, alias: str, table: Table) -> None:
        key = alias.lower()
        if any(a == key for a, _, _ in self.entries):
            raise SQLError(f"ambiguous table alias: {alias}")
        self.entries.append((key, table, self.width))
        self.width += len(table.columns)

    def prefix(self, n: int) -> Scope:
        s = Scope()
        s.entries = self.entries[:n]
        s.width = sum(len(t.columns) for _, t, _ in s.entries)
        return s


def is_aggregate_call(node) -> bool:
    if not isinstance(node, Func) or node.name not in AGGREGATES:
        return False
    if node.name in ("MIN", "MAX"):
        return len(node.args) == 1
    return True


def contains_aggregate(node) -> bool:
    if node is None:
        return False
    if is_aggregate_call(node):
        return True
    if isinstance(node, (Literal, Column)):
        return False
    if isinstance(node, Unary):
        return contains_aggregate(node.operand)
    if isinstance(node, Binary):
        return contains_aggregate(node.left) or contains_aggregate(node.right)
    if isinstance(node, IsNull):
        return contains_aggregate(node.operand)
    if isinstance(node, InList):
        return contains_aggregate(node.operand) or any(map(contains_aggregate, node.items))
    if isinstance(node, Between):
        return any(map(contains_aggregate, (node.operand, node.low, node.high)))
    if isinstance(node, Like):
        return contains_aggregate(node.operand) or contains_aggregate(node.pattern)
    if isinstance(node, Func):
        return any(map(contains_aggregate, node.args))
    if isinstance(node, Case):
        parts = [node.operand, node.else_]
        for c, r in node.whens:
            parts += [c, r]
        return any(map(contains_aggregate, parts))
    return False


_CMP = {
    "=": lambda c: c == 0,
    "!=": lambda c: c != 0,
    "<": lambda c: c < 0,
    "<=": lambda c: c <= 0,
    ">": lambda c: c > 0,
    ">=": lambda c: c >= 0,
}

_ARITH = {"+": V.add, "-": V.sub, "*": V.mul, "/": V.div, "%": V.mod, "||": V.concat}


def _cmp_fn(op: str, fl: Fn, al, fr: Fn, ar) -> Fn:
    test = _CMP[op]
    cl, cr = V.comparison_prep(al, ar)

    def f(r):
        a = fl(r)
        if a is None:
            return None
        b = fr(r)
        if b is None:
            return None
        if cl is not None:
            a = cl(a)
        if cr is not None:
            b = cr(b)
        return 1 if test(V.compare(a, b)) else 0

    return f


def _equal_prepped(a, b, cl, cr) -> bool:
    if cl is not None:
        a = cl(a)
    if cr is not None:
        b = cr(b)
    return V.compare(a, b) == 0


class AggSpec:
    def __init__(self, node: Func, arg_fns: list[Fn]):
        self.node = node
        self.name = node.name
        self.distinct = node.distinct
        self.star = node.star
        self.arg_fns = arg_fns


class Compiler:
    """Compiles AST expressions into Python closures over a flat row."""

    def __init__(self, scope: Scope, aliases: dict | None = None):
        self.scope = scope
        self.aliases = aliases or {}
        self.resolving: set[str] = set()
        self.aggs: list[AggSpec] | None = None  # set to a list to allow aggregates
        self.agg_context = "here"
        self.agg_base = scope.width  # row position of the first aggregate value
        self.group_terms: dict = {}  # node_key -> row position of a GROUP BY value

    def compile(self, node) -> tuple[Fn, str | None]:
        method = getattr(self, "c_" + type(node).__name__)
        if self.group_terms and not isinstance(node, Literal):
            pos = self.group_terms.get(self.node_key(node))
            if pos is not None:
                return self._col(pos), method(node)[1]
        return method(node)

    def node_key(self, node):
        """Structural identity of an expression, with columns resolved to row positions."""
        if isinstance(node, Literal):
            return ("lit", type(node.value).__name__, node.value)
        if isinstance(node, Column):
            try:
                found = self.resolve_column(node)
            except SQLError:
                found = None
            if found is not None:
                return ("col", found[0])
            name = node.name.lower()
            if node.table is None and name in self.aliases and name not in self.resolving:
                self.resolving.add(name)
                try:
                    return self.node_key(self.aliases[name])
                finally:
                    self.resolving.discard(name)
            return ("badcol", node.table, name)
        parts = [type(node).__name__]
        for name in node.__dataclass_fields__:
            v = getattr(node, name)
            if isinstance(v, list):
                parts.append(tuple(
                    tuple(self.node_key(x) for x in item) if isinstance(item, tuple)
                    else self.node_key(item)
                    for item in v
                ))
            elif v is None or isinstance(v, (str, bool)):
                parts.append(v)
            else:
                parts.append(self.node_key(v))
        return tuple(parts)

    def fn(self, node) -> Fn:
        return self.compile(node)[0]

    # ------------------------------------------------------------- leaves
    def c_Literal(self, node: Literal):
        v = node.value
        return (lambda r: v), None

    def resolve_column(self, node: Column) -> tuple[int, str] | None:
        """(row position, affinity) of a table column, or None if no table has it."""
        name = node.name.lower()
        if node.table is not None:
            tkey = node.table.lower()
            for alias, table, off in self.scope.entries:
                if alias == tkey:
                    idx = table.index.get(name)
                    if idx is None:
                        break
                    return off + idx, table.affinities[idx]
            raise SQLError(f"no such column: {node.table}.{node.name}")
        found = []
        for _alias, table, off in self.scope.entries:
            idx = table.index.get(name)
            if idx is not None:
                found.append((off + idx, table.affinities[idx]))
        if len(found) > 1:
            raise SQLError(f"ambiguous column name: {node.name}")
        return found[0] if found else None

    def c_Column(self, node: Column):
        found = self.resolve_column(node)
        if found is not None:
            return self._col(found[0]), found[1]
        name = node.name.lower()
        if name in self.aliases and name not in self.resolving:
            self.resolving.add(name)
            try:
                return self.compile(self.aliases[name])
            finally:
                self.resolving.discard(name)
        raise SQLError(f"no such column: {node.name}")

    @staticmethod
    def _col(pos: int) -> Fn:
        return lambda r: r[pos]

    # ----------------------------------------------------------- operators
    def c_Unary(self, node: Unary):
        f, aff = self.compile(node.operand)
        if node.op == "-":
            return (lambda r: V.negate(f(r))), None
        if node.op == "+":
            return f, aff

        def not_(r):
            t = V.truthy(f(r))
            return None if t is None else (0 if t else 1)

        return not_, None

    def c_Binary(self, node: Binary):
        op = node.op
        fl, al = self.compile(node.left)
        fr, ar = self.compile(node.right)
        if op in _ARITH:
            g = _ARITH[op]
            return (lambda r: g(fl(r), fr(r))), None
        if op in _CMP:
            return _cmp_fn(op, fl, al, fr, ar), None
        if op == "AND":

            def and_(r):
                a = V.truthy(fl(r))
                if a is False:
                    return 0
                b = V.truthy(fr(r))
                if b is False:
                    return 0
                if a is None or b is None:
                    return None
                return 1

            return and_, None
        if op == "OR":

            def or_(r):
                a = V.truthy(fl(r))
                if a is True:
                    return 1
                b = V.truthy(fr(r))
                if b is True:
                    return 1
                if a is None or b is None:
                    return None
                return 0

            return or_, None
        if op in ("IS", "ISNOT"):
            cl, cr = V.comparison_prep(al, ar)
            want = 1 if op == "IS" else 0

            def is_(r):
                a, b = fl(r), fr(r)
                if a is None or b is None:
                    same = a is None and b is None
                else:
                    same = _equal_prepped(a, b, cl, cr)
                return want if same else 1 - want

            return is_, None
        raise SQLError(f"unsupported operator {op}")

    def c_IsNull(self, node: IsNull):
        f = self.fn(node.operand)
        if node.negated:
            return (lambda r: 0 if f(r) is None else 1), None
        return (lambda r: 1 if f(r) is None else 0), None

    def c_InList(self, node: InList):
        f, aff = self.compile(node.operand)
        # SQLite compares every list element using the left operand's affinity.
        if aff in V.NUMERIC_AFFINITIES:
            conv = V.apply_numeric_for_compare
        elif aff == V.TEXT:
            conv = V.to_text
        else:
            conv = None
        items = [(self.fn(item), conv, conv) for item in node.items]
        neg = node.negated

        def in_(r):
            a = f(r)
            if a is None:
                return None if items else (1 if neg else 0)
            saw_null = False
            for fi, cl, cr in items:
                b = fi(r)
                if b is None:
                    saw_null = True
                elif _equal_prepped(a, b, cl, cr):
                    return 0 if neg else 1
            if saw_null:
                return None
            return 1 if neg else 0

        return in_, None

    def c_Between(self, node: Between):
        f, a = self.compile(node.operand)
        fl, al = self.compile(node.low)
        fh, ah = self.compile(node.high)
        ge = _cmp_fn(">=", f, a, fl, al)
        le = _cmp_fn("<=", f, a, fh, ah)
        neg = node.negated

        def between(r):
            x = ge(r)
            if x == 0:
                res = 0
            else:
                y = le(r)
                if y == 0:
                    res = 0
                elif x is None or y is None:
                    return None
                else:
                    res = 1
            return 1 - res if neg else res

        return between, None

    def c_Like(self, node: Like):
        f = self.fn(node.operand)
        p = self.fn(node.pattern)
        if node.negated:

            def not_like(r):
                v = V.like(f(r), p(r))
                return None if v is None else 1 - v

            return not_like, None
        return (lambda r: V.like(f(r), p(r))), None

    def c_Case(self, node: Case):
        whens = [(self.compile(c), self.fn(v)) for c, v in node.whens]
        else_fn = self.fn(node.else_) if node.else_ is not None else (lambda r: None)
        if node.operand is not None:
            fo, ao = self.compile(node.operand)
            prepped = []
            for (fc, ac), fv in whens:
                cl, cr = V.comparison_prep(ao, ac)
                prepped.append((fc, cl, cr, fv))

            def simple_case(r):
                x = fo(r)
                if x is not None:
                    for fc, cl, cr, fv in prepped:
                        y = fc(r)
                        if y is not None and _equal_prepped(x, y, cl, cr):
                            return fv(r)
                return else_fn(r)

            return simple_case, None

        conds = [(fc, fv) for (fc, _), fv in whens]

        def searched_case(r):
            for fc, fv in conds:
                if V.truthy(fc(r)) is True:
                    return fv(r)
            return else_fn(r)

        return searched_case, None

    # ------------------------------------------------------------ functions
    def c_Func(self, node: Func):
        if is_aggregate_call(node):
            return self._aggregate(node)
        if node.distinct or node.star:
            raise SQLError(f"DISTINCT/star not allowed in {node.name}()")
        builder = SCALAR_FUNCTIONS.get(node.name)
        if builder is None:
            raise SQLError(f"no such function: {node.name}")
        nmin, nmax, impl = builder
        if not (nmin <= len(node.args) <= nmax):
            raise SQLError(f"wrong number of arguments to function {node.name}()")
        arg_fns = [self.fn(a) for a in node.args]
        return (lambda r: impl(*[g(r) for g in arg_fns])), None

    def _aggregate(self, node: Func):
        if self.aggs is None:
            raise SQLError(f"misuse of aggregate function {node.name}() {self.agg_context}")
        name = node.name
        nargs = len(node.args)
        if node.star:
            ok = True
        elif name == "GROUP_CONCAT":
            ok = nargs in (1, 2)
        else:
            ok = nargs == 1
        if not ok:
            raise SQLError(f"wrong number of arguments to function {name}()")
        inner = Compiler(self.scope, self.aliases)
        inner.resolving = self.resolving
        inner.agg_context = "(nested aggregate)"
        arg_fns = [inner.fn(a) for a in node.args]
        idx = len(self.aggs)
        self.aggs.append(AggSpec(node, arg_fns))
        pos = self.agg_base + idx
        return (lambda r: r[pos]), None


# ---------------------------------------------------------------- scalar functions


def _abs(x):
    x = V.to_number(x)
    if x is None:
        return None
    if isinstance(x, int):
        return V.negate(x) if x < 0 else x
    return abs(x)


def _length(x):
    if x is None:
        return None
    return len(V.to_text(x))


def _upper(x):
    return None if x is None else V.to_text(x).upper()


def _lower(x):
    return None if x is None else V.to_text(x).lower()


def _coalesce(*args):
    for a in args:
        if a is not None:
            return a
    return None


def _nullif(a, b):
    if a is not None and b is not None and V.compare(a, b) == 0:
        return None
    return a


def _typeof(x):
    if x is None:
        return "null"
    if isinstance(x, int):
        return "integer"
    if isinstance(x, float):
        return "real"
    return "text"


def _minmax(pick):
    def f(*args):
        if any(a is None for a in args):
            return None
        best = args[0]
        for a in args[1:]:
            if pick(V.compare(a, best)):
                best = a
        return best

    return f


SCALAR_FUNCTIONS = {
    "ABS": (1, 1, _abs),
    "LENGTH": (1, 1, _length),
    "UPPER": (1, 1, _upper),
    "LOWER": (1, 1, _lower),
    "COALESCE": (2, 1000, _coalesce),
    "IFNULL": (2, 2, _coalesce),
    "NULLIF": (2, 2, _nullif),
    "TYPEOF": (1, 1, _typeof),
    "MIN": (2, 1000, _minmax(lambda c: c < 0)),
    "MAX": (2, 1000, _minmax(lambda c: c > 0)),
}


# ------------------------------------------------------------------ aggregates

_BIG = 4503599627370496  # 2**52


def _c_mod(a: int, b: int) -> int:
    r = abs(a) % b
    return -r if a < 0 else r


class _KBNSum:
    """Kahan-Babuska-Neumaier summation, mirroring SQLite's sum()/avg()."""

    def __init__(self):
        self.i_sum = 0
        self.r_sum = 0.0
        self.r_err = 0.0
        self.approx = False
        self.cnt = 0

    def _step(self, r: float) -> None:
        s = self.r_sum
        t = s + r
        if abs(s) > abs(r):
            self.r_err += (s - t) + r
        else:
            self.r_err += (r - t) + s
        self.r_sum = t

    def _step_int(self, v: int) -> None:
        if v <= -_BIG or v >= _BIG:
            sm = _c_mod(v, 16384)
            self._step(float(v - sm))
            self._step(float(sm))
        else:
            self._step(float(v))

    def _init(self, v: int) -> None:
        if v <= -_BIG or v >= _BIG:
            sm = _c_mod(v, 16384)
            self.r_sum = float(v - sm)
            self.r_err = float(sm)
        else:
            self.r_sum = float(v)
            self.r_err = 0.0

    def add(self, v) -> None:
        if v is None:
            return
        if isinstance(v, str):
            n = V.text_to_number_strict(v)
            v = n if isinstance(n, int) else float(V.text_to_number(v))
        self.cnt += 1
        if not self.approx:
            if isinstance(v, int):
                x = self.i_sum + v
                if V.INT_MIN <= x <= V.INT_MAX:
                    self.i_sum = x
                    return
                self._init(self.i_sum)
                self.approx = True
                self._step_int(v)
            else:
                self._init(self.i_sum)
                self.approx = True
                self._step(v)
        elif isinstance(v, int):
            self._step_int(v)
        else:
            self._step(v)

    def real(self) -> float:
        if not self.approx:
            return float(self.i_sum)
        r = self.r_sum
        if not math.isinf(self.r_err):
            r += self.r_err
        return r


def compute_aggregate(spec: AggSpec, rows: list[Row]):
    name = spec.name
    if spec.star:
        return len(rows)
    f = spec.arg_fns[0]
    vals = [v for v in (f(r) for r in rows) if v is not None]
    if spec.distinct:
        seen = set()
        uniq = []
        for v in vals:
            if v not in seen:
                seen.add(v)
                uniq.append(v)
        vals = uniq
    if name == "COUNT":
        return len(vals)
    if name in ("SUM", "AVG", "TOTAL"):
        acc = _KBNSum()
        for v in vals:
            acc.add(v)
        if name == "TOTAL":
            return acc.real()
        if acc.cnt == 0:
            return None
        if name == "AVG":
            return acc.real() / acc.cnt
        return acc.real() if acc.approx else acc.i_sum
    if name in ("MIN", "MAX"):
        if not vals:
            return None
        best = vals[0]
        for v in vals[1:]:
            c = V.compare(v, best)
            if (c < 0) if name == "MIN" else (c > 0):
                best = v
        return best
    if name == "GROUP_CONCAT":
        sep_fn = spec.arg_fns[1] if len(spec.arg_fns) > 1 else None
        out = None
        for r in rows:
            v = f(r)
            if v is None:
                continue
            if out is None:
                out = V.to_text(v)
            else:
                sep = "," if sep_fn is None else sep_fn(r)
                out += ("" if sep is None else V.to_text(sep)) + V.to_text(v)
        return out
    raise SQLError(f"unknown aggregate {name}")


def _minmax_row(spec: AggSpec, rows: list[Row]):
    """Row that supplies the MIN/MAX value (for bare columns in the result)."""
    f = spec.arg_fns[0]
    best = best_row = None
    for r in rows:
        v = f(r)
        if v is None:
            continue
        if best is None:
            best, best_row = v, r
            continue
        c = V.compare(v, best)
        if (c < 0) if spec.name == "MIN" else (c > 0):
            best, best_row = v, r
    return best_row


def _integer_term(e) -> int | None:
    """Integer value of an ORDER BY/GROUP BY term that SQLite treats as a column number."""
    if isinstance(e, Literal):
        return e.value if isinstance(e.value, int) else None
    if isinstance(e, Unary) and e.op in ("-", "+"):
        n = _integer_term(e.operand)
        return None if n is None else (-n if e.op == "-" else n)
    if isinstance(e, Binary) and e.op == "AND":
        # SQLite folds "x AND 0" to the literal 0 while parsing.
        if _integer_term(e.left) == 0 or _integer_term(e.right) == 0:
            return 0
    return None


# --------------------------------------------------------------------- database


class Database:
    """An in-memory SQL database."""

    def __init__(self):
        self.tables: dict[str, Table] = {}

    def execute(self, sql: str) -> list[tuple]:
        if not isinstance(sql, str):
            raise SQLError("SQL must be a string")
        try:
            stmt = parse(sql)
        except RecursionError as e:
            raise SQLError("expression too deeply nested") from e
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

    def _table(self, name: str) -> Table:
        t = self.tables.get(name.lower())
        if t is None:
            raise SQLError(f"no such table: {name}")
        return t

    # ----------------------------------------------------------------- DDL
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

    # ----------------------------------------------------------------- DML
    def _insert(self, stmt: Insert) -> None:
        table = self._table(stmt.table)
        ncols = len(table.columns)
        if stmt.columns is None:
            targets = list(range(ncols))
        else:
            targets = []
            for c in stmt.columns:
                idx = table.index.get(c.lower())
                if idx is None:
                    raise SQLError(f"table {table.name} has no column named {c}")
                if idx in targets:
                    raise SQLError(f"duplicate column name: {c}")
                targets.append(idx)
        comp = Compiler(Scope())
        compiled = []
        for row in stmt.rows:
            if len(row) != len(targets):
                if stmt.columns is not None:
                    raise SQLError(f"{len(row)} values for {len(targets)} columns")
                raise SQLError(
                    f"table {table.name} has {ncols} columns but {len(row)} values were supplied"
                )
            compiled.append([comp.fn(e) for e in row])
        new_rows = []
        for fns in compiled:
            vals = [None] * ncols
            for idx, f in zip(targets, fns, strict=True):
                vals[idx] = V.apply_affinity(f([]), table.affinities[idx])
            new_rows.append(vals)
        table.rows.extend(new_rows)

    def _single_scope(self, table: Table) -> Scope:
        scope = Scope()
        scope.add(table.name, table)
        return scope

    def _update(self, stmt: Update) -> None:
        table = self._table(stmt.table)
        comp = Compiler(self._single_scope(table))
        comp.agg_context = "in UPDATE"
        sets = []
        for col, expr in stmt.assignments:
            idx = table.index.get(col.lower())
            if idx is None:
                raise SQLError(f"no such column: {col}")
            sets.append((idx, comp.fn(expr)))
        where = comp.fn(stmt.where) if stmt.where is not None else None
        updates = []
        for row in table.rows:
            if where is None or V.truthy(where(row)) is True:
                updates.append((row, [(idx, f(row)) for idx, f in sets]))
        for row, changes in updates:
            for idx, v in changes:
                row[idx] = V.apply_affinity(v, table.affinities[idx])

    def _delete(self, stmt: Delete) -> None:
        table = self._table(stmt.table)
        if stmt.where is None:
            table.rows = []
            return
        comp = Compiler(self._single_scope(table))
        comp.agg_context = "in DELETE"
        where = comp.fn(stmt.where)
        table.rows = [r for r in table.rows if V.truthy(where(r)) is not True]

    # --------------------------------------------------------------- SELECT
    def _select(self, sel: Select) -> list[tuple]:
        scope = Scope()
        tables = []
        for item in sel.from_items:
            t = self._table(item.table)
            scope.add(item.alias, t)
            tables.append(t)

        # Expand the select list.
        out_exprs: list = []
        aliases: dict[str, object] = {}
        for item in sel.items:
            if item.expr is None:
                if item.star_table is None:
                    if not scope.entries:
                        raise SQLError("no tables specified")
                    entries = scope.entries
                else:
                    key = item.star_table.lower()
                    entries = [e for e in scope.entries if e[0] == key]
                    if not entries:
                        raise SQLError(f"no such table: {item.star_table}")
                for alias, t, _ in entries:
                    for c in t.columns:
                        out_exprs.append(Column(alias, c))
            else:
                out_exprs.append(item.expr)
                if item.alias is not None:
                    aliases.setdefault(item.alias.lower(), item.expr)

        is_agg = bool(sel.group_by) or sel.having is not None or any(
            contains_aggregate(e) for e in out_exprs
        ) or any(contains_aggregate(e) for e, _ in sel.order_by)

        # Joins.
        join_fns = []
        for k, item in enumerate(sel.from_items):
            if item.on is None:
                join_fns.append(None)
                continue
            c = Compiler(scope.prefix(k + 1))
            c.agg_context = "in ON clause"
            join_fns.append(c.fn(item.on))

        base = Compiler(scope, aliases)
        base.agg_context = "in WHERE clause"
        where_fn = base.fn(sel.where) if sel.where is not None else None

        group_fns = []
        for e in sel.group_by:
            n = _integer_term(e)
            if n is not None:
                e = self._positional(n, out_exprs, "GROUP BY")
            c = Compiler(scope, aliases)
            c.agg_context = "in GROUP BY clause"
            group_fns.append(c.fn(e))

        main = Compiler(scope, aliases)
        if is_agg:
            main.aggs = []
            main.agg_base = scope.width + len(group_fns)
            for i, e in enumerate(sel.group_by):
                n = _integer_term(e)
                if n is not None:
                    e = out_exprs[n - 1]
                main.group_terms.setdefault(main.node_key(e), scope.width + i)
        select_fns = [main.fn(e) for e in out_exprs]
        having_fn = main.fn(sel.having) if sel.having is not None else None

        order_fns = []
        for e, desc in sel.order_by:
            if isinstance(e, Column) and e.table is None and e.name.lower() in aliases:
                e = aliases[e.name.lower()]
            elif (n := _integer_term(e)) is not None:
                e = self._positional(n, out_exprs, "ORDER BY")
            order_fns.append((main.fn(e), desc))

        limit = self._const_int(sel.limit, "LIMIT")
        offset = self._const_int(sel.offset, "OFFSET")

        # Produce source rows.
        rows: list[Row] = [[]]
        for k, t in enumerate(tables):
            on = join_fns[k]
            left = sel.from_items[k].join == "LEFT"
            pad = [None] * len(t.columns)
            new_rows = []
            for r in rows:
                matched = False
                for tr in t.rows:
                    combined = r + tr
                    if on is None or V.truthy(on(combined)) is True:
                        new_rows.append(combined)
                        matched = True
                if left and not matched:
                    new_rows.append(r + pad)
            rows = new_rows
        if where_fn is not None:
            rows = [r for r in rows if V.truthy(where_fn(r)) is True]

        if is_agg:
            rows = self._aggregate(rows, scope.width, group_fns, main.aggs, bool(sel.group_by))
            if having_fn is not None:
                rows = [r for r in rows if V.truthy(having_fn(r)) is True]

        results = []
        for r in rows:
            out = tuple(f(r) for f in select_fns)
            keys = [f(r) for f, _ in order_fns]
            results.append((out, keys))

        if sel.distinct:
            seen = set()
            uniq = []
            for out, keys in results:
                if out not in seen:
                    seen.add(out)
                    uniq.append((out, keys))
            results = uniq

        for i in range(len(order_fns) - 1, -1, -1):
            desc = order_fns[i][1]
            results.sort(key=lambda x, i=i: V.sort_key(x[1][i]), reverse=desc)

        out_rows = [out for out, _ in results]
        if offset is not None and offset > 0:
            out_rows = out_rows[offset:]
        if limit is not None and limit >= 0:
            out_rows = out_rows[:limit]
        return out_rows

    @staticmethod
    def _positional(n: int, out_exprs: list, clause: str):
        if not 1 <= n <= len(out_exprs):
            raise SQLError(f"{clause} term out of range - should be between 1 and {len(out_exprs)}")
        return out_exprs[n - 1]

    @staticmethod
    def _const_int(expr, clause: str):
        if expr is None:
            return None
        c = Compiler(Scope())
        c.agg_context = f"in {clause}"
        v = c.fn(expr)([])
        if isinstance(v, str):
            n = V.text_to_number_strict(v)
            if n is None:
                raise SQLError("datatype mismatch")
            v = n
        if v is None:
            raise SQLError("datatype mismatch")
        if isinstance(v, float):
            if not v.is_integer():
                raise SQLError("datatype mismatch")
            v = int(v)
        return v

    @staticmethod
    def _aggregate(rows, width, group_fns, aggs: list[AggSpec], grouped: bool):
        if grouped:
            groups: dict[tuple, list] = {}
            for r in rows:
                key = tuple(f(r) for f in group_fns)
                groups.setdefault(key, []).append(r)
            group_list = list(groups.values())
        else:
            group_list = [rows]
        minmax = [a for a in aggs if a.name in ("MIN", "MAX")]
        out = []
        for g in group_list:
            rep = None
            if len(minmax) == 1:
                rep = _minmax_row(minmax[0], g)
            if rep is None:
                rep = g[0] if g else [None] * width
            keys = [f(g[0]) for f in group_fns] if grouped else []
            out.append(list(rep) + keys + [compute_aggregate(a, g) for a in aggs])
        return out
