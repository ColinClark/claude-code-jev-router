"""Compile expression ASTs into Python closures.

A compiled expression is a function taking an environment `env = (row, aggs)`, where `row` is the
flat list of column values of the current (joined) row and `aggs` holds finalized aggregate values
of the current group (None outside aggregate queries).
"""

import re
from dataclasses import dataclass

from minisql.errors import SQLError
from minisql.values import (
    arith,
    compare,
    comparison_converters,
    in_list_converter,
    negate,
    to_numeric,
    to_text,
    truth,
)

AGGREGATES = frozenset({"count", "sum", "avg", "min", "max", "total"})


def is_aggregate_call(node) -> bool:
    if node[0] != "func" or node[1] not in AGGREGATES:
        return False
    if node[1] in ("min", "max"):
        return len(node[2]) == 1
    return True


def contains_aggregate(node) -> bool:
    if isinstance(node, list):
        return any(contains_aggregate(x) for x in node)
    if not isinstance(node, tuple) or not node:
        return False
    if isinstance(node[0], str):
        if node[0] == "func" and is_aggregate_call(node):
            return True
        return any(contains_aggregate(x) for x in node[1:])
    return any(contains_aggregate(x) for x in node)


@dataclass
class Source:
    key: str  # lower-cased alias or table name
    table: object  # minisql.database.Table
    offset: int


@dataclass
class AggSpec:
    name: str
    arg: object  # compiled function or None for COUNT(*)
    distinct: bool


class Scope:
    def __init__(self, sources: list[Source] | None = None):
        self.sources = sources or []

    @property
    def width(self) -> int:
        return sum(len(s.table.columns) for s in self.sources)

    def resolve(self, table: str | None, name: str):
        """Return (index, affinity) or None when an unqualified name is not found."""
        lname = name.lower()
        if table is not None:
            matches = [s for s in self.sources if s.key == table.lower()]
            if not matches:
                raise SQLError(f"no such column: {table}.{name}")
            if len(matches) > 1:
                raise SQLError(f"ambiguous column name: {table}.{name}")
            src = matches[0]
            idx = src.table.index_of(lname)
            if idx is None:
                raise SQLError(f"no such column: {table}.{name}")
            return src.offset + idx, src.table.affinities[idx]
        hits = []
        for src in self.sources:
            idx = src.table.index_of(lname)
            if idx is not None:
                hits.append((src.offset + idx, src.table.affinities[idx]))
        if len(hits) > 1:
            raise SQLError(f"ambiguous column name: {name}")
        return hits[0] if hits else None


_LIKE_CACHE: dict[tuple[str, str | None], re.Pattern] = {}
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _like_regex(pattern: str, escape: str | None) -> re.Pattern:
    key = (pattern, escape)
    rx = _LIKE_CACHE.get(key)
    if rx is None:
        parts = []
        i = 0
        pattern = pattern.translate(_ASCII_LOWER)
        while i < len(pattern):
            ch = pattern[i]
            if escape is not None and ch == escape:
                i += 1
                if i < len(pattern):
                    parts.append(re.escape(pattern[i]))
            elif ch == "%":
                parts.append(".*")
            elif ch == "_":
                parts.append(".")
            else:
                parts.append(re.escape(ch))
            i += 1
        rx = re.compile("".join(parts), re.DOTALL)
        if len(_LIKE_CACHE) > 1000:
            _LIKE_CACHE.clear()
        _LIKE_CACHE[key] = rx
    return rx


def like(value, pattern, escape=None):
    if value is None or pattern is None:
        return None
    esc = None
    if escape is not None:
        esc = to_text(escape)
        if len(esc) != 1:
            raise SQLError("ESCAPE expression must be a single character")
    rx = _like_regex(to_text(pattern), esc)
    return 1 if rx.fullmatch(to_text(value).translate(_ASCII_LOWER)) else 0


_CMP_OPS = {
    "=": lambda c: c == 0,
    "!=": lambda c: c != 0,
    "<": lambda c: c < 0,
    "<=": lambda c: c <= 0,
    ">": lambda c: c > 0,
    ">=": lambda c: c >= 0,
}


def _bool3(value):
    return None if value is None else int(value)


def _make_compare(op, lf, rf, lconv, rconv):
    test = _CMP_OPS[op]

    def fn(env):
        a = lf(env)
        if a is None:
            return None
        b = rf(env)
        if b is None:
            return None
        if lconv is not None:
            a = lconv(a)
        if rconv is not None:
            b = rconv(b)
        return 1 if test(compare(a, b)) else 0

    return fn


def _compare_values(a, b, lconv, rconv) -> int:
    if lconv is not None:
        a = lconv(a)
    if rconv is not None:
        b = rconv(b)
    return compare(a, b)


class Compiler:
    def __init__(
        self,
        scope: Scope,
        aliases: dict | None = None,
        aggs: list[AggSpec] | None = None,
    ):
        self.scope = scope
        self.aliases = aliases or {}
        self.aggs = aggs  # None means aggregates are not allowed here
        self._expanding: set[str] = set()
        self._in_agg = False

    def compile(self, node):
        return self._compile(node)[0]

    def compile_with_affinity(self, node):
        return self._compile(node)

    def _compile(self, node):
        kind = node[0]
        method = getattr(self, "_c_" + kind)
        return method(node)

    def _c_lit(self, node):
        value = node[1]
        return (lambda env: value), None

    def _c_colidx(self, node):
        idx = node[1]
        return (lambda env: env[0][idx]), node[2]

    def _c_col(self, node):
        _, table, name = node
        resolved = self.scope.resolve(table, name)
        if resolved is None:
            key = name.lower()
            if key in self.aliases and key not in self._expanding:
                self._expanding.add(key)
                try:
                    return self._compile(self.aliases[key])
                finally:
                    self._expanding.discard(key)
            raise SQLError(f"no such column: {name}")
        idx, aff = resolved
        return (lambda env: env[0][idx]), aff

    def _c_neg(self, node):
        f = self.compile(node[1])
        return (lambda env: negate(f(env))), None

    def _c_pos(self, node):
        return self._compile(node[1])

    def _c_binop(self, node):
        _, op, left, right = node
        lf, rf = self.compile(left), self.compile(right)
        return (lambda env: arith(op, lf(env), rf(env))), None

    def _c_cmp(self, node):
        _, op, left, right = node
        lf, la = self._compile(left)
        rf, ra = self._compile(right)
        lconv, rconv = comparison_converters(la, ra)
        return _make_compare(op, lf, rf, lconv, rconv), None

    def _c_is(self, node):
        _, left, right, negated = node
        lf, la = self._compile(left)
        rf, ra = self._compile(right)
        lconv, rconv = comparison_converters(la, ra)

        def fn(env):
            a, b = lf(env), rf(env)
            if a is None or b is None:
                same = a is None and b is None
            else:
                same = _compare_values(a, b, lconv, rconv) == 0
            return int(same != negated)

        return fn, None

    def _c_and(self, node):
        lf, rf = self.compile(node[1]), self.compile(node[2])

        def fn(env):
            a = truth(lf(env))
            if a is False:
                return 0
            b = truth(rf(env))
            if b is False:
                return 0
            if a is None or b is None:
                return None
            return 1

        return fn, None

    def _c_or(self, node):
        lf, rf = self.compile(node[1]), self.compile(node[2])

        def fn(env):
            a = truth(lf(env))
            if a is True:
                return 1
            b = truth(rf(env))
            if b is True:
                return 1
            if a is None or b is None:
                return None
            return 0

        return fn, None

    def _c_not(self, node):
        f = self.compile(node[1])

        def fn(env):
            t = truth(f(env))
            return None if t is None else int(not t)

        return fn, None

    def _c_in(self, node):
        _, expr, items, negated = node
        lf, la = self._compile(expr)
        # SQLite applies the left operand's affinity to both sides of every comparison.
        conv = in_list_converter(la)
        compiled = [(self.compile(item), conv, conv) for item in items]

        def fn(env):
            if not compiled:
                return int(negated)
            a = lf(env)
            if a is None:
                return None
            saw_null = False
            for f, lconv, rconv in compiled:
                b = f(env)
                if b is None:
                    saw_null = True
                elif _compare_values(a, b, lconv, rconv) == 0:
                    return 0 if negated else 1
            if saw_null:
                return None
            return 1 if negated else 0

        return fn, None

    def _c_between(self, node):
        _, expr, low, high, negated = node
        lf, la = self._compile(expr)
        lof, loa = self._compile(low)
        hif, hia = self._compile(high)
        ge = _make_compare(">=", lf, lof, *comparison_converters(la, loa))
        le = _make_compare("<=", lf, hif, *comparison_converters(la, hia))

        def fn(env):
            a, b = truth(ge(env)), truth(le(env))
            if a is False or b is False:
                result = False
            elif a is None or b is None:
                return None
            else:
                result = True
            return int(result != negated)

        return fn, None

    def _c_like(self, node):
        _, expr, pattern, escape, negated = node
        vf, pf = self.compile(expr), self.compile(pattern)
        ef = self.compile(escape) if escape is not None else None

        def fn(env):
            esc = None
            if ef is not None:
                esc = ef(env)
                if esc is None:
                    return None
            r = like(vf(env), pf(env), esc)
            if r is None:
                return None
            return 1 - r if negated else r

        return fn, None

    def _c_case(self, node):
        _, base, whens, default = node
        df = self.compile(default) if default is not None else (lambda env: None)
        if base is None:
            branches = [(self.compile(c), self.compile(r)) for c, r in whens]

            def fn(env):
                for cond, res in branches:
                    if truth(cond(env)) is True:
                        return res(env)
                return df(env)

            return fn, None
        bf, ba = self._compile(base)
        cases = []
        for c, r in whens:
            cf, ca = self._compile(c)
            cases.append((_make_compare("=", bf, cf, *comparison_converters(ba, ca)),
                          self.compile(r)))

        def fn_base(env):
            for test, res in cases:
                if test(env) == 1:
                    return res(env)
            return df(env)

        return fn_base, None

    def _c_func(self, node):
        _, name, args, distinct, star = node
        if is_aggregate_call(node):
            return self._compile_aggregate(name, args, distinct, star)
        if star or distinct:
            raise SQLError(f"wrong use of {name}()")
        fns = [self.compile(a) for a in args]
        impl = SCALAR_FUNCTIONS.get(name)
        if impl is None:
            raise SQLError(f"no such function: {name}")
        min_args, max_args, func = impl
        if len(fns) < min_args or (max_args is not None and len(fns) > max_args):
            raise SQLError(f"wrong number of arguments to function {name}()")
        return (lambda env: func(*[f(env) for f in fns])), None

    def _compile_aggregate(self, name, args, distinct, star):
        if self.aggs is None or self._in_agg:
            raise SQLError(f"misuse of aggregate function {name}()")
        if star:
            if name != "count":
                raise SQLError(f"wrong use of {name}(*)")
            arg = None
        else:
            if len(args) != 1:
                raise SQLError(f"wrong number of arguments to function {name}()")
            self._in_agg = True
            try:
                arg = self.compile(args[0])
            finally:
                self._in_agg = False
        index = len(self.aggs)
        self.aggs.append(AggSpec(name, arg, distinct))
        return (lambda env: env[1][index]), None


# -- scalar functions --------------------------------------------------------

def _abs(v):
    if v is None:
        return None
    if isinstance(v, str):
        return abs(float(to_numeric(v)))
    if isinstance(v, int) and v == -(1 << 63):
        raise SQLError("integer overflow")
    return abs(v)


def _length(v):
    return None if v is None else len(to_text(v))


def _upper(v):
    return None if v is None else to_text(v).translate(_ASCII_UPPER)


def _lower(v):
    return None if v is None else to_text(v).translate(_ASCII_LOWER)


def _coalesce(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def _nullif(a, b):
    if a is not None and b is not None and compare(a, b) == 0:
        return None
    return a


def _typeof(v):
    if v is None:
        return "null"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "real"
    return "text"


def _scalar_extreme(pick):
    def fn(*vals):
        if any(v is None for v in vals):
            return None
        best = vals[0]
        for v in vals[1:]:
            if pick(compare(v, best)):
                best = v
        return best

    return fn


SCALAR_FUNCTIONS = {
    "abs": (1, 1, _abs),
    "length": (1, 1, _length),
    "upper": (1, 1, _upper),
    "lower": (1, 1, _lower),
    "coalesce": (2, None, _coalesce),
    "ifnull": (2, 2, _coalesce),
    "nullif": (2, 2, _nullif),
    "typeof": (1, 1, _typeof),
    "min": (2, None, _scalar_extreme(lambda c: c < 0)),
    "max": (2, None, _scalar_extreme(lambda c: c > 0)),
}
