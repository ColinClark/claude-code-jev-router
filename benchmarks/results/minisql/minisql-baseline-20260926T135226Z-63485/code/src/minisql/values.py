"""SQLite-compatible value semantics: affinity, conversions, arithmetic and ordering."""

from __future__ import annotations

import math
import re

from .errors import SQLError
from .lexer import INT64_MAX, INT64_MIN

# Affinities.
INTEGER = "INTEGER"
REAL = "REAL"
TEXT = "TEXT"
NUMERIC = "NUMERIC"
BLOB = "BLOB"
NONE = None  # expression without affinity

_FULL_NUMBER = re.compile(r"[ \t\n\f\r]*([+-]?(?:\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?)[ \t\n\f\r]*\Z")
_PREFIX_INTEGER = re.compile(r"[ \t\n\f\r]*([+-]?\d+)")
_PREFIX_NUMBER = re.compile(r"[ \t\n\f\r]*([+-]?(?:\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?)")


def type_affinity(type_name: str) -> str:
    """Column affinity from a declared type name (SQLite rules, section 3.1)."""
    upper = type_name.upper()
    if "INT" in upper:
        return INTEGER
    if "CHAR" in upper or "CLOB" in upper or "TEXT" in upper:
        return TEXT
    if "BLOB" in upper or not upper:
        return BLOB
    if "REAL" in upper or "FLOA" in upper or "DOUB" in upper:
        return REAL
    return NUMERIC


def _int_or_float(text: str, is_int: bool) -> int | float:
    if is_int:
        value = int(text)
        if INT64_MIN <= value <= INT64_MAX:
            return value
    return float(text)


def parse_number(text: str) -> int | float | None:
    """Parse text that is entirely a well-formed number (surrounding space allowed)."""
    m = _FULL_NUMBER.match(text)
    if not m:
        return None
    return _int_or_float(m.group(1), m.group(2) is None and m.group(3) is None)


def to_number(value):
    """Numeric value of an operand as used by arithmetic (text uses its longest numeric prefix)."""
    if value is None or isinstance(value, (int, float)):
        return value
    m = _PREFIX_NUMBER.match(value)
    if not m:
        return 0
    return _int_or_float(m.group(1), m.group(2) is None and m.group(3) is None)


def to_real(value) -> float:
    number = to_number(value)
    return float(number)


def to_integer(value) -> int:
    """CAST(value AS INTEGER) for a non-NULL value."""
    if isinstance(value, str):
        m = _PREFIX_INTEGER.match(value)
        if not m:
            return 0
        return max(INT64_MIN, min(INT64_MAX, int(m.group(1))))
    number = to_number(value)
    if isinstance(number, float):
        return float_to_int(number)
    return number


def float_to_int(value: float) -> int:
    if math.isnan(value):
        return 0
    if value >= 9.223372036854775807e18:
        return INT64_MAX
    if value <= -9.223372036854775808e18:
        return INT64_MIN
    return int(value)


def format_real(value: float) -> str:
    """Render a REAL the way SQLite does when converting it to TEXT (printf "%!.15g")."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Inf" if value > 0 else "-Inf"
    if value == 0:
        return "0.0"
    text = f"{value:.15g}"
    if "e" in text:
        mantissa, exponent = text.split("e")
        if "." not in mantissa:
            mantissa += ".0"
        return f"{mantissa}e{exponent}"
    if "." not in text:
        text += ".0"
    return text


def to_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        return format_real(value)
    return str(value)


def apply_affinity(value, affinity):
    """Convert a value for storage in (or comparison against) a column of the given affinity."""
    if value is None or affinity is None or affinity == BLOB:
        return value
    if affinity == TEXT:
        return value if isinstance(value, str) else to_text(value)
    if affinity == REAL:
        if isinstance(value, str):
            number = parse_number(value)
            return value if number is None else float(number)
        return float(value)
    # INTEGER / NUMERIC
    if isinstance(value, str):
        number = parse_number(value)
        if number is None:
            return value
        value = number
    if isinstance(value, float) and value.is_integer() and -(2.0**63) <= value < 2.0**63:
        return int(value)
    return value


def comparison_affinity(left_aff, right_aff):
    """Affinity applied to both operands of a comparison (sqlite3CompareAffinity)."""
    if left_aff is not None and right_aff is not None:
        if left_aff in (INTEGER, REAL, NUMERIC) or right_aff in (INTEGER, REAL, NUMERIC):
            return NUMERIC
        return None
    return left_aff if left_aff is not None else right_aff


def truth(value):
    """Three-valued truth of a value: True, False or None (NULL)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = to_number(value)
    return value != 0


# ------------------------------------------------------------------ ordering


def sort_key(value):
    """Key implementing SQLite's cross-type order: NULL < numbers < text."""
    if value is None:
        return (0, 0)
    if isinstance(value, str):
        return (2, value)
    return (1, value)


def compare(a, b) -> int:
    """Compare two non-NULL values; returns -1, 0 or 1."""
    ka = sort_key(a)
    kb = sort_key(b)
    return (ka > kb) - (ka < kb)


# --------------------------------------------------------------- arithmetic


def _fix_int(value: int, a, b, op):
    if INT64_MIN <= value <= INT64_MAX:
        return value
    return _real(op(float(a), float(b)))


def _real(value: float):
    return None if math.isnan(value) else value


def add(a, b):
    if a is None or b is None:
        return None
    a, b = to_number(a), to_number(b)
    if isinstance(a, int) and isinstance(b, int):
        return _fix_int(a + b, a, b, float.__add__)
    return _real(a + b)


def subtract(a, b):
    if a is None or b is None:
        return None
    a, b = to_number(a), to_number(b)
    if isinstance(a, int) and isinstance(b, int):
        return _fix_int(a - b, a, b, float.__sub__)
    return _real(a - b)


def multiply(a, b):
    if a is None or b is None:
        return None
    a, b = to_number(a), to_number(b)
    if isinstance(a, int) and isinstance(b, int):
        return _fix_int(a * b, a, b, float.__mul__)
    return _real(a * b)


def divide(a, b):
    if a is None or b is None:
        return None
    a, b = to_number(a), to_number(b)
    if isinstance(a, int) and isinstance(b, int):
        if b == 0:
            return None
        if a == INT64_MIN and b == -1:
            return float(a) / -1.0
        q = abs(a) // abs(b)
        return q if (a < 0) == (b < 0) else -q
    if b == 0:
        return None
    return _real(a / b)


def remainder(a, b):
    if a is None or b is None:
        return None
    na, nb = to_number(a), to_number(b)
    is_real = isinstance(na, float) or isinstance(nb, float)
    # Operands are converted like CAST(x AS INTEGER): text uses its integer prefix.
    ia = to_integer(a) if is_real else na
    ib = to_integer(b) if is_real else nb
    if ib == 0:
        return None
    if ib == -1:
        ib = 1
    r = abs(ia) % abs(ib)
    if ia < 0:
        r = -r
    return float(r) if is_real else r


def negate(a):
    if a is None:
        return None
    a = to_number(a)
    if isinstance(a, int):
        return float(-a) if a == INT64_MIN else -a
    return -a


def concat(a, b):
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)


# ------------------------------------------------------------------- LIKE

_like_cache: dict[tuple[str, str | None], re.Pattern] = {}


def like(value, pattern, escape=None):
    if value is None or pattern is None:
        return None
    value = to_text(value)
    pattern = to_text(pattern)
    if escape is not None:
        escape = to_text(escape)
        if len(escape) != 1:
            raise SQLError("ESCAPE expression must be a single character")
    key = (pattern, escape)
    regex = _like_cache.get(key)
    if regex is None:
        parts = []
        i = 0
        while i < len(pattern):
            ch = pattern[i]
            if escape is not None and ch == escape and i + 1 < len(pattern):
                parts.append(re.escape(pattern[i + 1]))
                i += 2
                continue
            if ch == "%":
                parts.append(".*")
            elif ch == "_":
                parts.append(".")
            else:
                parts.append(re.escape(ch))
            i += 1
        regex = re.compile("".join(parts), re.IGNORECASE | re.ASCII | re.DOTALL)
        if len(_like_cache) > 1000:
            _like_cache.clear()
        _like_cache[key] = regex
    return 1 if regex.fullmatch(value) else 0


def typeof(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return "text"
    if isinstance(value, float):
        return "real"
    return "integer"
