"""Aggregate function evaluation with SQLite semantics."""

from __future__ import annotations

import math

from . import values as V
from .compiler import AggSpec
from .errors import SQLError

_BIG = 4503599627370496  # 2**52


class _Sum:
    """Mirror of SQLite's SumCtx, including Kahan-Babuska-Neumaier summation."""

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

    def _init(self, i: int) -> None:
        if i <= -_BIG or i >= _BIG:
            small = int(math.fmod(i, 16384))
            self.rsum = float(i - small)
            self.rerr = float(small)
        else:
            self.rsum = float(i)
            self.rerr = 0.0

    def step(self, v) -> None:
        if v is None:
            return
        v = V.numeric_affinity(v)
        self.cnt += 1
        if not self.approx:
            if type(v) is not int:
                self._init(self.isum)
                self.approx = True
                self._kbn(V.to_real(v))
            else:
                x = self.isum + v
                if V.INT64_MIN <= x <= V.INT64_MAX:
                    self.isum = x
                else:
                    self.overflow = True
                    self._init(self.isum)
                    self.approx = True
                    self._kbn_int(v)
        elif type(v) is int:
            self._kbn_int(v)
        else:
            self.overflow = False
            self._kbn(V.to_real(v))

    def _real(self) -> float:
        if math.isinf(self.rerr) or math.isnan(self.rerr):
            return self.rsum
        return self.rsum + self.rerr

    def sum(self):
        if self.cnt == 0:
            return None
        if self.approx:
            if self.overflow:
                raise SQLError("integer overflow")
            return _nan_to_null(self._real())
        return self.isum

    def total(self) -> float:
        if self.cnt == 0:
            return 0.0
        return _nan_to_null(self._real() if self.approx else float(self.isum))

    def avg(self):
        if self.cnt == 0:
            return None
        r = self._real() if self.approx else float(self.isum)
        return _nan_to_null(r / self.cnt)


def _nan_to_null(r: float):
    return None if math.isnan(r) else r


def evaluate(spec: AggSpec, rows: list[tuple]):
    """Compute one aggregate over the rows of a group."""
    if spec.arg is None:
        return len(rows)
    arg = spec.arg
    vals = [arg(r) for r in rows]
    if spec.distinct:
        seen = set()
        uniq = []
        for v in vals:
            if v is not None and v not in seen:
                seen.add(v)
                uniq.append(v)
        vals = uniq
    name = spec.name
    if name == "count":
        return sum(1 for v in vals if v is not None)
    if name in ("sum", "avg", "total"):
        acc = _Sum()
        for v in vals:
            acc.step(v)
        if name == "sum":
            return acc.sum()
        if name == "avg":
            return acc.avg()
        return acc.total()
    if name in ("min", "max"):
        sign = 1 if name == "max" else -1
        best = None
        for v in vals:
            if v is not None and (best is None or V.compare(v, best) * sign > 0):
                best = v
        return best
    raise SQLError(f"no such function: {name}")  # pragma: no cover


def representative_row(specs: list[AggSpec], rows: list[tuple]) -> tuple:
    """The source row that supplies bare (non-aggregated) columns for a group.

    Like SQLite: bare columns come from the first row of the group, unless the query uses
    min() or max(); then the last such aggregate decides, and bare columns come from the
    row where it first reached its final value.
    """
    extremes = [s for s in specs if s.name in ("min", "max")]
    if not extremes or extremes[-1].distinct:
        return rows[0]
    spec = extremes[-1]
    sign = 1 if spec.name == "max" else -1
    best = None
    rep = rows[0]
    for r in rows:
        v = spec.arg(r)
        if v is None:
            if best is None:
                rep = r
        elif best is None or V.compare(v, best) * sign > 0:
            best = v
            rep = r
    return rep
