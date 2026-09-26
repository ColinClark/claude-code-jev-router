"""Aggregate function accumulators."""

from __future__ import annotations

import math

from .errors import SQLError
from .values import INT_MAX, INT_MIN, sort_key, text_looks_numeric, text_to_numeric, to_text

AGGREGATES = frozenset({"COUNT", "SUM", "AVG", "MIN", "MAX", "TOTAL", "GROUP_CONCAT"})


class _Sum:
    """SQLite-compatible summation: exact integers, Kahan-Babuska-Neumaier for reals."""

    __slots__ = ("count", "i_sum", "r_sum", "r_err", "approx", "overflow")

    def __init__(self):
        self.count = 0
        self.overflow = False  # integer overflow not (yet) excused by a REAL input
        self.i_sum = 0
        self.r_sum = 0.0
        self.r_err = 0.0
        self.approx = False

    def _kbn(self, r: float):
        s = self.r_sum
        t = s + r
        if abs(s) > abs(r):
            self.r_err += (s - t) + r
        else:
            self.r_err += (r - t) + s
        self.r_sum = t

    def _go_approx(self):
        self.approx = True
        self.r_sum = float(self.i_sum)
        self.r_err = float(self.i_sum - int(self.r_sum)) if abs(self.i_sum) < 2**1000 else 0.0

    def add(self, v):
        self.count += 1
        if isinstance(v, str):
            # Well-formed integer text sums as INTEGER; anything else as REAL.
            n = text_to_numeric(v)
            v = n if isinstance(n, int) and text_looks_numeric(v) else float(n)
        if isinstance(v, int):
            if not self.approx:
                s = self.i_sum + v
                if INT_MIN <= s <= INT_MAX:
                    self.i_sum = s
                    return
                self.overflow = True
                self._go_approx()
        elif not self.approx:
            self._go_approx()
        else:
            self.overflow = False
        self._kbn(float(v))

    def real_value(self) -> float:
        if not self.approx:
            return float(self.i_sum)
        r = self.r_sum
        if math.isfinite(self.r_err):
            r += self.r_err
        return None if math.isnan(r) else r


class Aggregate:
    """Accumulator for one aggregate call within one group."""

    __slots__ = ("kind", "distinct", "seen", "state", "best", "best_row", "parts", "sep")

    def __init__(self, kind: str, distinct: bool):
        self.kind = kind
        self.distinct = distinct
        self.seen: set | None = set() if distinct else None
        self.state = _Sum() if kind in ("SUM", "AVG", "TOTAL") else 0
        self.best = None
        self.best_row = None
        self.parts: list[str] = []
        self.sep = ","

    def step(self, args: list, row):
        kind = self.kind
        if kind == "COUNT" and not args:  # COUNT(*)
            self.state += 1
            return
        v = args[0]
        if v is None:
            return
        if self.distinct:
            if v in self.seen:
                return
            self.seen.add(v)
        if kind == "COUNT":
            self.state += 1
        elif kind in ("SUM", "AVG", "TOTAL"):
            self.state.add(v)
        elif kind == "MIN":
            if self.best is None or sort_key(v) < sort_key(self.best):
                self.best, self.best_row = v, row
        elif kind == "MAX":
            if self.best is None or sort_key(v) > sort_key(self.best):
                self.best, self.best_row = v, row
        elif kind == "GROUP_CONCAT":
            if len(args) > 1:
                self.sep = to_text(args[1]) if args[1] is not None else ""
                if self.parts:
                    self.parts.append(self.sep)
            elif self.parts:
                self.parts.append(",")
            self.parts.append(to_text(v))

    def result(self):
        kind = self.kind
        if kind == "COUNT":
            return self.state
        if kind == "SUM":
            s = self.state
            if s.count == 0:
                return None
            if s.overflow:
                raise SQLError("integer overflow")
            return s.real_value() if s.approx else s.i_sum
        if kind == "TOTAL":
            return self.state.real_value()
        if kind == "AVG":
            s = self.state
            if s.count == 0:
                return None
            r = s.real_value()
            return None if r is None else r / s.count
        if kind in ("MIN", "MAX"):
            return self.best
        if kind == "GROUP_CONCAT":
            return "".join(self.parts) if self.parts else None
        raise AssertionError(kind)  # pragma: no cover
