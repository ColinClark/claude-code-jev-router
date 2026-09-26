"""SQLite value semantics: affinity, conversions, comparison, arithmetic and LIKE.

Values are plain Python objects: ``int``, ``float``, ``str`` or ``None`` (NULL).
Booleans produced by SQL operators are always the integers ``1`` and ``0``.
"""

from __future__ import annotations

import math
import re
from enum import Enum
from functools import lru_cache

Value = int | float | str | None
Number = int | float

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


class Affinity(Enum):
    INTEGER = "INTEGER"
    REAL = "REAL"
    NUMERIC = "NUMERIC"
    TEXT = "TEXT"
    BLOB = "BLOB"  # a.k.a. "no affinity"


NUMERIC_AFFINITIES = frozenset({Affinity.INTEGER, Affinity.REAL, Affinity.NUMERIC})


def affinity_for_type(type_name: str) -> Affinity:
    """Determine column affinity from a declared type name (SQLite section 3.1 rules)."""
    name = type_name.upper()
    if "INT" in name:
        return Affinity.INTEGER
    if "CHAR" in name or "CLOB" in name or "TEXT" in name:
        return Affinity.TEXT
    if "BLOB" in name or not name:
        return Affinity.BLOB
    if "REAL" in name or "FLOA" in name or "DOUB" in name:
        return Affinity.REAL
    return Affinity.NUMERIC


# ----------------------------------------------------------------- conversions

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_FULL_NUMBER_RE = re.compile(rf"\s*({_NUMBER})\s*\Z")
_PREFIX_NUMBER_RE = re.compile(rf"\s*({_NUMBER})")


def _parse_number(text: str) -> Number:
    if "." in text or "e" in text or "E" in text:
        return float(text)
    value = int(text)
    if INT64_MIN <= value <= INT64_MAX:
        return value
    return float(value)


def _real_to_int_if_exact(value: float) -> Number:
    if value.is_integer() and INT64_MIN <= value < 2.0**63:
        return int(value)
    return value


def parse_full_number(text: str) -> Number | None:
    """Parse text that is entirely a number (surrounding whitespace allowed)."""
    match = _FULL_NUMBER_RE.match(text)
    return _parse_number(match.group(1)) if match else None


def to_numeric(value: Value) -> Number | None:
    """Convert a value for use in arithmetic (text uses its longest numeric prefix)."""
    if value is None or isinstance(value, (int, float)):
        return value
    match = _PREFIX_NUMBER_RE.match(value)
    return _parse_number(match.group(1)) if match else 0


def to_real(value: Value) -> float:
    number = to_numeric(value)
    return 0.0 if number is None else float(number)


def to_int(value: Value) -> int:
    """Convert to a 64-bit integer the way ``sqlite3_value_int64`` does."""
    number = to_numeric(value)
    if number is None:
        return 0
    if isinstance(number, float):
        if math.isnan(number):
            return 0
        if number >= 2.0**63:
            return INT64_MAX
        if number <= -(2.0**63):
            return INT64_MIN
        return int(number)
    return number


def format_real(value: float) -> str:
    """Render a REAL the way SQLite converts it to TEXT.

    SQLite uses ``printf("%!.15g")``: 15 significant digits, and the ``!`` flag keeps at
    least one digit after the decimal point (2.0 -> '2.0', 1e20 -> '1.0e+20').
    """
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Inf" if value > 0 else "-Inf"
    if value == 0:
        return "0.0"
    text = f"{value:.15g}"
    mantissa, sep, exponent = text.partition("e")
    if "." not in mantissa:
        mantissa += ".0"
    return mantissa + sep + exponent


def to_text(value: Value) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, float):
        return format_real(value)
    return str(value)


def truth(value: Value) -> bool | None:
    """SQL truth value: None for NULL, otherwise whether the numeric value is non-zero."""
    if value is None:
        return None
    return to_numeric(value) != 0


def from_bool(flag: bool | None) -> int | None:
    return None if flag is None else int(flag)


def apply_affinity(value: Value, affinity: Affinity) -> Value:
    """Convert a value being stored into a column with the given affinity."""
    if value is None or affinity is Affinity.BLOB:
        return value
    if affinity is Affinity.TEXT:
        return to_text(value)
    if isinstance(value, str):
        number = parse_full_number(value)
        if number is None:
            return value
        value = number
    if affinity is Affinity.REAL:
        return float(value)
    if isinstance(value, float):
        return _real_to_int_if_exact(value)
    return value


def numeric_affinity_for_compare(value: Value) -> Value:
    if isinstance(value, str):
        number = parse_full_number(value)
        if number is not None:
            return number
    return value


# ------------------------------------------------------------------ comparison


def type_rank(value: Value) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return 1
    return 2


def compare(a: Value, b: Value) -> int:
    """Total order used by ORDER BY, MIN/MAX: NULL < numbers < text."""
    ra, rb = type_rank(a), type_rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if ra == 0 or a == b:
        return 0
    return -1 if a < b else 1  # type: ignore[operator]


def sort_key(value: Value) -> tuple[int, Value]:
    return (type_rank(value), 0 if value is None else value)


def comparison_affinity(a_aff: Affinity | None, b_aff: Affinity | None) -> Affinity | None:
    """Affinity used to compare two operands (``None`` = expression with no affinity).

    Mirrors ``sqlite3CompareAffinity``: two column operands compare numerically if either
    is numeric and without conversion otherwise; if only one operand has an affinity, it
    is applied to both.
    """
    if a_aff is not None and b_aff is not None:
        if a_aff in NUMERIC_AFFINITIES or b_aff in NUMERIC_AFFINITIES:
            return Affinity.NUMERIC
        return None
    affinity = a_aff if a_aff is not None else b_aff
    return None if affinity is Affinity.BLOB else affinity


def coerce_for_comparison(
    a: Value, a_aff: Affinity | None, b: Value, b_aff: Affinity | None
) -> tuple[Value, Value]:
    """Apply SQLite's comparison affinity rules (section 4.2 of the datatype docs)."""
    affinity = comparison_affinity(a_aff, b_aff)
    if affinity in NUMERIC_AFFINITIES:
        return numeric_affinity_for_compare(a), numeric_affinity_for_compare(b)
    if affinity is Affinity.TEXT:
        return to_text(a), to_text(b)
    return a, b


_COMPARISONS = {
    "=": lambda c: c == 0,
    "!=": lambda c: c != 0,
    "<": lambda c: c < 0,
    "<=": lambda c: c <= 0,
    ">": lambda c: c > 0,
    ">=": lambda c: c >= 0,
}


def compare_op(
    op: str, a: Value, b: Value, a_aff: Affinity | None = None, b_aff: Affinity | None = None
) -> int | None:
    if a is None or b is None:
        return None
    a, b = coerce_for_comparison(a, a_aff, b, b_aff)
    return int(_COMPARISONS[op](compare(a, b)))


def is_op(a: Value, b: Value, a_aff: Affinity | None = None, b_aff: Affinity | None = None) -> int:
    """``a IS b``: equality where NULL IS NULL is true."""
    if a is None or b is None:
        return int(a is None and b is None)
    a, b = coerce_for_comparison(a, a_aff, b, b_aff)
    return int(compare(a, b) == 0)


# ------------------------------------------------------------------ arithmetic


def _c_mod(a: int, b: int) -> int:
    """Remainder with the sign of the dividend (C semantics)."""
    r = abs(a) % abs(b)
    return -r if a < 0 else r


def _checked_int(result: int, fallback: float) -> Number:
    return result if INT64_MIN <= result <= INT64_MAX else fallback


def arithmetic(op: str, a: Value, b: Value) -> Number | None:
    if a is None or b is None:
        return None
    x = to_numeric(a)
    y = to_numeric(b)
    assert x is not None and y is not None
    both_int = isinstance(x, int) and isinstance(y, int)
    if op == "%":
        ix, iy = to_int(x), to_int(y)
        if iy == 0:
            return None
        result = _c_mod(ix, iy)
        return result if both_int else float(result)
    if op == "/":
        if y == 0:
            return None
        if both_int:
            quotient = abs(x) // abs(y)  # type: ignore[operator]
            if (x < 0) != (y < 0):
                quotient = -quotient
            return _checked_int(quotient, float(x) / float(y))
        return float(x) / float(y)
    if op == "+":
        return _checked_int(x + y, float(x) + float(y)) if both_int else float(x) + float(y)
    if op == "-":
        return _checked_int(x - y, float(x) - float(y)) if both_int else float(x) - float(y)
    if op == "*":
        return _checked_int(x * y, float(x) * float(y)) if both_int else float(x) * float(y)
    raise ValueError(f"unknown arithmetic operator {op}")


def negate(value: Value) -> Number | None:
    number = to_numeric(value)
    if number is None:
        return None
    if isinstance(number, int):
        return _checked_int(-number, -float(number))
    return -number


def concat(a: Value, b: Value) -> str | None:
    if a is None or b is None:
        return None
    return f"{to_text(a)}{to_text(b)}"


# ------------------------------------------------------------------------ LIKE

_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


@lru_cache(maxsize=256)
def _like_regex(pattern: str) -> re.Pattern[str]:
    parts = []
    for ch in pattern.translate(_ASCII_LOWER):
        if ch == "%":
            parts.append(".*")
        elif ch == "_":
            parts.append(".")
        else:
            parts.append(re.escape(ch))
    return re.compile("".join(parts), re.DOTALL)


def like(value: Value, pattern: Value) -> int | None:
    """SQLite LIKE: ASCII case-insensitive, ``%`` and ``_`` wildcards, no escape."""
    if value is None or pattern is None:
        return None
    text = to_text(value)
    assert text is not None
    regex = _like_regex(to_text(pattern))  # type: ignore[arg-type]
    return int(regex.fullmatch(text.translate(_ASCII_LOWER)) is not None)
