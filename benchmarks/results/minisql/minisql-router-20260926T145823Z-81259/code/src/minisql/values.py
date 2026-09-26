"""SQLite value semantics: type conversion, affinity, comparison and arithmetic."""

import math
import re

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

_NUMERIC_PREFIX = re.compile(r"\s*([+-]?(?:\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?)")
_INT_PREFIX = re.compile(r"\s*[+-]?\d+")
_WELL_FORMED = re.compile(r"\s*[+-]?(?:\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\s*")


def real_to_text(x: float) -> str:
    """Render a float the way SQLite (3.47, "%!.15g") does when converting REAL to TEXT."""
    if math.isinf(x):
        return "Inf" if x > 0 else "-Inf"
    if math.isnan(x):
        return "NaN"
    if x == 0:
        return "0.0"
    mantissa, exp_text = f"{x:.14e}".split("e")
    exp = int(exp_text)
    sign = "-" if mantissa.startswith("-") else ""
    digits = mantissa.lstrip("-").replace(".", "").rstrip("0") or "0"
    if exp < -4 or exp >= 15:
        return f"{sign}{digits[0]}.{digits[1:] or '0'}e{'+' if exp >= 0 else '-'}{abs(exp):02d}"
    if exp >= 0:
        int_part = digits[: exp + 1].ljust(exp + 1, "0")
        frac = digits[exp + 1 :] or "0"
    else:
        int_part = "0"
        frac = "0" * (-exp - 1) + digits
    return f"{sign}{int_part}.{frac}"


def to_text(value):
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, float):
        return real_to_text(value)
    return str(value)


def _int_or_real(text: str, is_real: bool):
    if not is_real:
        value = int(text)
        if INT64_MIN <= value <= INT64_MAX:
            return value
    return float(text)


def text_to_number(text: str):
    """Convert text to a number using its longest numeric prefix (0 if none)."""
    m = _NUMERIC_PREFIX.match(text)
    if not m:
        return 0
    return _int_or_real(m.group(1), bool(m.group(2) is not None or m.group(3)))


def to_number(value):
    """Numeric value of an operand for arithmetic; NULL stays NULL."""
    if isinstance(value, str):
        return text_to_number(value)
    return value


def to_integer(value):
    """CAST(value AS INTEGER) semantics."""
    if value is None:
        return None
    if isinstance(value, str):
        m = _INT_PREFIX.match(value)
        return max(INT64_MIN, min(INT64_MAX, int(m.group()))) if m else 0
    if isinstance(value, float):
        if math.isnan(value):
            return 0
        if value >= 9.223372036854775807e18:
            return INT64_MAX
        if value <= -9.223372036854775808e18:
            return INT64_MIN
        return int(value)
    return value


def to_real(value):
    if value is None:
        return None
    return float(to_number(value))


def _numeric_from_text(text: str):
    """Return the number a well-formed numeric text represents, or None."""
    if not _WELL_FORMED.fullmatch(text):
        return None
    m = _NUMERIC_PREFIX.match(text)
    return _int_or_real(m.group(1), bool(m.group(2) is not None or m.group(3)))


def _real_as_int(x: float):
    if x.is_integer() and -9.223372036854775e18 < x < 9.223372036854775e18:
        return int(x)
    return x


def apply_affinity(value, affinity: str | None):
    """Coerce a value to a column affinity, as SQLite does on storage."""
    if value is None or affinity is None or affinity == "BLOB":
        return value
    if affinity == "TEXT":
        return to_text(value)
    if isinstance(value, str):
        number = _numeric_from_text(value)
        if number is None:
            return value
        value = number
    if affinity == "REAL":
        return float(value)
    if isinstance(value, float):
        return _real_as_int(value)
    return value


def apply_numeric_affinity_for_compare(value):
    if isinstance(value, str):
        number = _numeric_from_text(value)
        if number is not None:
            return number
    return value


# ---------------------------------------------------------------- comparison


def type_class(value) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return 2
    return 1


def sort_key(value):
    """Key implementing SQLite ordering: NULL < numbers < text."""
    if value is None:
        return (0, 0)
    if isinstance(value, str):
        return (2, value)
    return (1, value)


def compare(a, b) -> int:
    """Three-way comparison of two non-NULL values in SQLite order."""
    ca, cb = type_class(a), type_class(b)
    if ca != cb:
        return -1 if ca < cb else 1
    if a == b:
        return 0
    return -1 if a < b else 1


def coerce_for_compare(a, b, aff_a: str | None, aff_b: str | None):
    """Apply SQLite's comparison affinity rules to the two operands."""
    numeric = ("INTEGER", "REAL", "NUMERIC")
    if aff_a in numeric or aff_b in numeric:
        if aff_a not in numeric:
            a = apply_numeric_affinity_for_compare(a)
        if aff_b not in numeric:
            b = apply_numeric_affinity_for_compare(b)
    elif aff_a == "TEXT" and aff_b is None:
        b = to_text(b)
    elif aff_b == "TEXT" and aff_a is None:
        a = to_text(a)
    return a, b


def truth(value):
    """SQL truth value: True, False or None (unknown)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = text_to_number(value)
    return value != 0


# ---------------------------------------------------------------- arithmetic


def _int_result(value, fallback):
    if INT64_MIN <= value <= INT64_MAX:
        return value
    return fallback()


def arith(op: str, a, b):
    if a is None or b is None:
        return None
    raw_a, raw_b = a, b
    a = to_number(a)
    b = to_number(b)
    both_int = isinstance(a, int) and isinstance(b, int)
    if op == "+":
        if both_int:
            return _int_result(a + b, lambda: float(a) + float(b))
        return float(a) + float(b)
    if op == "-":
        if both_int:
            return _int_result(a - b, lambda: float(a) - float(b))
        return float(a) - float(b)
    if op == "*":
        if both_int:
            return _int_result(a * b, lambda: float(a) * float(b))
        return float(a) * float(b)
    if op == "/":
        if both_int:
            if b == 0:
                return None
            if a == INT64_MIN and b == -1:
                return float(a) / -1.0
            q = abs(a) // abs(b)
            return q if (a >= 0) == (b >= 0) else -q
        if float(b) == 0.0:
            return None
        return float(a) / float(b)
    if op == "%":
        # Text operands contribute their integer prefix, as in SQLite.
        ia, ib = to_integer(raw_a), to_integer(raw_b)
        if ib == 0:
            return None
        if ib == -1:
            r = 0
        else:
            r = abs(ia) % abs(ib)
            if ia < 0:
                r = -r
        return r if both_int else float(r)
    raise ValueError(op)


def negate(value):
    if value is None:
        return None
    value = to_number(value)
    if isinstance(value, int):
        return -value if value != INT64_MIN else -float(value)
    return -value


def concat(a, b):
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)


# ---------------------------------------------------------------- LIKE

_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_like_cache: dict[str, re.Pattern] = {}


def like(value, pattern):
    if value is None or pattern is None:
        return None
    value = to_text(value).translate(_ASCII_LOWER)
    pattern = to_text(pattern).translate(_ASCII_LOWER)
    regex = _like_cache.get(pattern)
    if regex is None:
        parts = []
        for ch in pattern:
            if ch == "%":
                parts.append(".*")
            elif ch == "_":
                parts.append(".")
            else:
                parts.append(re.escape(ch))
        regex = re.compile("".join(parts), re.DOTALL)
        if len(_like_cache) > 1000:
            _like_cache.clear()
        _like_cache[pattern] = regex
    return 1 if regex.fullmatch(value) else 0
