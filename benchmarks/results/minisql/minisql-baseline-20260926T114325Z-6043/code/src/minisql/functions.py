"""Scalar SQL functions (a small subset of SQLite's built-ins)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import SQLError
from .values import INT_MIN, compare, text_to_number_prefix, to_text


def _abs(x: Any) -> Any:
    if x is None:
        return None
    if isinstance(x, int):
        if x == INT_MIN:
            raise SQLError("integer overflow")
        return abs(x)
    if isinstance(x, float):
        return abs(x)
    return abs(float(text_to_number_prefix(x)))


def _coalesce(*args: Any) -> Any:
    for a in args:
        if a is not None:
            return a
    return None


def _nullif(a: Any, b: Any) -> Any:
    if a is not None and b is not None and compare(a, b) == 0:
        return None
    return a


def _length(x: Any) -> Any:
    return None if x is None else len(to_text(x))


def _ascii_case(convert: Callable[[str], str]) -> Callable[[Any], Any]:
    def fn(x: Any) -> Any:
        if x is None:
            return None
        return "".join(convert(c) if c.isascii() else c for c in to_text(x))

    return fn


def _typeof(x: Any) -> str:
    if x is None:
        return "null"
    if isinstance(x, int):
        return "integer"
    if isinstance(x, float):
        return "real"
    return "text"


def _extreme(want: Callable[[int], bool]) -> Callable[..., Any]:
    def fn(*args: Any) -> Any:
        best = None
        for a in args:
            if a is None:
                return None
            if best is None or want(compare(a, best)):
                best = a
        return best

    return fn


# name -> (implementation, min args, max args)
SCALAR_FUNCTIONS: dict[str, tuple[Callable[..., Any], int, int]] = {
    "abs": (_abs, 1, 1),
    "coalesce": (_coalesce, 2, 1 << 30),
    "ifnull": (_coalesce, 2, 2),
    "nullif": (_nullif, 2, 2),
    "length": (_length, 1, 1),
    "lower": (_ascii_case(str.lower), 1, 1),
    "upper": (_ascii_case(str.upper), 1, 1),
    "typeof": (_typeof, 1, 1),
    "min": (_extreme(lambda c: c < 0), 2, 1 << 30),
    "max": (_extreme(lambda c: c > 0), 2, 1 << 30),
}
