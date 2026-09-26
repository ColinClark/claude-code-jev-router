"""SQLite value semantics: type affinity, conversions and comparison.

Values are plain Python objects: ``None`` (NULL), ``int`` (INTEGER, 64-bit),
``float`` (REAL) and ``str`` (TEXT).
"""

from __future__ import annotations

import math
import re

INTEGER = "INTEGER"
REAL = "REAL"
NUMERIC = "NUMERIC"
TEXT = "TEXT"
BLOB = "BLOB"  # also used for "no affinity"
NONE = None  # expression without affinity

MIN_INT64 = -(2**63)
MAX_INT64 = 2**63 - 1

_NUMERIC_PREFIX = re.compile(r"\s*([+-]?(?:\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?)")
_WELL_FORMED_NUMBER = re.compile(r"\s*[+-]?(?:\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\s*\Z")


def type_affinity(type_name: str) -> str:
    """Column affinity from a declared type name (SQLite section 3.1 rules)."""
    t = type_name.upper()
    if "INT" in t:
        return INTEGER
    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return TEXT
    if "BLOB" in t or not t:
        return BLOB
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return REAL
    return NUMERIC


def fits_int64(v: int) -> bool:
    return MIN_INT64 <= v <= MAX_INT64


def float_to_int_if_exact(f: float) -> int | float:
    if math.isfinite(f) and f == int(f) and -(2**63) <= f < 2**63:
        return int(f)
    return f


def text_to_number(s: str) -> int | float | None:
    """Convert a well-formed numeric string to a number, else None."""
    m = _WELL_FORMED_NUMBER.match(s)
    if not m:
        return None
    body = s.strip()
    if "." not in body and "e" not in body and "E" not in body:
        v = int(body)
        return v if fits_int64(v) else float(v)
    return float(body)


def to_numeric_prefix(s: str) -> int | float:
    """Numeric value of a string the way SQLite arithmetic sees it (prefix parse)."""
    m = _NUMERIC_PREFIX.match(s)
    if not m:
        return 0
    body = m.group(1)
    if "." not in body and "e" not in body and "E" not in body:
        v = int(body)
        return v if fits_int64(v) else float(v)
    return float(body)


def to_number(v: object) -> int | float | None:
    """Coerce a value to a number for arithmetic. NULL stays NULL."""
    if v is None or isinstance(v, (int, float)):
        return v  # type: ignore[return-value]
    if isinstance(v, str):
        return to_numeric_prefix(v)
    if isinstance(v, (bytes, bytearray)):
        return to_numeric_prefix(v.decode("utf-8", "replace"))
    raise TypeError(f"unsupported value {v!r}")


def float_to_text(f: float) -> str:
    if math.isnan(f):
        return "NaN"  # SQLite actually stores NULL for NaN
    if math.isinf(f):
        return "Inf" if f > 0 else "-Inf"
    s = f"{f:.15g}"
    if "e" in s:
        mant, exp = s.split("e")
        if "." not in mant:
            mant += ".0"
        sign = exp[0]
        digits = exp[1:].lstrip("0").rjust(2, "0")
        return f"{mant}e{sign}{digits}"
    if "." not in s and "inf" not in s and "nan" not in s:
        s += ".0"
    return s


def to_text(v: object) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return float_to_text(v)
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    raise TypeError(f"unsupported value {v!r}")


def is_true(v: object) -> bool | None:
    """SQL truth value: None for NULL, else whether the numeric value is non-zero."""
    if v is None:
        return None
    n = to_number(v)
    return n != 0


def apply_affinity(v: object, affinity: str | None) -> object:
    """Convert a value for storage in / comparison against a given affinity."""
    if v is None or affinity is None or affinity == BLOB:
        return v
    if affinity == TEXT:
        if isinstance(v, (int, float)):
            return to_text(v)
        return v
    # numeric affinities
    if isinstance(v, str):
        n = text_to_number(v)
        if n is None:
            return v
        v = n
    if affinity == REAL:
        if isinstance(v, int):
            return float(v)
        return v
    # INTEGER / NUMERIC
    if isinstance(v, float):
        return float_to_int_if_exact(v)
    return v


def apply_numeric_affinity_for_compare(v: object) -> object:
    """NUMERIC affinity applied to an operand of a comparison.

    Unlike storage, REAL values that happen to be integral are left alone
    (1.0 = 1 is true either way).
    """
    if isinstance(v, str):
        n = text_to_number(v)
        if n is not None:
            return n
    return v


def _type_rank(v: object) -> int:
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return 1
    if isinstance(v, str):
        return 2
    return 3


def compare_values(a: object, b: object) -> int:
    """Total ordering used by comparisons, ORDER BY, MIN/MAX, DISTINCT.

    NULL < numbers < text < blob; numbers compare numerically, text by binary
    (code point) comparison. Callers handle NULL propagation themselves when
    implementing SQL comparison operators.
    """
    ra, rb = _type_rank(a), _type_rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if ra == 0:
        return 0
    if a < b:  # type: ignore[operator]
        return -1
    if a > b:  # type: ignore[operator]
        return 1
    return 0


class SortKey:
    """Wrapper making values sortable with :func:`compare_values` semantics."""

    __slots__ = ("value",)

    def __init__(self, value: object):
        self.value = value

    def __lt__(self, other: SortKey) -> bool:
        return compare_values(self.value, other.value) < 0

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SortKey) and compare_values(self.value, other.value) == 0

    def __hash__(self) -> int:
        v = self.value
        if isinstance(v, float) and v.is_integer():
            return hash(int(v))
        return hash(v)
