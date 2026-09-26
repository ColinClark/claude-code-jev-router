"""Scalar and aggregate SQL functions."""

from __future__ import annotations

import math
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal

from minisql import values as V
from minisql.errors import SQLError
from minisql.values import Value

# ---------------------------------------------------------------------------
# Scalar functions
# ---------------------------------------------------------------------------


def _ascii_upper(s: str) -> str:
    return "".join(chr(ord(c) - 32) if "a" <= c <= "z" else c for c in s)


def _ascii_lower(s: str) -> str:
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)


def f_abs(x: Value) -> Value:
    if x is None:
        return None
    if isinstance(x, int):
        if x == V.INT_MIN:
            raise SQLError("integer overflow")
        return abs(x)
    return abs(V.to_real(x))  # type: ignore[arg-type]


def f_length(x: Value) -> Value:
    if x is None:
        return None
    return len(V.to_text(x))  # type: ignore[arg-type]


def f_upper(x: Value) -> Value:
    return None if x is None else _ascii_upper(V.to_text(x))  # type: ignore[arg-type]


def f_lower(x: Value) -> Value:
    return None if x is None else _ascii_lower(V.to_text(x))  # type: ignore[arg-type]


def f_coalesce(*args: Value) -> Value:
    for a in args:
        if a is not None:
            return a
    return None


def f_nullif(a: Value, b: Value) -> Value:
    if a is not None and b is not None and V.compare(a, b) == 0:
        return None
    return a


def f_round(x: Value, n: Value = 0) -> Value:
    if x is None or n is None:
        return None
    r = V.to_real(x)
    digits = V.to_int(V.to_numeric(n)) or 0
    digits = max(0, min(30, digits))
    assert r is not None
    if not math.isfinite(r) or abs(r) > 4503599627370496.0:
        return r
    if digits == 0:
        return float(int(r + (-0.5 if r < 0 else 0.5)))
    d = Decimal(repr(r)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return float(d)


def f_substr(x: Value, start: Value, length: Value = V.INT_MAX) -> Value:
    if x is None or start is None or length is None:
        return None
    s = V.to_text(x)
    assert s is not None
    size = len(s)
    p1 = V.to_int(V.to_numeric(start))
    p2 = V.to_int(V.to_numeric(length))
    assert p1 is not None and p2 is not None
    neg = p2 < 0
    if neg:
        p2 = -p2
    if p1 < 0:
        p1 += size
        if p1 < 0:
            p2 += p1
            if p2 < 0:
                p2 = 0
            p1 = 0
    elif p1 > 0:
        p1 -= 1
    elif p2 > 0:
        p2 -= 1
    if neg:
        p1 -= p2
        if p1 < 0:
            p2 += p1
            p1 = 0
    return s[p1 : p1 + p2]


def _trim(kind: str) -> Callable[..., Value]:
    def fn(x: Value, chars: Value = " ") -> Value:
        if x is None or chars is None:
            return None
        s = V.to_text(x)
        c = V.to_text(chars)
        assert s is not None and c is not None
        if kind == "l":
            return s.lstrip(c)
        if kind == "r":
            return s.rstrip(c)
        return s.strip(c)

    return fn


def f_replace(x: Value, y: Value, z: Value) -> Value:
    if x is None or y is None or z is None:
        return None
    s, old, new = V.to_text(x), V.to_text(y), V.to_text(z)
    assert s is not None and old is not None and new is not None
    if old == "":
        return s
    return s.replace(old, new)


def f_instr(x: Value, y: Value) -> Value:
    if x is None or y is None:
        return None
    s, sub = V.to_text(x), V.to_text(y)
    assert s is not None and sub is not None
    return s.find(sub) + 1


def f_typeof(x: Value) -> Value:
    return V.typeof(x)


def f_min(*args: Value) -> Value:
    if any(a is None for a in args):
        return None
    best = args[0]
    for a in args[1:]:
        if V.compare(a, best) < 0:
            best = a
    return best


def f_max(*args: Value) -> Value:
    if any(a is None for a in args):
        return None
    best = args[0]
    for a in args[1:]:
        if V.compare(a, best) > 0:
            best = a
    return best


def f_sign(x: Value) -> Value:
    if x is None:
        return None
    if isinstance(x, str):
        n = V.numeric_affinity_for_compare(x)
        if isinstance(n, str):
            return None
    else:
        n = x
    return (n > 0) - (n < 0)  # type: ignore[operator]


def f_iif(cond: Value, a: Value, b: Value) -> Value:
    return a if V.truth(cond) else b


# name -> (function, min_args, max_args)  (max_args None = unbounded)
SCALAR_FUNCTIONS: dict[str, tuple[Callable[..., Value], int, int | None]] = {
    "abs": (f_abs, 1, 1),
    "length": (f_length, 1, 1),
    "upper": (f_upper, 1, 1),
    "lower": (f_lower, 1, 1),
    "coalesce": (f_coalesce, 2, None),
    "ifnull": (f_coalesce, 2, 2),
    "nullif": (f_nullif, 2, 2),
    "round": (f_round, 1, 2),
    "substr": (f_substr, 2, 3),
    "substring": (f_substr, 2, 3),
    "trim": (_trim("b"), 1, 2),
    "ltrim": (_trim("l"), 1, 2),
    "rtrim": (_trim("r"), 1, 2),
    "replace": (f_replace, 3, 3),
    "instr": (f_instr, 2, 2),
    "typeof": (f_typeof, 1, 1),
    "min": (f_min, 2, None),
    "max": (f_max, 2, None),
    "sign": (f_sign, 1, 1),
    "iif": (f_iif, 3, 3),
}

# ---------------------------------------------------------------------------
# Aggregate functions
# ---------------------------------------------------------------------------


class Aggregate:
    """Accumulator base class. step() returns True when the row is a new min/max."""

    is_minmax = False

    def step(self, args: tuple[Value, ...]) -> bool:
        raise NotImplementedError

    def final(self) -> Value:
        raise NotImplementedError


class CountStar(Aggregate):
    def __init__(self) -> None:
        self.n = 0

    def step(self, args: tuple[Value, ...]) -> bool:
        self.n += 1
        return False

    def final(self) -> Value:
        return self.n


class Count(Aggregate):
    def __init__(self) -> None:
        self.n = 0

    def step(self, args: tuple[Value, ...]) -> bool:
        if args[0] is not None:
            self.n += 1
        return False

    def final(self) -> Value:
        return self.n


_BIG = 4503599627370496


class _SumBase(Aggregate):
    """SQLite's sum/total/avg accumulator with Kahan-Babuska-Neumaier summation."""

    def __init__(self) -> None:
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

    def _kbn_int(self, i: int) -> None:
        if i <= -_BIG or i >= _BIG:
            small = int(math.fmod(i, 16384))
            self._kbn(float(i - small))
            self._kbn(float(small))
        else:
            self._kbn(float(i))

    def _kbn_init(self, i: int) -> None:
        if i <= -_BIG or i >= _BIG:
            small = int(math.fmod(i, 16384))
            self.rsum = float(i - small)
            self.rerr = float(small)
        else:
            self.rsum = float(i)
            self.rerr = 0.0

    def step(self, args: tuple[Value, ...]) -> bool:
        v = args[0]
        if v is None:
            return False
        if isinstance(v, str):
            num = V.numeric_affinity_for_compare(v)
            v = num if isinstance(num, int) else V.to_real(v)
        self.cnt += 1
        if not self.approx:
            if not isinstance(v, int):
                self._kbn_init(self.isum)
                self.approx = True
                self._kbn(float(v))  # type: ignore[arg-type]
            else:
                x = self.isum + v
                if V.INT_MIN <= x <= V.INT_MAX:
                    self.isum = x
                else:
                    self.overflow = True
                    self._kbn_init(self.isum)
                    self.approx = True
                    self._kbn_int(v)
        else:
            if isinstance(v, int):
                self._kbn_int(v)
            else:
                self.overflow = False
                self._kbn(float(v))  # type: ignore[arg-type]
        return False

    def _real_total(self) -> float:
        if self.approx:
            if math.isinf(self.rsum):
                return self.rsum
            return self.rsum + self.rerr
        return float(self.isum)


class Sum(_SumBase):
    def final(self) -> Value:
        if self.cnt == 0:
            return None
        if self.approx:
            if self.overflow:
                raise SQLError("integer overflow")
            return self._real_total()
        return self.isum


class Total(_SumBase):
    def final(self) -> Value:
        return self._real_total() if self.cnt else 0.0


class Avg(_SumBase):
    def final(self) -> Value:
        if self.cnt == 0:
            return None
        return self._real_total() / self.cnt


class MinMax(Aggregate):
    is_minmax = True

    def __init__(self, want_max: bool) -> None:
        self.want_max = want_max
        self.best: Value = None
        self.has_best = False

    def step(self, args: tuple[Value, ...]) -> bool:
        v = args[0]
        if v is None:
            return not self.has_best
        if not self.has_best:
            self.best = v
            self.has_best = True
            return True
        c = V.compare(self.best, v)
        if (self.want_max and c < 0) or (not self.want_max and c > 0):
            self.best = v
            return True
        return False

    def final(self) -> Value:
        return self.best


class GroupConcat(Aggregate):
    def __init__(self) -> None:
        self.parts: list[str] = []

    def step(self, args: tuple[Value, ...]) -> bool:
        v = args[0]
        if v is None:
            return False
        if self.parts:
            sep = "," if len(args) < 2 else args[1]
            self.parts.append("" if sep is None else V.to_text(sep))  # type: ignore[arg-type]
        self.parts.append(V.to_text(v))  # type: ignore[arg-type]
        return False

    def final(self) -> Value:
        if not self.parts:
            return None
        return "".join(self.parts)


class Distinct(Aggregate):
    def __init__(self, inner: Aggregate) -> None:
        self.inner = inner
        self.is_minmax = inner.is_minmax
        self.seen: set[tuple] = set()

    def step(self, args: tuple[Value, ...]) -> bool:
        if args[0] is not None:
            key = V.value_key(args[0])
            if key in self.seen:
                return False
            self.seen.add(key)
        return self.inner.step(args)

    def final(self) -> Value:
        return self.inner.final()


# name -> (factory, min_args, max_args)
AGGREGATE_FUNCTIONS: dict[str, tuple[Callable[[], Aggregate], int, int]] = {
    "count": (Count, 0, 1),
    "sum": (Sum, 1, 1),
    "total": (Total, 1, 1),
    "avg": (Avg, 1, 1),
    "min": (lambda: MinMax(False), 1, 1),
    "max": (lambda: MinMax(True), 1, 1),
    "group_concat": (GroupConcat, 1, 2),
}


def is_aggregate_call(name: str, nargs: int, star: bool) -> bool:
    if name not in AGGREGATE_FUNCTIONS:
        return False
    if name in ("min", "max"):
        return nargs == 1
    return True
