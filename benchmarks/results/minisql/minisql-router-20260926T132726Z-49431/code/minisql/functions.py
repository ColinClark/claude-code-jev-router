"""Scalar and aggregate SQL functions with SQLite semantics."""

from __future__ import annotations

import math
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal

from minisql.errors import SQLError
from minisql.values import (
    INT_MIN,
    ascii_lower,
    ascii_upper,
    compare,
    numeric_affinity,
    to_integer,
    to_number,
    to_real,
    to_text,
    type_name,
)

# ---------------------------------------------------------------- scalar


def _abs(x):
    if x is None:
        return None
    if isinstance(x, int):
        if x == INT_MIN:
            raise SQLError("integer overflow")
        return abs(x)
    if isinstance(x, float):
        return abs(x)
    return abs(float(to_number(x)))


def _length(x):
    if x is None:
        return None
    if isinstance(x, bytes):
        return len(x)
    return len(to_text(x))


def _upper(x):
    return None if x is None else ascii_upper(to_text(x))


def _lower(x):
    return None if x is None else ascii_lower(to_text(x))


def _coalesce(*args):
    for a in args:
        if a is not None:
            return a
    return None


def _nullif(a, b):
    if a is not None and b is not None and compare(a, b) == 0:
        return None
    return a


def _typeof(x):
    return type_name(x)


def _scalar_min(*args):
    if any(a is None for a in args):
        return None
    best = args[0]
    for a in args[1:]:
        if compare(a, best) < 0:
            best = a
    return best


def _scalar_max(*args):
    if any(a is None for a in args):
        return None
    best = args[0]
    for a in args[1:]:
        if compare(a, best) > 0:
            best = a
    return best


def _round(x, digits=0):
    if x is None:
        return None
    n = 0
    if digits is not None:
        n = to_integer(digits)
    n = max(0, min(30, n))
    r = to_real(x)
    if math.isnan(r) or math.isinf(r):
        return r
    if r < -4503599627370496.0 or r > 4503599627370496.0:
        return r
    if n == 0:
        return float(int(r + (-0.5 if r < 0 else 0.5)))
    q = Decimal(r).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)
    return float(q)


def _substr(x, y, z=None, *, has_z=False):
    if x is None or y is None:
        return None
    s = to_text(x)
    length = len(s)
    p1 = to_integer(y)
    neg_p2 = False
    if has_z:
        if z is None:
            return None
        p2 = to_integer(z)
        if p2 < 0:
            neg_p2 = True
            p2 = -p2
    else:
        p2 = 1_000_000_000
    if p1 < 0:
        p1 += length
        if p1 < 0:
            p2 += p1
            if p2 < 0:
                p2 = 0
            p1 = 0
    elif p1 > 0:
        p1 -= 1
    elif p2 > 0:
        p2 -= 1
    if neg_p2:
        p1 -= p2
        if p1 < 0:
            p2 += p1
            p1 = 0
    return s[p1 : p1 + p2]


def _substr_dispatch(*args):
    if len(args) == 3:
        return _substr(args[0], args[1], args[2], has_z=True)
    return _substr(args[0], args[1])


def _trim_impl(mode: str):
    def trim(x, chars=" "):
        if x is None or chars is None:
            return None
        s = to_text(x)
        c = to_text(chars)
        if mode == "both":
            return s.strip(c)
        if mode == "left":
            return s.lstrip(c)
        return s.rstrip(c)

    return trim


def _replace(x, y, z):
    if x is None or y is None or z is None:
        return None
    s, old, new = to_text(x), to_text(y), to_text(z)
    if old == "":
        return s
    return s.replace(old, new)


def _instr(x, y):
    if x is None or y is None:
        return None
    return to_text(x).find(to_text(y)) + 1


# name -> (min_args, max_args or None for unbounded, fn)
SCALAR_FUNCTIONS: dict[str, tuple[int, int | None, Callable]] = {
    "ABS": (1, 1, _abs),
    "LENGTH": (1, 1, _length),
    "UPPER": (1, 1, _upper),
    "LOWER": (1, 1, _lower),
    "COALESCE": (2, None, _coalesce),
    "IFNULL": (2, 2, _coalesce),
    "NULLIF": (2, 2, _nullif),
    "TYPEOF": (1, 1, _typeof),
    "MIN": (2, None, _scalar_min),
    "MAX": (2, None, _scalar_max),
    "ROUND": (1, 2, _round),
    "SUBSTR": (2, 3, _substr_dispatch),
    "SUBSTRING": (2, 3, _substr_dispatch),
    "TRIM": (1, 2, _trim_impl("both")),
    "LTRIM": (1, 2, _trim_impl("left")),
    "RTRIM": (1, 2, _trim_impl("right")),
    "REPLACE": (3, 3, _replace),
    "INSTR": (2, 2, _instr),
}

# ---------------------------------------------------------------- aggregates

AGGREGATE_ARGS: dict[str, tuple[int, int]] = {
    "COUNT": (0, 1),
    "SUM": (1, 1),
    "TOTAL": (1, 1),
    "AVG": (1, 1),
    "MIN": (1, 1),
    "MAX": (1, 1),
    "GROUP_CONCAT": (1, 2),
}

_BIG = 4503599627370496


def _c_mod(a: int, b: int) -> int:
    r = abs(a) % abs(b)
    return -r if a < 0 else r


class _KBNSum:
    """Replicates SQLite's sum()/avg()/total() accumulator."""

    __slots__ = ("i_sum", "r_sum", "r_err", "approx", "ovrfl", "cnt")

    def __init__(self):
        self.i_sum = 0
        self.r_sum = 0.0
        self.r_err = 0.0
        self.approx = False
        self.ovrfl = False
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

    def add(self, value) -> None:
        if value is None:
            return
        v = value
        if isinstance(value, str):
            v = numeric_affinity(value)
            if isinstance(v, int) and any(c in value for c in ".eE"):
                v = float(v)
        is_int = isinstance(v, int)
        self.cnt += 1
        if not self.approx:
            if not is_int:
                self._init(self.i_sum)
                self.approx = True
                self._step(to_real(v))
            else:
                x = self.i_sum + v
                if -(1 << 63) <= x < (1 << 63):
                    self.i_sum = x
                else:
                    self.ovrfl = True
                    self._init(self.i_sum)
                    self.approx = True
                    self._step_int(v)
        else:
            if is_int:
                self._step_int(v)
            else:
                self.ovrfl = False
                self._step(to_real(v))

    def _real(self) -> float:
        r = self.r_sum
        if not (math.isinf(self.r_err) or math.isnan(self.r_err)):
            r += self.r_err
        return r

    def sum(self):
        if self.cnt == 0:
            return None
        if self.approx:
            if self.ovrfl:
                raise SQLError("integer overflow")
            return self._real()
        return self.i_sum

    def total(self) -> float:
        if self.cnt == 0:
            return 0.0
        return self._real() if self.approx else float(self.i_sum)

    def avg(self):
        if self.cnt == 0:
            return None
        r = self._real() if self.approx else float(self.i_sum)
        return r / self.cnt


def compute_aggregate(name: str, values: list, seps: list | None = None):
    """Compute aggregate ``name`` over already-evaluated argument values.

    Returns (result, index_of_selected_row_or_None) where the index is set for MIN/MAX.
    """
    if name == "COUNT":
        return sum(1 for v in values if v is not None), None
    if name in ("SUM", "TOTAL", "AVG"):
        acc = _KBNSum()
        for v in values:
            acc.add(v)
        if name == "SUM":
            return acc.sum(), None
        if name == "TOTAL":
            return acc.total(), None
        return acc.avg(), None
    if name in ("MIN", "MAX"):
        best = None
        best_idx = None
        want = -1 if name == "MIN" else 1
        for i, v in enumerate(values):
            if v is None:
                continue
            if best is None or compare(v, best) == want:
                best = v
                best_idx = i
        return best, best_idx
    if name == "GROUP_CONCAT":
        out: list[str] = []
        first = True
        for i, v in enumerate(values):
            if v is None:
                continue
            if not first:
                sep = "," if seps is None else seps[i]
                if sep is not None:
                    out.append(to_text(sep))
            out.append(to_text(v))
            first = False
        return ("".join(out) if not first else None), None
    raise SQLError(f"no such function: {name.lower()}")
