"""Aggregate accumulators matching SQLite's count/sum/avg/total/min/max."""

from __future__ import annotations

import math

from .errors import SQLError
from .lexer import INT64_MAX, INT64_MIN
from .values import compare, parse_number, to_real

_BIG = 4503599627370496  # 2**52


def _c_mod(a: int, b: int) -> int:
    r = abs(a) % b
    return -r if a < 0 else r


class Count:
    __slots__ = ("n",)

    def __init__(self):
        self.n = 0

    def step(self, value) -> bool:
        if value is not None:
            self.n += 1
        return True

    def final(self):
        return self.n


class CountStar(Count):
    __slots__ = ()

    def step(self, value) -> bool:
        self.n += 1
        return True


class Sum:
    """SUM/AVG/TOTAL using SQLite's integer-then-Kahan-Babuska-Neumaier algorithm."""

    __slots__ = ("cnt", "isum", "rsum", "rerr", "approx", "overflow", "kind")

    def __init__(self, kind: str):
        self.kind = kind  # "SUM", "AVG" or "TOTAL"
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
        if v <= -_BIG or v >= _BIG:
            small = _c_mod(v, 16384)
            self._kbn(float(v - small))
            self._kbn(float(small))
        else:
            self._kbn(float(v))

    def _init_approx(self) -> None:
        v = self.isum
        if v <= -_BIG or v >= _BIG:
            small = _c_mod(v, 16384)
            self.rsum = float(v - small)
            self.rerr = float(small)
        else:
            self.rsum = float(v)
            self.rerr = 0.0
        self.approx = True

    def step(self, value) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            number = parse_number(value)
            value = number if isinstance(number, int) else to_real(value)
        self.cnt += 1
        if not self.approx:
            if isinstance(value, int):
                total = self.isum + value
                if INT64_MIN <= total <= INT64_MAX:
                    self.isum = total
                else:
                    self.overflow = True
                    self._init_approx()
                    self._kbn_int(value)
            else:
                self._init_approx()
                self._kbn(value)
        elif isinstance(value, int):
            self._kbn_int(value)
        else:
            self.overflow = False
            self._kbn(value)
        return True

    def _approx_value(self) -> float:
        if math.isinf(self.rerr) or math.isnan(self.rerr):
            return self.rsum
        return self.rsum + self.rerr

    def final(self):
        if self.kind == "SUM":
            if self.cnt == 0:
                return None
            if self.approx:
                if self.overflow:
                    raise SQLError("integer overflow")
                return _nan_to_none(self._approx_value())
            return self.isum
        if self.kind == "TOTAL":
            if self.cnt == 0:
                return 0.0
            return _nan_to_none(self._approx_value() if self.approx else float(self.isum))
        if self.cnt == 0:
            return None
        r = self._approx_value() if self.approx else float(self.isum)
        return _nan_to_none(r / self.cnt)


def _nan_to_none(value: float):
    return None if math.isnan(value) else value


class MinMax:
    __slots__ = ("best", "has_best", "sign")

    def __init__(self, is_max: bool):
        self.best = None
        self.has_best = False
        self.sign = 1 if is_max else -1

    def step(self, value) -> bool:
        """Returns True when this row "loads" the accumulator (drives bare columns)."""
        if value is None:
            return not self.has_best
        if not self.has_best or compare(value, self.best) * self.sign > 0:
            self.best = value
            self.has_best = True
            return True
        return False

    def final(self):
        return self.best


class Distinct:
    __slots__ = ("inner", "seen")

    def __init__(self, inner):
        self.inner = inner
        self.seen = set()

    def step(self, value) -> bool | None:
        """Like the inner step; returns None when a duplicate value skips the step."""
        if value is None:
            return self.inner.step(value)
        if value in self.seen:
            return None
        self.seen.add(value)
        return self.inner.step(value)

    def final(self):
        return self.inner.final()


AGGREGATE_NAMES = frozenset({"COUNT", "SUM", "AVG", "TOTAL", "MIN", "MAX"})


def is_aggregate_call(name: str, nargs: int, star: bool) -> bool:
    if name in ("MIN", "MAX"):
        return nargs == 1
    return name in AGGREGATE_NAMES


def make_accumulator(name: str, star: bool, distinct: bool):
    if name == "COUNT":
        acc = CountStar() if star else Count()
    elif name in ("SUM", "AVG", "TOTAL"):
        acc = Sum(name)
    elif name == "MIN":
        acc = MinMax(False)
    else:
        acc = MinMax(True)
    return Distinct(acc) if distinct else acc
