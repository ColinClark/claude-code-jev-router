"""Value semantics modelled on SQLite: affinity, conversion, comparison and arithmetic."""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal

from .errors import SQLError

INT_MIN = -(2**63)
INT_MAX = 2**63 - 1

# Type affinities (SQLite datatype3 section 3).
INTEGER = "INTEGER"
REAL = "REAL"
TEXT = "TEXT"
NUMERIC = "NUMERIC"
BLOB = "BLOB"  # also used for "no affinity"

NUMERIC_AFFINITIES = (INTEGER, REAL, NUMERIC)


def affinity_of_type(type_name: str) -> str:
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


# ---------------------------------------------------------------- text <-> number

_FIFTEEN_DIGITS = Decimal("1.00000000000000")
_FULL_NUMBER = re.compile(r"\s*([+-]?(?:\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?)\s*\Z")
_PREFIX_NUMBER = re.compile(r"\s*([+-]?(?:\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?)")


def _number_from_match(m: re.Match[str]) -> int | float:
    text = m.group(1)
    if "." not in text and m.group(3) is None:
        value = int(text)
        if INT_MIN <= value <= INT_MAX:
            return value
    return float(text)


def text_to_number_strict(text: str) -> int | float | None:
    """Convert text that is entirely a well-formed number; otherwise None."""
    m = _FULL_NUMBER.match(text)
    if m is None:
        return None
    return _number_from_match(m)


def text_to_number_prefix(text: str) -> int | float:
    """Convert the longest numeric prefix of text (as SQLite does for arithmetic)."""
    m = _PREFIX_NUMBER.match(text)
    if m is None:
        return 0
    return _number_from_match(m)


def to_number(value: object) -> int | float:
    if isinstance(value, str):
        return text_to_number_prefix(value)
    return value  # type: ignore[return-value]


def format_real(v: float) -> str:
    """Render a float as SQLite's "%!.15g" does: 15 significant digits, rounded half-up."""
    if math.isinf(v):
        return "Inf" if v > 0 else "-Inf"
    if math.isnan(v):
        return "NaN"
    if v == 0:
        return "0.0"
    exact = Decimal(v)
    exp = exact.adjusted()
    scaled = exact.scaleb(-exp).quantize(_FIFTEEN_DIGITS, rounding=ROUND_HALF_UP)
    if abs(scaled) >= 10:
        exp += 1
        scaled = exact.scaleb(-exp).quantize(_FIFTEEN_DIGITS, rounding=ROUND_HALF_UP)
    digits = str(abs(scaled)).replace(".", "").rstrip("0") or "0"
    if exp < -4 or exp >= 15:
        sign = "-" if exp < 0 else "+"
        out = f"{digits[0]}.{digits[1:] or '0'}e{sign}{abs(exp):02d}"
    elif exp < 0:
        out = "0." + "0" * (-exp - 1) + digits
    else:
        out = digits[: exp + 1].ljust(exp + 1, "0") + "." + (digits[exp + 1 :] or "0")
    return "-" + out if v < 0 else out


def to_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        return format_real(value)
    return str(value)


def _real_to_int_if_exact(v: float) -> int | float:
    if v.is_integer() and -(2.0**63) <= v < 2.0**63:
        return int(v)
    return v


def apply_numeric_affinity(value: object) -> object:
    """Numeric affinity as used in comparisons: convert well-formed numeric text."""
    if isinstance(value, str):
        num = text_to_number_strict(value)
        if num is not None:
            return num
    return value


def apply_text_affinity(value: object) -> object:
    if isinstance(value, (int, float)):
        return to_text(value)
    return value


def coerce_for_storage(value: object, affinity: str) -> object:
    """Apply a column's affinity to a value being stored."""
    if value is None:
        return None
    if isinstance(value, float) and value == 0:
        value = 0.0  # stored records do not preserve negative zero
    if affinity in (INTEGER, NUMERIC):
        if isinstance(value, str):
            num = text_to_number_strict(value)
            if num is None:
                return value
            value = num
        if isinstance(value, float):
            return _real_to_int_if_exact(value)
        return value
    if affinity == REAL:
        if isinstance(value, str):
            num = text_to_number_strict(value)
            return value if num is None else float(num)
        if isinstance(value, int):
            return float(value)
        return value
    if affinity == TEXT:
        return apply_text_affinity(value)
    return value


# ---------------------------------------------------------------- truth and comparison


def truth(value: object) -> bool | None:
    """SQL truth value: None for NULL, otherwise whether the numeric value is non-zero."""
    if value is None:
        return None
    if isinstance(value, str):
        return text_to_number_prefix(value) != 0
    return value != 0


def _class(value: object) -> int:
    return 2 if isinstance(value, str) else 1


def compare(a: object, b: object) -> int:
    """Compare two non-NULL values: numbers sort before text; text compares by code point."""
    ca, cb = _class(a), _class(b)
    if ca != cb:
        return -1 if ca < cb else 1
    if a < b:  # type: ignore[operator]
        return -1
    if a > b:  # type: ignore[operator]
        return 1
    return 0


def sort_key(value: object) -> tuple:
    """Key giving SQLite's default ordering: NULL < numbers < text."""
    if value is None:
        return (0, 0)
    if isinstance(value, str):
        return (2, value)
    return (1, value)


# ---------------------------------------------------------------- arithmetic


def _int_result(value: int) -> int | float:
    if INT_MIN <= value <= INT_MAX:
        return value
    return float(value)


def _real_result(value: float) -> float | None:
    return None if math.isnan(value) else value


def arith(op: str, a: object, b: object) -> object:
    if a is None or b is None:
        return None
    x, y = to_number(a), to_number(b)
    if isinstance(x, int) and isinstance(y, int):
        if op == "+":
            return _int_result(x + y)
        if op == "-":
            return _int_result(x - y)
        if op == "*":
            return _int_result(x * y)
        if op == "/":
            if y == 0:
                return None
            q = abs(x) // abs(y)
            return _int_result(q if (x < 0) == (y < 0) else -q)
        if op == "%":
            if y == 0:
                return None
            r = abs(x) % abs(y)
            return r if x >= 0 else -r
        raise SQLError(f"unknown operator {op}")
    fx, fy = float(x), float(y)
    if op == "+":
        return _real_result(fx + fy)
    if op == "-":
        return _real_result(fx - fy)
    if op == "*":
        return _real_result(fx * fy)
    if op == "/":
        if fy == 0:
            return None
        return _real_result(fx / fy)
    if op == "%":
        ix, iy = _real_to_int_clamped(fx), _real_to_int_clamped(fy)
        if iy == 0:
            return None
        r = abs(ix) % abs(iy)
        return float(r if ix >= 0 else -r)
    raise SQLError(f"unknown operator {op}")


def _real_to_int_clamped(v: float) -> int:
    if math.isnan(v):
        return 0
    if v >= 2.0**63:
        return INT_MAX
    if v <= -(2.0**63):
        return INT_MIN
    return int(v)


def negate(value: object) -> object:
    if value is None:
        return None
    num = to_number(value)
    if isinstance(num, int):
        return _int_result(-num)
    return -num


# ---------------------------------------------------------------- LIKE

_like_cache: dict[tuple[str, str | None], re.Pattern[str]] = {}


def _ascii_case_insensitive(ch: str) -> str:
    if "a" <= ch.lower() <= "z" and ch.isascii():
        return f"[{ch.lower()}{ch.upper()}]"
    return re.escape(ch)


def like_regex(pattern: str, escape: str | None) -> re.Pattern[str]:
    key = (pattern, escape)
    compiled = _like_cache.get(key)
    if compiled is None:
        parts = []
        i = 0
        while i < len(pattern):
            ch = pattern[i]
            if escape is not None and ch == escape:
                i += 1
                if i < len(pattern):
                    parts.append(_ascii_case_insensitive(pattern[i]))
            elif ch == "%":
                parts.append(".*")
            elif ch == "_":
                parts.append(".")
            else:
                parts.append(_ascii_case_insensitive(ch))
            i += 1
        compiled = re.compile("".join(parts), re.DOTALL)
        if len(_like_cache) > 1000:
            _like_cache.clear()
        _like_cache[key] = compiled
    return compiled
