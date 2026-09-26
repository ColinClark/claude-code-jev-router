"""Compile expression ASTs into Python closures over flat row tuples."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from . import ast as A
from . import values as V
from .errors import SQLError
from .parser import AGGREGATES

Row = tuple
Fn = Callable[[Row], object]


@dataclass(slots=True)
class ScopeEntry:
    alias: str  # lower-cased name used to qualify columns
    columns: list[str]  # lower-cased column names
    affinities: list[str]
    offset: int


class Scope:
    def __init__(self) -> None:
        self.entries: list[ScopeEntry] = []
        self.width = 0

    def add(self, alias: str, columns: list[str], affinities: list[str]) -> None:
        self.entries.append(ScopeEntry(alias.lower(), columns, affinities, self.width))
        self.width += len(columns)

    def copy(self) -> Scope:
        s = Scope()
        s.entries = list(self.entries)
        s.width = self.width
        return s

    def find_entry(self, alias: str) -> ScopeEntry | None:
        a = alias.lower()
        for e in self.entries:
            if e.alias == a:
                return e
        return None

    def resolve(self, table: str | None, name: str) -> tuple[int, str] | None:
        """Return (index, affinity) or None if not found. Raises on ambiguity."""
        n = name.lower()
        if table is not None:
            t = table.lower()
            matches = [e for e in self.entries if e.alias == t]
            if not matches:
                raise SQLError(f"no such column: {table}.{name}")
            found = []
            for e in matches:
                if n in e.columns:
                    i = e.columns.index(n)
                    found.append((e.offset + i, e.affinities[i]))
            if not found:
                raise SQLError(f"no such column: {table}.{name}")
            if len(found) > 1:
                raise SQLError(f"ambiguous column name: {table}.{name}")
            return found[0]
        found = []
        for e in self.entries:
            if n in e.columns:
                i = e.columns.index(n)
                found.append((e.offset + i, e.affinities[i]))
        if len(found) > 1:
            raise SQLError(f"ambiguous column name: {name}")
        return found[0] if found else None


@dataclass(slots=True)
class AggSpec:
    name: str
    arg: Fn | None  # None for COUNT(*)
    distinct: bool
    extra: Fn | None = None  # separator for group_concat


def contains_aggregate(node: object) -> bool:
    if isinstance(node, A.Func):
        if node.name in AGGREGATES and not (
            node.name in ("MIN", "MAX") and len(node.args) != 1
        ):
            return True
        return any(contains_aggregate(a) for a in node.args)
    if isinstance(node, A.Unary):
        return contains_aggregate(node.operand)
    if isinstance(node, A.Binary):
        return contains_aggregate(node.left) or contains_aggregate(node.right)
    if isinstance(node, A.InList):
        return contains_aggregate(node.expr) or any(contains_aggregate(i) for i in node.items)
    if isinstance(node, A.Between):
        return any(contains_aggregate(x) for x in (node.expr, node.low, node.high))
    if isinstance(node, A.Like):
        return any(
            contains_aggregate(x) for x in (node.expr, node.pattern, node.escape) if x is not None
        )
    if isinstance(node, A.Case):
        parts: list[object] = [node.operand, node.else_]
        for w, t in node.whens:
            parts += [w, t]
        return any(contains_aggregate(p) for p in parts if p is not None)
    if isinstance(node, A.Cast):
        return contains_aggregate(node.expr)
    return False


def _cast_affinity(type_name: str) -> str:
    return V.affinity_of_type(type_name)


def cast_value(v: object, type_name: str) -> object:
    if v is None:
        return None
    aff = _cast_affinity(type_name)
    if aff == "TEXT":
        return V.to_text(v)  # type: ignore[arg-type]
    if aff == "BLOB":
        return V.to_text(v) if not isinstance(v, str) else v  # type: ignore[arg-type]
    if aff == "INTEGER":
        return V.to_int(v)  # type: ignore[arg-type]
    if aff == "REAL":
        n = V.to_number(v)  # type: ignore[arg-type]
        return float(n)  # type: ignore[arg-type]
    # NUMERIC
    if isinstance(v, str):
        n = V.to_number(v)
        if isinstance(n, float) and n.is_integer() and abs(n) < 9.2e18:
            return int(n)
        return n
    return v


class Compiler:
    """Compiles expressions against a scope.

    ``aggs`` is a list collecting aggregate specs when aggregates are allowed (or None).
    Aggregate results are read from ``row[agg_base + k]``.
    ``aliases`` maps lower-cased output aliases to expressions (SQLite allows referring to
    result-column aliases in WHERE/GROUP BY/HAVING/ORDER BY).
    """

    def __init__(
        self,
        scope: Scope,
        aggs: list[AggSpec] | None = None,
        agg_base: int = 0,
        aliases: dict[str, A.Expr] | None = None,
        context: str = "expression",
    ):
        self.scope = scope
        self.aggs = aggs
        self.agg_base = agg_base
        self.aliases = aliases
        self.context = context

    def compile(self, node: A.Expr) -> tuple[Fn, str | None]:
        method = getattr(self, "c_" + type(node).__name__)
        return method(node)

    def fn(self, node: A.Expr) -> Fn:
        return self.compile(node)[0]

    # -- leaves ------------------------------------------------------------

    def c_Literal(self, node: A.Literal):
        v = node.value
        return (lambda r: v), None

    def c_Column(self, node: A.Column):
        res = self.scope.resolve(node.table, node.name)
        if res is None:
            if node.table is None and self.aliases is not None:
                alias_expr = self.aliases.get(node.name.lower())
                if alias_expr is not None:
                    sub = Compiler(self.scope, self.aggs, self.agg_base, None, self.context)
                    return sub.compile(alias_expr)
            raise SQLError(f"no such column: {node.name}")
        idx, aff = res
        return (lambda r: r[idx]), aff

    # -- operators ---------------------------------------------------------

    def c_Unary(self, node: A.Unary):
        f, aff = self.compile(node.operand)
        if node.op == "+":
            return f, None
        if node.op == "-":
            if isinstance(node.operand, A.Literal) and isinstance(
                node.operand.value, (int, float)
            ):
                # SQLite folds negated numeric literals directly (so -0.0 stays -0.0) ...
                return (lambda r: V.negate(f(r))), None
            # ... but computes other negations as 0 - x.
            return (lambda r: V.arith("-", 0, f(r))), None
        if node.op == "~":

            def bnot(r):
                v = V.to_int(f(r))
                return None if v is None else ~v

            return bnot, None
        # NOT

        def not_(r):
            b = V.to_bool(f(r))
            return None if b is None else int(not b)

        return not_, None

    def c_Binary(self, node: A.Binary):
        op = node.op
        lf, la = self.compile(node.left)
        rf, ra = self.compile(node.right)
        if op in ("+", "-", "*", "/", "%"):
            return (lambda r: V.arith(op, lf(r), rf(r))), None
        if op == "||":
            return (lambda r: V.concat(lf(r), rf(r))), None
        if op in ("&", "|", "<<", ">>"):
            return (lambda r: V.bitop(op, lf(r), rf(r))), None
        if op == "AND":

            def and_(r):
                a = V.to_bool(lf(r))
                if a is False:
                    return 0
                b = V.to_bool(rf(r))
                if b is False:
                    return 0
                if a is None or b is None:
                    return None
                return 1

            return and_, None
        if op == "OR":

            def or_(r):
                a = V.to_bool(lf(r))
                if a is True:
                    return 1
                b = V.to_bool(rf(r))
                if b is True:
                    return 1
                if a is None or b is None:
                    return None
                return 0

            return or_, None
        lconv, rconv = V.comparison_converters(la, ra)
        if op in ("IS", "ISNOT"):
            want = op == "IS"

            def is_(r):
                a = lf(r)
                b = rf(r)
                if a is None or b is None:
                    return int((a is None and b is None) == want)
                if lconv:
                    a = lconv(a)
                if rconv:
                    b = rconv(b)
                return int((V.compare(a, b) == 0) == want)

            return is_, None
        test = _CMP_TESTS[op]

        def cmp(r):
            a = lf(r)
            if a is None:
                return None
            b = rf(r)
            if b is None:
                return None
            if lconv:
                a = lconv(a)
            if rconv:
                b = rconv(b)
            return int(test(V.compare(a, b)))

        return cmp, None

    def c_InList(self, node: A.InList):
        lf, la = self.compile(node.expr)
        items = [self.fn(i) for i in node.items]
        _, conv = V.comparison_converters(la, None)
        negated = node.negated

        def in_(r):
            if not items:
                return int(negated)
            a = lf(r)
            if a is None:
                return None
            saw_null = False
            for f in items:
                b = f(r)
                if b is None:
                    saw_null = True
                    continue
                if conv:
                    b = conv(b)
                if V.compare(a, b) == 0:
                    return int(not negated)
            if saw_null:
                return None
            return int(negated)

        return in_, None

    def c_Between(self, node: A.Between):
        ef, ea = self.compile(node.expr)
        lof, loa = self.compile(node.low)
        hif, hia = self.compile(node.high)
        c1 = V.comparison_converters(ea, loa)
        c2 = V.comparison_converters(ea, hia)
        negated = node.negated

        def cmp(a, b, convs):
            if a is None or b is None:
                return None
            if convs[0]:
                a = convs[0](a)
            if convs[1]:
                b = convs[1](b)
            return V.compare(a, b)

        def between(r):
            a = ef(r)
            lo = cmp(a, lof(r), c1)
            ge = None if lo is None else lo >= 0
            if ge is False:
                res = 0
            else:
                hi = cmp(a, hif(r), c2)
                le = None if hi is None else hi <= 0
                if le is False:
                    res = 0
                elif ge is None or le is None:
                    return None
                else:
                    res = 1
            return int(not res) if negated else res

        return between, None

    def c_Like(self, node: A.Like):
        ef = self.fn(node.expr)
        pf = self.fn(node.pattern)
        xf = self.fn(node.escape) if node.escape is not None else None
        negated = node.negated

        def like(r):
            v = ef(r)
            p = pf(r)
            esc = None
            if xf is not None:
                esc = xf(r)
                if esc is None:
                    return None
                esc = V.to_text(esc)
                if len(esc) != 1:
                    raise SQLError("ESCAPE expression must be a single character")
            if v is None or p is None:
                return None
            m = V.like(V.to_text(v), V.to_text(p), esc)  # type: ignore[arg-type]
            return int(m != negated)

        return like, None

    def c_Case(self, node: A.Case):
        whens = [(self.compile(w), self.fn(t)) for w, t in node.whens]
        else_f = self.fn(node.else_) if node.else_ is not None else (lambda r: None)
        if node.operand is None:

            def case(r):
                for (wf, _), tf in whens:
                    if V.to_bool(wf(r)):
                        return tf(r)
                return else_f(r)

            return case, None
        of, oa = self.compile(node.operand)
        convs = [V.comparison_converters(oa, wa) for (_, wa), _ in whens]

        def case_op(r):
            a = of(r)
            if a is not None:
                for ((wf, _), tf), (c1, c2) in zip(whens, convs, strict=True):
                    b = wf(r)
                    if b is None:
                        continue
                    x = c1(a) if c1 else a
                    y = c2(b) if c2 else b
                    if V.compare(x, y) == 0:
                        return tf(r)
            return else_f(r)

        return case_op, None

    def c_Cast(self, node: A.Cast):
        f = self.fn(node.expr)
        t = node.type_name
        return (lambda r: cast_value(f(r), t)), _cast_affinity(t)

    # -- functions ---------------------------------------------------------

    def c_Func(self, node: A.Func):
        name = node.name
        is_agg = name in AGGREGATES and not (name in ("MIN", "MAX") and len(node.args) != 1)
        if is_agg:
            if self.aggs is None:
                raise SQLError(f"misuse of aggregate function {name.lower()}()")
            if name == "GROUP_CONCAT":
                if len(node.args) not in (1, 2):
                    raise SQLError(f"wrong number of arguments to function {name.lower()}()")
            elif not node.star and len(node.args) != 1:
                raise SQLError(f"wrong number of arguments to function {name.lower()}()")
            inner = Compiler(self.scope, None, 0, self.aliases, self.context)
            arg = None if node.star else inner.fn(node.args[0])
            extra = inner.fn(node.args[1]) if len(node.args) > 1 else None
            self.aggs.append(AggSpec(name, arg, node.distinct, extra))
            idx = self.agg_base + len(self.aggs) - 1
            return (lambda r: r[idx]), None
        if node.distinct:
            raise SQLError(f"DISTINCT aggregates must have exactly one argument: {name}")
        impl = SCALAR_FUNCS.get(name)
        if impl is None:
            raise SQLError(f"no such function: {name}")
        func, nmin, nmax = impl
        if not (nmin <= len(node.args) <= (nmax if nmax >= 0 else 1 << 30)):
            raise SQLError(f"wrong number of arguments to function {name.lower()}()")
        argfs = [self.fn(a) for a in node.args]
        if name in ("COALESCE", "IFNULL"):

            def coalesce(r):
                for f in argfs:
                    v = f(r)
                    if v is not None:
                        return v
                return None

            return coalesce, None
        return (lambda r: func(*[f(r) for f in argfs])), None


_CMP_TESTS = {
    "=": lambda c: c == 0,
    "!=": lambda c: c != 0,
    "<": lambda c: c < 0,
    "<=": lambda c: c <= 0,
    ">": lambda c: c > 0,
    ">=": lambda c: c >= 0,
}


# ---------------------------------------------------------------------------
# Scalar functions


def _abs(v):
    if v is None:
        return None
    n = V.to_number(v)
    if isinstance(n, int):
        if n == V.INT_MIN:
            raise SQLError("integer overflow")
        return abs(n)
    return abs(n)  # type: ignore[arg-type]


def _length(v):
    if v is None:
        return None
    return len(V.to_text(v))  # type: ignore[arg-type]


_UPPER_ASCII = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_LOWER_ASCII = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _upper(v):
    return None if v is None else V.to_text(v).translate(_UPPER_ASCII)  # type: ignore[union-attr]


def _lower(v):
    return None if v is None else V.to_text(v).translate(_LOWER_ASCII)  # type: ignore[union-attr]


def _typeof(v):
    if v is None:
        return "null"
    if isinstance(v, str):
        return "text"
    if isinstance(v, float):
        return "real"
    return "integer"


def _nullif(a, b):
    if a is not None and b is not None and V.compare(a, b) == 0:
        return None
    return a


def _round(v, n=0):
    if v is None or n is None:
        return None
    digits = V.to_int(n) or 0
    digits = max(0, min(digits, 30))
    x = float(V.to_number(v))  # type: ignore[arg-type]
    if digits == 0 and abs(x) < 4503599627370496.0:
        return float(V.real_to_int(x + (0.5 if x >= 0 else -0.5)))
    return float(f"{x:.{digits}f}")


def _substr(s, start, length=None):
    if s is None or start is None:
        return None
    text = V.to_text(s)
    assert text is not None
    p1 = V.to_int(start) or 0
    if length is None:
        p2 = len(text) + 1
        neg_len = False
    else:
        if length is None:
            return None
        p2 = V.to_int(length) or 0
        neg_len = p2 < 0
        if neg_len:
            p2 = -p2
    if p1 < 0:
        p1 += len(text)
        if p1 < 0:
            p2 += p1
            if p2 < 0:
                p2 = 0
            p1 = 0
    elif p1 > 0:
        p1 -= 1
    elif p2 > 0:
        p2 -= 1
    if neg_len:
        p1 -= p2
        if p1 < 0:
            p2 += p1
            p1 = 0
    if length is None:
        return text[p1:]
    return text[p1 : p1 + p2]


def _minmax(pick_max: bool):
    def f(*args):
        best = None
        for a in args:
            if a is None:
                return None
            if best is None:
                best = a
                continue
            c = V.compare(a, best)
            if (c > 0) if pick_max else (c < 0):
                best = a
        return best

    return f


def _instr(a, b):
    if a is None or b is None:
        return None
    return V.to_text(a).find(V.to_text(b)) + 1  # type: ignore[union-attr,arg-type]


def _trim(kind):
    def f(s, chars=" "):
        if s is None or chars is None:
            return None
        t = V.to_text(s)
        c = V.to_text(chars)
        if kind == "L":
            return t.lstrip(c)  # type: ignore[union-attr]
        if kind == "R":
            return t.rstrip(c)  # type: ignore[union-attr]
        return t.strip(c)  # type: ignore[union-attr]

    return f


def _replace(s, old, new):
    if s is None or old is None or new is None:
        return None
    t, o, n = V.to_text(s), V.to_text(old), V.to_text(new)
    if o == "":
        return t
    return t.replace(o, n)  # type: ignore[union-attr,arg-type]


SCALAR_FUNCS: dict[str, tuple[Callable[..., object], int, int]] = {
    "ABS": (_abs, 1, 1),
    "LENGTH": (_length, 1, 1),
    "UPPER": (_upper, 1, 1),
    "LOWER": (_lower, 1, 1),
    "TYPEOF": (_typeof, 1, 1),
    "COALESCE": (lambda *a: None, 2, -1),
    "IFNULL": (lambda *a: None, 2, 2),
    "NULLIF": (_nullif, 2, 2),
    "ROUND": (_round, 1, 2),
    "SUBSTR": (_substr, 2, 3),
    "SUBSTRING": (_substr, 2, 3),
    "MIN": (_minmax(False), 2, -1),
    "MAX": (_minmax(True), 2, -1),
    "INSTR": (_instr, 2, 2),
    "TRIM": (_trim("B"), 1, 2),
    "LTRIM": (_trim("L"), 1, 2),
    "RTRIM": (_trim("R"), 1, 2),
    "REPLACE": (_replace, 3, 3),
}
