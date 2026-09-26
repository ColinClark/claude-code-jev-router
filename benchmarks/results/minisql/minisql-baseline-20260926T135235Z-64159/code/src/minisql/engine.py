"""Query execution: name resolution, expression compilation and statement evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from minisql import ast
from minisql import values as V
from minisql.errors import SQLError
from minisql.parser import parse

AGGREGATES = frozenset({"COUNT", "SUM", "AVG", "MIN", "MAX", "TOTAL", "GROUP_CONCAT"})


class Table:
    def __init__(self, name: str, columns: list[tuple[str, str]]):
        self.name = name
        self.columns = [c for c, _ in columns]
        self.affinities = [V.type_affinity(t) for _, t in columns]
        self.index: dict[str, int] = {}
        for i, c in enumerate(self.columns):
            key = c.lower()
            if key in self.index:
                raise SQLError(f"duplicate column name: {c}")
            self.index[key] = i
        self.rows: list[tuple] = []

    def column_index(self, name: str) -> int:
        try:
            return self.index[name.lower()]
        except KeyError:
            raise SQLError(f"table {self.name} has no column named {name}") from None


@dataclass
class _ScopeEntry:
    name: str  # lower-cased table name or alias
    table: Table
    offset: int


class Scope:
    """The tables visible to an expression; rows are flat tuples of all their columns."""

    def __init__(self):
        self.entries: list[_ScopeEntry] = []
        self.width = 0

    def add(self, name: str, table: Table):
        self.entries.append(_ScopeEntry(name.lower(), table, self.width))
        self.width += len(table.columns)

    def find(self, name: str) -> _ScopeEntry:
        for entry in self.entries:
            if entry.name == name.lower():
                return entry
        raise SQLError(f"no such table: {name}")

    def resolve(self, table: str | None, column: str):
        """Return (row index, affinity) for a column, None if unknown; raise if ambiguous."""
        key = column.lower()
        matches = []
        table_seen = False
        for entry in self.entries:
            if table is not None and entry.name != table.lower():
                continue
            table_seen = True
            idx = entry.table.index.get(key)
            if idx is not None:
                matches.append((entry.offset + idx, entry.table.affinities[idx]))
        if len(matches) > 1:
            name = f"{table}.{column}" if table else column
            raise SQLError(f"ambiguous column name: {name}")
        if matches:
            return matches[0]
        if table is not None and not table_seen:
            raise SQLError(f"no such column: {table}.{column}")
        return None


@dataclass
class _Slot(ast.Expr):
    """A direct reference to a row position (produced by '*' expansion)."""

    index: int
    affinity: str | None


@dataclass
class AggSpec:
    name: str
    args: list  # compiled argument functions
    distinct: bool
    star: bool


# ---------------------------------------------------------------------------
# Expression compilation
# ---------------------------------------------------------------------------


def _comparison_converters(aff_a, aff_b):
    """Affinity conversions SQLite applies to the operands of a comparison."""
    conv_a = conv_b = None
    a_num = aff_a in V.NUMERIC_AFFINITIES
    b_num = aff_b in V.NUMERIC_AFFINITIES
    if a_num and not b_num:
        conv_b = V.NUMERIC
    elif b_num and not a_num:
        conv_a = V.NUMERIC
    elif aff_a == V.TEXT and aff_b is None:
        conv_b = V.TEXT
    elif aff_b == V.TEXT and aff_a is None:
        conv_a = V.TEXT
    return conv_a, conv_b


_CMP_TESTS = {
    "=": lambda c: c == 0,
    "!=": lambda c: c != 0,
    "<": lambda c: c < 0,
    "<=": lambda c: c <= 0,
    ">": lambda c: c > 0,
    ">=": lambda c: c >= 0,
}


def _make_compare(op, fa, aff_a, fb, aff_b, convs=None):
    """Build fn(row, aggs) -> 1/0/None comparing two compiled operands."""
    conv_a, conv_b = convs or _comparison_converters(aff_a, aff_b)
    test = _CMP_TESTS[op]

    def f(row, aggs):
        x = fa(row, aggs)
        if x is None:
            return None
        y = fb(row, aggs)
        if y is None:
            return None
        if conv_a:
            x = V.apply_affinity(x, conv_a)
        if conv_b:
            y = V.apply_affinity(y, conv_b)
        return 1 if test(V.compare(x, y)) else 0

    return f


def _and(fa, fb):
    def f(row, aggs):
        x = V.truth(fa(row, aggs))
        if x is False:
            return 0
        y = V.truth(fb(row, aggs))
        if y is False:
            return 0
        if x is None or y is None:
            return None
        return 1

    return f


def _or(fa, fb):
    def f(row, aggs):
        x = V.truth(fa(row, aggs))
        if x is True:
            return 1
        y = V.truth(fb(row, aggs))
        if y is True:
            return 1
        if x is None or y is None:
            return None
        return 0

    return f


def _not(fa):
    def f(row, aggs):
        x = V.truth(fa(row, aggs))
        if x is None:
            return None
        return 0 if x else 1

    return f


class Compiler:
    """Compiles AST expressions into closures fn(row, aggs) -> value.

    `aggs` is the list to register aggregate calls in, or None where aggregates are not
    allowed. `aliases` maps lower-cased output column aliases to their expressions; they are
    used when a bare identifier does not name a column.
    """

    def __init__(self, scope: Scope, aggs: list[AggSpec] | None = None, aliases=None):
        self.scope = scope
        self.aggs = aggs
        self.aliases = aliases or {}

    def fn(self, expr: ast.Expr):
        return self.compile(expr)[0]

    def compile(self, e: ast.Expr):
        """Return (fn, affinity)."""
        method = getattr(self, "_c_" + type(e).__name__)
        return method(e)

    def _c_Literal(self, e: ast.Literal):
        value = e.value
        if isinstance(value, int) and not V.INT_MIN <= value <= V.INT_MAX:
            value = float(value)
        return (lambda row, aggs: value), None

    def _c__Slot(self, e: _Slot):
        idx = e.index
        return (lambda row, aggs: row[idx]), e.affinity

    def _c_Column(self, e: ast.Column):
        found = self.scope.resolve(e.table, e.name)
        if found is None:
            if e.table is None:
                alias_expr = self.aliases.get(e.name.lower())
                if alias_expr is not None:
                    return Compiler(self.scope, self.aggs).compile(alias_expr)
                if e.quoted:
                    return self._c_Literal(ast.Literal(e.name))
            name = f"{e.table}.{e.name}" if e.table else e.name
            raise SQLError(f"no such column: {name}")
        idx, affinity = found
        return (lambda row, aggs: row[idx]), affinity

    def _c_Unary(self, e: ast.Unary):
        fa, aff = self.compile(e.operand)
        if e.op == "NOT":
            return _not(fa), None
        if e.op == "+":
            return fa, aff
        return (lambda row, aggs: V.negate(fa(row, aggs))), None

    def _c_Binary(self, e: ast.Binary):
        op = e.op
        fa, aff_a = self.compile(e.left)
        fb, aff_b = self.compile(e.right)
        if op == "AND":
            return _and(fa, fb), None
        if op == "OR":
            return _or(fa, fb), None
        if op in _CMP_TESTS:
            return _make_compare(op, fa, aff_a, fb, aff_b), None
        if op in ("IS", "IS NOT"):
            conv_a, conv_b = _comparison_converters(aff_a, aff_b)
            want = 1 if op == "IS" else 0

            def is_(row, aggs):
                x = fa(row, aggs)
                y = fb(row, aggs)
                if x is None or y is None:
                    same = x is None and y is None
                else:
                    if conv_a:
                        x = V.apply_affinity(x, conv_a)
                    if conv_b:
                        y = V.apply_affinity(y, conv_b)
                    same = V.compare(x, y) == 0
                return want if same else 1 - want

            return is_, None
        if op == "||":
            return (lambda row, aggs: V.concat(fa(row, aggs), fb(row, aggs))), None
        return (lambda row, aggs: V.arithmetic(op, fa(row, aggs), fb(row, aggs))), None

    def _c_InList(self, e: ast.InList):
        fx, aff_x = self.compile(e.expr)
        # Unlike '=', IN compares using the left operand's affinity alone, for both sides.
        conv = V.NUMERIC if aff_x in V.NUMERIC_AFFINITIES else aff_x
        tests = [_make_compare("=", fx, None, self.fn(i), None, (conv, conv)) for i in e.items]
        negated = e.negated

        def f(row, aggs):
            if not tests:
                return 1 if negated else 0
            if fx(row, aggs) is None:
                return None
            saw_null = False
            for test in tests:
                r = test(row, aggs)
                if r == 1:
                    return 0 if negated else 1
                if r is None:
                    saw_null = True
            if saw_null:
                return None
            return 1 if negated else 0

        return f, None

    def _c_Between(self, e: ast.Between):
        fx, aff_x = self.compile(e.expr)
        flo, aff_lo = self.compile(e.low)
        fhi, aff_hi = self.compile(e.high)
        f = _and(
            _make_compare(">=", fx, aff_x, flo, aff_lo),
            _make_compare("<=", fx, aff_x, fhi, aff_hi),
        )
        return (_not(f) if e.negated else f), None

    def _c_Like(self, e: ast.Like):
        fx = self.fn(e.expr)
        fp = self.fn(e.pattern)
        negated = e.negated

        def f(row, aggs):
            r = V.like(fx(row, aggs), fp(row, aggs))
            if r is None or not negated:
                return r
            return 1 - r

        return f, None

    def _c_Case(self, e: ast.Case):
        else_fn = self.fn(e.else_) if e.else_ is not None else (lambda row, aggs: None)
        if e.base is not None:
            fb, aff_b = self.compile(e.base)
            conds = []
            for when, then in e.whens:
                fw, aff_w = self.compile(when)
                conds.append((_make_compare("=", fb, aff_b, fw, aff_w), self.fn(then)))
        else:
            conds = [(self.fn(when), self.fn(then)) for when, then in e.whens]

        def f(row, aggs):
            for cond, then in conds:
                if V.truth(cond(row, aggs)):
                    return then(row, aggs)
            return else_fn(row, aggs)

        return f, None

    def _c_Cast(self, e: ast.Cast):
        fx = self.fn(e.expr)
        type_name = e.type_name
        return (lambda row, aggs: V.cast(fx(row, aggs), type_name)), V.type_affinity(type_name)

    def _c_Func(self, e: ast.Func):
        name = e.name
        is_agg = name in AGGREGATES and not (name in ("MIN", "MAX") and len(e.args) > 1)
        if is_agg:
            return self._aggregate(e), None
        if e.star or e.distinct:
            raise SQLError(f"wrong use of {name}()")
        impl = SCALAR_FUNCTIONS.get(name)
        if impl is None:
            raise SQLError(f"no such function: {name}")
        nargs, func = impl
        if nargs is not None and len(e.args) not in nargs:
            raise SQLError(f"wrong number of arguments to function {name}()")
        arg_fns = [self.fn(a) for a in e.args]
        return (lambda row, aggs: func(*[a(row, aggs) for a in arg_fns])), None

    def _aggregate(self, e: ast.Func):
        name = e.name
        if self.aggs is None:
            raise SQLError(f"misuse of aggregate function {name}()")
        if e.star:
            if name != "COUNT":
                raise SQLError(f"wrong number of arguments to function {name}()")
        else:
            expected = (1, 2) if name == "GROUP_CONCAT" else (1,)
            if len(e.args) not in expected or (e.distinct and len(e.args) != 1):
                raise SQLError(f"wrong number of arguments to function {name}()")
        inner = Compiler(self.scope, None, self.aliases)
        args = [inner.fn(a) for a in e.args]
        self.aggs.append(AggSpec(name, args, e.distinct, e.star))
        k = len(self.aggs) - 1
        return lambda row, aggs: aggs[k]


# ---------------------------------------------------------------------------
# Scalar functions (beyond the required set; handy and cheap)
# ---------------------------------------------------------------------------


def _abs(x):
    if x is None:
        return None
    x = V.to_number(x)
    if isinstance(x, int):
        if x == V.INT_MIN:
            raise SQLError("integer overflow")
        return abs(x)
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


def _round(x, n=0):
    if x is None or n is None:
        return None
    x = float(V.to_number(x))
    n = max(0, min(30, V.to_int(n)))
    if math.isinf(x) or math.isnan(x):
        return x
    if n == 0 and abs(x) < 4503599627370496.0:
        return float(-int(-x + 0.5)) if x < 0 else float(int(x + 0.5))
    return float(f"{x:.{n}f}")


def _substr(s, start, length=None):
    if s is None or start is None:
        return None
    s = V.to_text(s)
    start = V.to_int(start)
    if length is not None:
        length = V.to_int(length)
    n = len(s)
    if start > 0:
        begin = start - 1
    elif start < 0:
        begin = n + start
    else:
        begin = -1  # position 0 is just before the first character
    if length is None:
        end = n
    elif length >= 0:
        end = begin + length
    else:
        end = begin
        begin = begin + length
    begin = max(begin, 0)
    end = min(end, n)
    return s[begin:end] if end > begin else ""


def _min_scalar(*args):
    if any(a is None for a in args):
        return None
    best = args[0]
    for a in args[1:]:
        if V.compare(a, best) < 0:
            best = a
    return best


def _max_scalar(*args):
    if any(a is None for a in args):
        return None
    best = args[0]
    for a in args[1:]:
        if V.compare(a, best) > 0:
            best = a
    return best


SCALAR_FUNCTIONS = {
    "ABS": ((1,), _abs),
    "LENGTH": ((1,), _length),
    "UPPER": ((1,), _upper),
    "LOWER": ((1,), _lower),
    "COALESCE": (range(2, 1000), _coalesce),
    "IFNULL": ((2,), _coalesce),
    "NULLIF": ((2,), _nullif),
    "TYPEOF": ((1,), _typeof),
    "ROUND": ((1, 2), _round),
    "SUBSTR": ((2, 3), _substr),
    "MIN": (range(2, 1000), _min_scalar),
    "MAX": (range(2, 1000), _max_scalar),
}


# ---------------------------------------------------------------------------
# Aggregate evaluation
# ---------------------------------------------------------------------------


class _Sum:
    """SUM/AVG/TOTAL accumulator mirroring SQLite's integer/Kahan-Babuska-Neumaier logic."""

    def __init__(self):
        self.count = 0
        self.isum = 0
        self.rsum = 0.0
        self.rerr = 0.0
        self.approx = False
        self.overflow = False

    def _kbn(self, r: float):
        s = self.rsum
        t = s + r
        if abs(s) > abs(r):
            self.rerr += (s - t) + r
        else:
            self.rerr += (r - t) + s
        self.rsum = t

    def _kbn_int(self, i: int):
        if -(2**52) <= i <= 2**52:
            self._kbn(float(i))
        else:
            big = i - i % 16384 if i >= 0 else -((-i) - (-i) % 16384)
            self._kbn(float(big))
            self._kbn(float(i - big))

    def _start_approx(self):
        self.approx = True
        i = self.isum
        if abs(i) >= 2**52:
            small = abs(i) % 16384 * (1 if i >= 0 else -1)
            self.rsum = float(i - small)
            self.rerr = float(small)
        else:
            self.rsum = float(i)
            self.rerr = 0.0

    def add(self, v):
        if v is None:
            return
        self.count += 1
        if isinstance(v, str):
            n = V.text_exact_number(v)
            v = n if isinstance(n, int) else float(V.text_prefix_number(v))
        if not self.approx:
            if isinstance(v, int):
                x = self.isum + v
                if V.INT_MIN <= x <= V.INT_MAX:
                    self.isum = x
                else:
                    self.overflow = True
                    self._start_approx()
                    self._kbn_int(v)
            else:
                self._start_approx()
                self._kbn(v)
        elif isinstance(v, int):
            self._kbn_int(v)
        else:
            self.overflow = False
            self._kbn(v)

    def _real(self) -> float:
        if math.isinf(self.rsum):
            return self.rsum
        return self.rsum + self.rerr

    def sum(self):
        if self.count == 0:
            return None
        if self.approx:
            if self.overflow:
                raise SQLError("integer overflow")
            return self._real()
        return self.isum

    def total(self):
        return self._real() if self.approx else float(self.isum)

    def avg(self):
        if self.count == 0:
            return None
        r = self._real() if self.approx else float(self.isum)
        return r / self.count


def _distinct(values):
    seen = set()
    out = []
    for v in values:
        if v is not None and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def compute_aggregates(specs: list[AggSpec], rows: list[tuple]):
    """Evaluate aggregates over a group; return (values, representative row or None)."""
    results = []
    # Bare columns come from the group's first row, or from the row holding the extreme
    # value of a min()/max() aggregate (the last such aggregate wins), as in SQLite.
    rep = rows[0] if rows else None
    minmax_row = None
    for spec in specs:
        name = spec.name
        if spec.star:
            results.append(len(rows))
            continue
        arg = spec.args[0]
        vals = [arg(r, None) for r in rows]
        if spec.distinct:
            vals = _distinct(vals)
        if name == "COUNT":
            results.append(sum(1 for v in vals if v is not None))
        elif name in ("SUM", "AVG", "TOTAL"):
            acc = _Sum()
            for v in vals:
                acc.add(v)
            if name == "SUM":
                results.append(acc.sum())
            elif name == "AVG":
                results.append(acc.avg())
            else:
                results.append(acc.total())
        elif name in ("MIN", "MAX"):
            want = -1 if name == "MIN" else 1
            best = None
            best_i = None
            for i, v in enumerate(vals):
                if v is not None and (best is None or V.compare(v, best) == want):
                    best = v
                    best_i = i
            results.append(best)
            if best_i is not None and not spec.distinct:
                minmax_row = rows[best_i]
        else:  # GROUP_CONCAT
            seps = [spec.args[1](r, None) for r in rows] if len(spec.args) > 1 else None
            out = None
            for i, v in enumerate(vals):
                if v is None:
                    continue
                if out is None:
                    out = V.to_text(v)
                else:
                    sep = "," if seps is None else seps[i]
                    out += ("" if sep is None else V.to_text(sep)) + V.to_text(v)
            results.append(out)
    return results, (minmax_row if minmax_row is not None else rep)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def _integer_constant(expr: ast.Expr) -> int | None:
    """The value of an integer literal, possibly signed (ORDER BY/GROUP BY positions)."""
    if isinstance(expr, ast.Literal):
        return expr.value if isinstance(expr.value, int) else None
    if isinstance(expr, ast.Unary) and expr.op in "+-":
        inner = _integer_constant(expr.operand)
        if inner is not None:
            return -inner if expr.op == "-" else inner
    return None


class Database:
    """An in-memory SQL database. `execute` runs one statement."""

    def __init__(self):
        self.tables: dict[str, Table] = {}

    def execute(self, sql: str) -> list[tuple]:
        if not isinstance(sql, str):
            raise SQLError("SQL must be a string")
        stmt = parse(sql)
        handler = getattr(self, "_exec_" + type(stmt).__name__)
        try:
            return handler(stmt)
        except RecursionError:
            raise SQLError("expression too deeply nested") from None

    def _table(self, name: str) -> Table:
        table = self.tables.get(name.lower())
        if table is None:
            raise SQLError(f"no such table: {name}")
        return table

    # ---- DDL ----

    def _exec_CreateTable(self, stmt: ast.CreateTable):
        key = stmt.name.lower()
        if key in self.tables:
            if stmt.if_not_exists:
                return []
            raise SQLError(f"table {stmt.name} already exists")
        self.tables[key] = Table(stmt.name, stmt.columns)
        return []

    def _exec_DropTable(self, stmt: ast.DropTable):
        key = stmt.name.lower()
        if key not in self.tables:
            if stmt.if_exists:
                return []
            raise SQLError(f"no such table: {stmt.name}")
        del self.tables[key]
        return []

    # ---- DML ----

    def _exec_Insert(self, stmt: ast.Insert):
        table = self._table(stmt.table)
        if stmt.columns is None:
            targets = list(range(len(table.columns)))
        else:
            targets = [table.column_index(c) for c in stmt.columns]
            if len(set(targets)) != len(targets):
                raise SQLError("duplicate column in INSERT")
        if stmt.select is not None:
            source = self._exec_Select(stmt.select)
        else:
            compiler = Compiler(Scope())
            source = []
            for exprs in stmt.rows:
                fns = [compiler.fn(x) for x in exprs]
                source.append(tuple(f((), None) for f in fns))
        new_rows = []
        for values in source:
            if len(values) != len(targets):
                raise SQLError(
                    f"table {table.name} has {len(table.columns)} columns but "
                    f"{len(values)} values were supplied"
                    if stmt.columns is None
                    else f"{len(values)} values for {len(targets)} columns"
                )
            row = [None] * len(table.columns)
            for idx, v in zip(targets, values, strict=True):
                row[idx] = V.apply_affinity(v, table.affinities[idx])
            new_rows.append(tuple(row))
        table.rows.extend(new_rows)
        return []

    def _table_scope(self, table: Table) -> Scope:
        scope = Scope()
        scope.add(table.name, table)
        return scope

    def _exec_Update(self, stmt: ast.Update):
        table = self._table(stmt.table)
        compiler = Compiler(self._table_scope(table))
        where = compiler.fn(stmt.where) if stmt.where is not None else None
        sets = [(table.column_index(c), compiler.fn(x)) for c, x in stmt.assignments]
        updated = []
        for row in table.rows:
            if where is None or V.truth(where(row, None)):
                new = list(row)
                for idx, f in sets:
                    new[idx] = V.apply_affinity(f(row, None), table.affinities[idx])
                row = tuple(new)
            updated.append(row)
        table.rows = updated
        return []

    def _exec_Delete(self, stmt: ast.Delete):
        table = self._table(stmt.table)
        if stmt.where is None:
            table.rows = []
            return []
        where = Compiler(self._table_scope(table)).fn(stmt.where)
        table.rows = [row for row in table.rows if not V.truth(where(row, None))]
        return []

    # ---- SELECT ----

    def _from_clause(self, sel: ast.Select):
        scope = Scope()
        if sel.from_ is None:
            return scope, [()]
        first = self._table(sel.from_.name)
        scope.add(sel.from_.alias or first.name, first)
        rows = list(first.rows)
        for join in sel.joins:
            table = self._table(join.table.name)
            scope.add(join.table.alias or table.name, table)
            on = Compiler(scope).fn(join.on) if join.on is not None else None
            pad = (None,) * len(table.columns)
            right_rows = table.rows
            index = self._join_index(join.on, scope, table) if join.on is not None else None
            joined = []
            for left in rows:
                matched = False
                if index is not None:
                    left_key, buckets = index
                    key = left_key(left)
                    candidates = buckets.get(key, ()) if key is not None else ()
                else:
                    candidates = right_rows
                for right in candidates:
                    combined = left + right
                    if on is None or V.truth(on(combined, None)):
                        joined.append(combined)
                        matched = True
                if not matched and join.kind == "LEFT":
                    joined.append(left + pad)
            rows = joined
        return scope, rows

    def _join_index(self, on: ast.Expr, scope: Scope, table: Table):
        """Hash the joined table on an `earlier = new` equality conjunct of the ON clause.

        Returns (left_key_fn, buckets) or None. Buckets narrow the candidate rows; the full ON
        condition is still evaluated on each candidate.
        """
        conjuncts = []
        stack = [on]
        while stack:
            e = stack.pop()
            if isinstance(e, ast.Binary) and e.op == "AND":
                stack += [e.left, e.right]
            else:
                conjuncts.append(e)
        start = scope.entries[-1].offset
        for e in conjuncts:
            if not (
                isinstance(e, ast.Binary)
                and e.op == "="
                and isinstance(e.left, ast.Column)
                and isinstance(e.right, ast.Column)
            ):
                continue
            a = scope.resolve(e.left.table, e.left.name)
            b = scope.resolve(e.right.table, e.right.name)
            if a is None or b is None:
                continue
            if a[0] >= start and b[0] < start:
                a, b = b, a
            if not (a[0] < start <= b[0]):
                continue
            (left_idx, left_aff), (right_idx, right_aff) = a, b
            conv_left, conv_right = _comparison_converters(left_aff, right_aff)
            right_idx -= start
            buckets: dict[object, list[tuple]] = {}
            for row in table.rows:
                v = row[right_idx]
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    continue
                if conv_right:
                    v = V.apply_affinity(v, conv_right)
                buckets.setdefault(v, []).append(row)

            def left_key(row, i=left_idx, conv=conv_left):
                v = row[i]
                if v is not None and conv:
                    v = V.apply_affinity(v, conv)
                return v

            return left_key, buckets
        return None

    def _expand_items(self, sel: ast.Select, scope: Scope):
        items: list[tuple[ast.Expr, str | None]] = []
        for item in sel.items:
            if item.expr is not None:
                items.append((item.expr, item.alias))
                continue
            if not scope.entries:
                raise SQLError("no tables specified")
            entries = [scope.find(item.star_table)] if item.star_table else scope.entries
            for entry in entries:
                for i, _ in enumerate(entry.table.columns):
                    items.append((_Slot(entry.offset + i, entry.table.affinities[i]), None))
        return items

    def _constant_int(self, expr: ast.Expr, what: str) -> int:
        v = Compiler(Scope()).fn(expr)((), None)
        v = V.apply_affinity(v, V.INTEGER)
        if not isinstance(v, int):
            raise SQLError(f"datatype mismatch in {what}")
        return v

    def _exec_Select(self, sel: ast.Select):
        scope, rows = self._from_clause(sel)
        items = self._expand_items(sel, scope)
        aliases = {alias.lower(): expr for expr, alias in items if alias}

        if sel.where is not None:
            where = Compiler(scope, None, aliases).fn(sel.where)
            rows = [r for r in rows if V.truth(where(r, None))]

        aggs: list[AggSpec] = []
        compiler = Compiler(scope, aggs, aliases)
        item_fns = [Compiler(scope, aggs).fn(expr) for expr, _ in items]
        having = compiler.fn(sel.having) if sel.having is not None else None
        is_aggregate = bool(sel.group_by) or bool(aggs)
        if having is not None and not is_aggregate:
            raise SQLError("HAVING clause on a non-aggregate query")
        # ORDER BY may use aggregates only in an aggregate query.
        order_compiler = compiler if is_aggregate else Compiler(scope, None, aliases)

        # Each ORDER BY key is either an output column index or a compiled expression.
        order_keys = []
        for term in sel.order_by:
            expr = term.expr
            out_idx = None
            position = _integer_constant(expr)
            if position is not None:
                if not 1 <= position <= len(items):
                    raise SQLError(
                        f"ORDER BY term out of range - should be between 1 and {len(items)}"
                    )
                out_idx = position - 1
            elif isinstance(expr, ast.Column) and expr.table is None:
                for i, (_, alias) in enumerate(items):
                    if alias is not None and alias.lower() == expr.name.lower():
                        out_idx = i
                        break
            if out_idx is not None:
                order_keys.append((out_idx, None, term.desc))
            else:
                order_keys.append((None, order_compiler.fn(expr), term.desc))

        group_fns = []
        group_compiler = Compiler(scope, None, aliases)
        for expr in sel.group_by:
            position = _integer_constant(expr)
            if position is not None:
                if not 1 <= position <= len(items):
                    raise SQLError(
                        f"GROUP BY term out of range - should be between 1 and {len(items)}"
                    )
                expr = items[position - 1][0]
            group_fns.append(group_compiler.fn(expr))

        results = []  # (output tuple, sort keys)

        def emit(row, aggvals):
            out = tuple(f(row, aggvals) for f in item_fns)
            keys = [out[i] if i is not None else f(row, aggvals) for i, f, _ in order_keys]
            results.append((out, keys))

        if is_aggregate:
            if group_fns:
                groups: dict[tuple, list[tuple]] = {}
                for r in rows:
                    key = tuple(f(r, None) for f in group_fns)
                    groups.setdefault(key, []).append(r)
                group_rows = list(groups.values())
            else:
                group_rows = [rows]
            null_row = (None,) * scope.width
            for grows in group_rows:
                aggvals, rep = compute_aggregates(aggs, grows)
                if rep is None:
                    rep = null_row
                if having is not None and not V.truth(having(rep, aggvals)):
                    continue
                emit(rep, aggvals)
        else:
            for r in rows:
                emit(r, None)

        if sel.distinct:
            seen = set()
            unique = []
            for out, keys in results:
                if out not in seen:
                    seen.add(out)
                    unique.append((out, keys))
            results = unique

        for i in reversed(range(len(order_keys))):
            desc = order_keys[i][2]
            results.sort(key=lambda item, i=i: V.sort_key(item[1][i]), reverse=desc)

        output = [out for out, _ in results]
        if sel.limit is not None:
            limit = self._constant_int(sel.limit, "LIMIT")
            offset = self._constant_int(sel.offset, "OFFSET") if sel.offset is not None else 0
            offset = max(offset, 0)
            output = output[offset:] if limit < 0 else output[offset : offset + limit]
        return output
