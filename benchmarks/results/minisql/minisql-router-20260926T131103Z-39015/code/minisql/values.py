"""Value semantics mirroring SQLite: affinity, conversion, comparison, arithmetic."""

from __future__ import annotations

import math
import re
from functools import cmp_to_key

Value = int | float | str | None

INT_MIN = -(2**63)
INT_MAX = 2**63 - 1

# Affinity names
INTEGER = "INTEGER"
REAL = "REAL"
TEXT = "TEXT"
NUMERIC = "NUMERIC"
BLOB = "BLOB"

_WELL_FORMED_NUM = re.compile(r"\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*\Z")
_NUM_PREFIX = re.compile(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))([eE][+-]?\d+)?")
_INT_PREFIX = re.compile(r"\s*[+-]?\d+")


def type_affinity(type_name: str) -> str:
    """Determine column affinity from a declared type name (SQLite rules)."""
    up = type_name.upper()
    if "INT" in up:
        return INTEGER
    if "CHAR" in up or "CLOB" in up or "TEXT" in up:
        return TEXT
    if "BLOB" in up or not up:
        return BLOB
    if "REAL" in up or "FLOA" in up or "DOUB" in up:
        return REAL
    return NUMERIC


def float_to_text(f: float) -> str:
    """Render a float the way SQLite does ("%!.15g")."""
    if math.isinf(f):
        return "Inf" if f > 0 else "-Inf"
    if f == 0:
        return "0.0"
    s = f"{f:.15g}"
    if "e" in s:
        mant, exp = s.split("e")
        if "." not in mant:
            mant += ".0"
        return f"{mant}e{exp}"
    if "." not in s:
        s += ".0"
    return s


def to_text(v: Value) -> str | None:
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, float):
        return float_to_text(v)
    return str(v)


def _real_as_int(f: float) -> int | None:
    """Return the int equal to f if f is integral and fits in 64 bits."""
    if math.isfinite(f) and -(2.0**63) <= f < 2.0**63 and f == int(f):
        return int(f)
    return None


def _parse_well_formed(s: str) -> int | float | None:
    """Convert well-formed numeric text to a number, or None if not numeric."""
    if not _WELL_FORMED_NUM.match(s):
        return None
    t = s.strip()
    if "." in t or "e" in t or "E" in t:
        return float(t)
    i = int(t)
    if INT_MIN <= i <= INT_MAX:
        return i
    return float(i)


def apply_affinity(v: Value, affinity: str) -> Value:
    """Apply column affinity for storage (INSERT/UPDATE)."""
    if v is None:
        return None
    if affinity in (INTEGER, NUMERIC):
        if isinstance(v, str):
            num = _parse_well_formed(v)
            if num is None:
                return v
            v = num
        if isinstance(v, float):
            as_int = _real_as_int(v)
            return v if as_int is None else as_int
        return v
    if affinity == REAL:
        if isinstance(v, str):
            num = _parse_well_formed(v)
            return v if num is None else float(num)
        if isinstance(v, int):
            return float(v)
        return v
    if affinity == TEXT:
        return to_text(v)
    return v


def numeric_affinity_for_compare(v: Value) -> Value:
    """Numeric affinity applied to an operand before comparison."""
    if isinstance(v, str):
        num = _parse_well_formed(v)
        return v if num is None else num
    return v


def to_numeric(v: Value) -> int | float | None:
    """Convert a value to a number the way SQLite does for arithmetic."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    m = _NUM_PREFIX.match(v)
    if not m:
        return 0
    mant, exp = m.group(1), m.group(2)
    if "." in mant or exp:
        try:
            return float(mant + (exp or ""))
        except OverflowError:  # pragma: no cover - float() returns inf instead
            return math.inf
    i = int(mant)
    if INT_MIN <= i <= INT_MAX:
        return i
    return float(i)


def to_real(v: Value) -> float | None:
    n = to_numeric(v)
    return None if n is None else float(n)


def to_int(v: Value) -> int | None:
    """CAST(v AS INTEGER) semantics."""
    if v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        m = _INT_PREFIX.match(v)
        if not m:
            return 0
        i = int(m.group(0))
        return max(INT_MIN, min(INT_MAX, i))
    if math.isnan(v):
        return 0
    if v >= 9.223372036854775807e18:
        return INT_MAX
    if v <= -9.223372036854775808e18:
        return INT_MIN
    return int(v)


def truth(v: Value) -> bool | None:
    """Three-valued truth of a value: None for NULL."""
    if v is None:
        return None
    if isinstance(v, str):
        v = to_numeric(v)
    return v != 0


def _rank(v: Value) -> int:
    if v is None:
        return 0
    if isinstance(v, str):
        return 2
    return 1


def compare(a: Value, b: Value) -> int:
    """Total ordering: NULL < numbers < text. Returns -1, 0 or 1."""
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if ra == 0:
        return 0
    if a < b:  # type: ignore[operator]
        return -1
    if a > b:  # type: ignore[operator]
        return 1
    return 0


sort_key = cmp_to_key(compare)


def value_key(v: Value) -> tuple:
    """Hashable key where NULLs are equal and 1 == 1.0 but 1 != '1'."""
    return (_rank(v), v)


def _int_result(r: int) -> int | float:
    if INT_MIN <= r <= INT_MAX:
        return r
    return float(r)


def _real_result(r: float) -> float | None:
    if math.isnan(r):
        return None
    return r


def arith(op: str, a: Value, b: Value) -> Value:
    if a is None or b is None:
        return None
    x = to_numeric(a)
    y = to_numeric(b)
    both_int = isinstance(x, int) and isinstance(y, int)
    if op == "+":
        if both_int:
            return _int_result(x + y)  # type: ignore[operator]
        return _real_result(float(x) + float(y))  # type: ignore[arg-type]
    if op == "-":
        if both_int:
            return _int_result(x - y)  # type: ignore[operator]
        return _real_result(float(x) - float(y))  # type: ignore[arg-type]
    if op == "*":
        if both_int:
            return _int_result(x * y)  # type: ignore[operator]
        try:
            return _real_result(float(x) * float(y))  # type: ignore[arg-type]
        except OverflowError:  # pragma: no cover
            return math.inf
    if op == "/":
        if both_int:
            if y == 0:
                return None
            q = abs(x) // abs(y)  # type: ignore[arg-type]
            if (x < 0) != (y < 0):  # type: ignore[operator]
                q = -q
            return _int_result(q)
        fy = float(y)  # type: ignore[arg-type]
        if fy == 0.0:
            return None
        try:
            return _real_result(float(x) / fy)  # type: ignore[arg-type]
        except OverflowError:  # pragma: no cover
            return math.inf
    if op == "%":
        ix = to_int(x)
        iy = to_int(y)
        if iy == 0:
            return None
        r = abs(ix) % abs(iy)  # type: ignore[arg-type]
        if ix < 0:  # type: ignore[operator]
            r = -r
        return r if both_int else float(r)
    raise ValueError(op)


def _to_i64(v: int) -> int:
    v &= 0xFFFFFFFFFFFFFFFF
    return v - 2**64 if v >= 2**63 else v


def bitwise(op: str, a: Value, b: Value) -> Value:
    if a is None or b is None:
        return None
    x = to_int(to_numeric(a))
    y = to_int(to_numeric(b))
    assert x is not None and y is not None
    if op == "&":
        return x & y
    if op == "|":
        return x | y
    if op in ("<<", ">>"):
        if op == ">>":
            y = -y
        if y >= 0:
            return 0 if y >= 64 else _to_i64(x << y)
        y = -y
        if y >= 64:
            return -1 if x < 0 else 0
        return x >> y
    raise ValueError(op)


def negate(v: Value) -> Value:
    if v is None:
        return None
    n = to_numeric(v)
    if isinstance(n, int):
        return float(-n) if n == INT_MIN else -n
    return -n  # type: ignore[operator]


def bit_not(v: Value) -> Value:
    if v is None:
        return None
    return ~to_int(to_numeric(v))  # type: ignore[operator]


def concat(a: Value, b: Value) -> Value:
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)  # type: ignore[operator]


_like_cache: dict[tuple[str, str | None], re.Pattern[str]] = {}


def like(value: Value, pattern: Value, escape: Value = None) -> int | None:
    if value is None or pattern is None:
        return None
    text = to_text(value)
    pat = to_text(pattern)
    esc = to_text(escape) if escape is not None else None
    key = (pat, esc)  # type: ignore[assignment]
    rx = _like_cache.get(key)  # type: ignore[arg-type]
    if rx is None:
        parts: list[str] = []
        i = 0
        assert pat is not None
        while i < len(pat):
            c = pat[i]
            if esc is not None and c == esc and i + 1 < len(pat):
                parts.append(re.escape(pat[i + 1]))
                i += 2
                continue
            if c == "%":
                parts.append(".*")
            elif c == "_":
                parts.append(".")
            else:
                parts.append(re.escape(c))
            i += 1
        rx = re.compile("".join(parts), re.DOTALL | re.IGNORECASE | re.ASCII)
        if len(_like_cache) > 1000:
            _like_cache.clear()
        _like_cache[key] = rx  # type: ignore[index]
    return 1 if rx.fullmatch(text) else 0  # type: ignore[arg-type]


def cast(v: Value, type_name: str) -> Value:
    if v is None:
        return None
    aff = type_affinity(type_name)
    if aff == INTEGER:
        if isinstance(v, str):
            return to_int(v)
        return to_int(v)
    if aff == REAL:
        return to_real(v)
    if aff == TEXT:
        return to_text(v)
    if aff == NUMERIC:
        n = to_numeric(v)
        if isinstance(n, float):
            as_int = _real_as_int(n)
            if as_int is not None:
                return as_int
        return n
    return v


def typeof(v: Value) -> str:
    if v is None:
        return "null"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "real"
    return "text"
