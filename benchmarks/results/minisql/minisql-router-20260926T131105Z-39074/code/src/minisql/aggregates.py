"""Aggregate function accumulators mirroring SQLite's implementations."""

from __future__ import annotations

import math

from .errors import SQLError
from .values import INT64_MAX, INT64_MIN, Value, compare, parse_full_number, to_real

_KBN_LIMIT = 4503599627370496  # 2**52: beyond this, split integers before adding as doubles


def _c_mod(a: int, b: int) -> int:
    r = abs(a) % abs(b)
    return -r if a < 0 else r


class Accumulator:
    def step(self, value: Value) -> None:
        raise NotImplementedError

    def finish(self) -> Value:
        raise NotImplementedError


class CountStar(Accumulator):
    def __init__(self) -> None:
        self.count = 0

    def step(self, value: Value) -> None:
        self.count += 1

    def finish(self) -> Value:
        return self.count


class Count(Accumulator):
    def __init__(self) -> None:
        self.count = 0

    def step(self, value: Value) -> None:
        if value is not None:
            self.count += 1

    def finish(self) -> Value:
        return self.count


class _MinMax(Accumulator):
    sign = 1

    def __init__(self) -> None:
        self.best: Value = None

    def step(self, value: Value) -> None:
        if value is None:
            return
        if self.best is None or compare(value, self.best) * self.sign > 0:
            self.best = value

    def finish(self) -> Value:
        return self.best


class Max(_MinMax):
    sign = 1


class Min(_MinMax):
    sign = -1


class Sum(Accumulator):
    """SUM(): exact integer sum until a non-integer appears, then Kahan-Babuska-Neumaier."""

    def __init__(self) -> None:
        self.count = 0
        self.int_sum = 0
        self.approx = False
        self.overflow = False
        self.r_sum = 0.0
        self.r_err = 0.0

    def _kbn_step(self, r: float) -> None:
        s = self.r_sum
        t = s + r
        if abs(s) > abs(r):
            self.r_err += (s - t) + r
        else:
            self.r_err += (r - t) + s
        self.r_sum = t

    def _kbn_step_int(self, value: int) -> None:
        if value <= -_KBN_LIMIT or value >= _KBN_LIMIT:
            small = _c_mod(value, 16384)
            self._kbn_step(float(value - small))
            self._kbn_step(float(small))
        else:
            self._kbn_step(float(value))

    def _kbn_init(self, value: int) -> None:
        if value <= -_KBN_LIMIT or value >= _KBN_LIMIT:
            small = _c_mod(value, 16384)
            self.r_sum = float(value - small)
            self.r_err = float(small)
        else:
            self.r_sum = float(value)
            self.r_err = 0.0
        self.approx = True

    def step(self, value: Value) -> None:
        if value is None:
            return
        integer: int | None = None
        if isinstance(value, int):
            integer = value
        elif isinstance(value, str):
            number = parse_full_number(value)
            if isinstance(number, int):
                integer = number
        self.count += 1
        if not self.approx:
            if integer is None:
                self._kbn_init(self.int_sum)
                self._kbn_step(to_real(value))
            elif INT64_MIN <= self.int_sum + integer <= INT64_MAX:
                self.int_sum += integer
            else:
                self.overflow = True
                self._kbn_init(self.int_sum)
                self._kbn_step_int(integer)
        elif integer is not None:
            self._kbn_step_int(integer)
        else:
            self.overflow = False
            self._kbn_step(to_real(value))

    def _real_total(self) -> float:
        if not self.approx:
            return float(self.int_sum)
        if math.isinf(self.r_err):
            return self.r_sum
        return self.r_sum + self.r_err

    def finish(self) -> Value:
        if self.count == 0:
            return None
        if not self.approx:
            return self.int_sum
        if self.overflow:
            raise SQLError("integer overflow")
        return self._real_total()


class Total(Sum):
    def finish(self) -> Value:
        return self._real_total() if self.count else 0.0


class Avg(Sum):
    def finish(self) -> Value:
        if self.count == 0:
            return None
        return self._real_total() / self.count


class Distinct(Accumulator):
    """Wraps an accumulator so that it only sees each distinct non-NULL value once."""

    def __init__(self, inner: Accumulator) -> None:
        self.inner = inner
        self.seen: set[Value] = set()

    def step(self, value: Value) -> None:
        if value is None or value in self.seen:
            return
        self.seen.add(value)
        self.inner.step(value)

    def finish(self) -> Value:
        return self.inner.finish()


AGGREGATES: dict[str, type[Accumulator]] = {
    "count": Count,
    "sum": Sum,
    "total": Total,
    "avg": Avg,
    "min": Min,
    "max": Max,
}


def make_accumulator(name: str, *, star: bool, distinct: bool) -> Accumulator:
    if star:
        return CountStar()
    accumulator = AGGREGATES[name]()
    return Distinct(accumulator) if distinct else accumulator
