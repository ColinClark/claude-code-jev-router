"""Aggregate function accumulators, following SQLite's func.c."""

from __future__ import annotations

import math
from typing import Any

from . import ast
from .errors import SQLError
from .values import (
    INT_MAX,
    INT_MIN,
    compare,
    sort_key,
    text_to_number_prefix,
    text_to_number_strict,
)

AGGREGATES = frozenset({"count", "sum", "total", "avg", "min", "max"})


class Accumulator:
    def __init__(self, distinct: bool):
        self.seen: set | None = set() if distinct else None

    def step(self, args: list[Any]) -> bool:
        """Feed one row. Returns False if a min()/max() accumulator did not take the row's
        value, which is what decides where bare columns come from."""
        value = args[0]
        if value is None:
            return self.accept_null()
        if self.seen is not None:
            key = sort_key(value)
            if key in self.seen:
                return True
            self.seen.add(key)
        return self.add(value)

    def accept_null(self) -> bool:
        return True

    def add(self, value: Any) -> bool:
        raise NotImplementedError

    def final(self) -> Any:
        raise NotImplementedError


class CountStar(Accumulator):
    def __init__(self) -> None:
        super().__init__(False)
        self.n = 0

    def step(self, args: list[Any]) -> bool:
        self.n += 1
        return True

    def final(self) -> Any:
        return self.n


class Count(Accumulator):
    def __init__(self, distinct: bool):
        super().__init__(distinct)
        self.n = 0

    def add(self, value: Any) -> bool:
        self.n += 1
        return True

    def final(self) -> Any:
        return self.n


def _split_int(value: int) -> tuple[float, float] | None:
    """Split a large integer into two exactly-representable doubles (SQLite's KBN init)."""
    if -4503599627370496 < value < 4503599627370496:
        return None
    rem = abs(value) % 16384
    rem = rem if value >= 0 else -rem
    big = value - rem
    return float(big), float(rem)


class Sum(Accumulator):
    """sum(), total() and avg() share SQLite's Kahan-Babuska-Neumaier summation."""

    def __init__(self, kind: str, distinct: bool):
        super().__init__(distinct)
        self.kind = kind
        self.count = 0
        self.int_sum = 0
        self.approx = False
        self.overflow = False
        self.r_sum = 0.0
        self.r_err = 0.0

    def _kbn(self, r: float) -> None:
        s = self.r_sum
        t = s + r
        if abs(s) > abs(r):
            self.r_err += (s - t) + r
        else:
            self.r_err += (r - t) + s
        self.r_sum = t

    def _kbn_int(self, value: int) -> None:
        parts = _split_int(value)
        if parts is None:
            self._kbn(float(value))
        else:
            self._kbn(parts[0])
            self._kbn(parts[1])

    def _kbn_init(self, value: int) -> None:
        parts = _split_int(value)
        if parts is None:
            self.r_sum, self.r_err = float(value), 0.0
        else:
            self.r_sum, self.r_err = parts

    def add(self, value: Any) -> bool:
        self.count += 1
        if isinstance(value, str):
            strict = text_to_number_strict(value)
            if isinstance(strict, int):
                value = strict
            else:
                value = float(text_to_number_prefix(value))
        if not self.approx:
            if not isinstance(value, int):
                self._kbn_init(self.int_sum)
                self.approx = True
                self._kbn(value)
            else:
                total = self.int_sum + value
                if INT_MIN <= total <= INT_MAX:
                    self.int_sum = total
                else:
                    self.overflow = True
                    self._kbn_init(self.int_sum)
                    self.approx = True
                    self._kbn_int(value)
        elif isinstance(value, int):
            self._kbn_int(value)
        else:
            self.overflow = False
            self._kbn(value)
        return True

    def _real(self) -> float:
        if math.isinf(self.r_err) or math.isnan(self.r_err):
            return self.r_sum
        return self.r_sum + self.r_err

    def final(self) -> Any:
        if self.kind == "sum":
            if self.count == 0:
                return None
            if self.approx:
                if self.overflow:
                    raise SQLError("integer overflow")
                return self._real()
            return self.int_sum
        if self.kind == "total":
            return self._real() if self.approx else float(self.int_sum)
        if self.count == 0:
            return None
        total = self._real() if self.approx else float(self.int_sum)
        return total / self.count


class MinMax(Accumulator):
    def __init__(self, is_max: bool, distinct: bool):
        super().__init__(distinct)
        self.is_max = is_max
        self.best: Any = None

    def accept_null(self) -> bool:
        return self.best is None

    def add(self, value: Any) -> bool:
        if self.best is None:
            self.best = value
            return True
        c = compare(value, self.best)
        if (c > 0) if self.is_max else (c < 0):
            self.best = value
            return True
        return False

    def final(self) -> Any:
        return self.best


def make_accumulator(func: ast.Func) -> Accumulator:
    name, nargs = func.name, len(func.args)
    if func.star:
        if name != "count":
            raise SQLError(f"wrong number of arguments to function {name}()")
        return CountStar()
    if name == "count" and nargs == 0:
        return CountStar()
    if nargs != 1:
        raise SQLError(f"wrong number of arguments to function {name}()")
    if name == "count":
        return Count(func.distinct)
    if name in ("sum", "total", "avg"):
        return Sum(name, func.distinct)
    return MinMax(name == "max", func.distinct)
