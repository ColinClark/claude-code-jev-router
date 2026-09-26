"""Value semantics: SQLite storage classes, affinity, comparison, arithmetic, LIKE.

Values are represented as Python ``None`` (NULL), ``int`` (INTEGER), ``float`` (REAL)
and ``str`` (TEXT).
"""

from __future__ import annotations

import re
from functools import lru_cache

INT_MIN = -(2**63)
INT_MAX = 2**63 - 1

NUMERIC_AFFINITIES = frozenset({"INTEGER", "REAL", "NUMERIC"})

_WS = " \t\n\r\f\v"
_FULL_NUMBER_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_PREFIX_NUMBER_RE = re.compile(r"[ \t\n\r\f\v]*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")


# ----------------------------------------------------------------------------
# Affinity
# ----------------------------------------------------------------------------


def affinity_from_type(type_name: str | None) -> str:
    """Map a declared type name to a SQLite affinity name."""
    if not type_name:
        return "BLOB"
    t = type_name.upper()
    if "INT" in t:
        return "INTEGER"
    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return "TEXT"
    if "BLOB" in t:
        return "BLOB"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "REAL"
    return "NUMERIC"


def text_to_number(s: str) -> int | float | None:
    """Convert well-formed numeric text (surrounding whitespace allowed) or return None."""
    stripped = s.strip(_WS)
    if not stripped or not _FULL_NUMBER_RE.fullmatch(stripped):
        return None
    return _parse_number_text(stripped)


def _parse_number_text(text: str) -> int | float:
    if "." in text or "e" in text or "E" in text:
        return float(text)
    value = int(text)
    if value < INT_MIN or value > INT_MAX:
        return float(value)
    return value


def _float_to_int_if_exact(value: float) -> int | float:
    if value.is_integer() and INT_MIN <= value <= INT_MAX:
        return int(value)
    return value


def apply_affinity(value: object, affinity: str | None) -> object:
    """Apply column affinity as SQLite does when storing a value."""
    if value is None:
        return None
    if affinity in ("INTEGER", "NUMERIC"):
        if isinstance(value, str):
            n = text_to_number(value)
            if n is None:
                return value
            value = n
        if isinstance(value, float):
            return _float_to_int_if_exact(value)
        return value
    if affinity == "REAL":
        if isinstance(value, str):
            n = text_to_number(value)
            if n is None:
                return value
            value = n
        if isinstance(value, int):
            return float(value)
        if isinstance(value, float) and value.is_integer() and INT_MIN <= value <= INT_MAX:
            # SQLite stores integral REAL values as integers, so -0.0 reads back as 0.0.
            return float(int(value))
        return value
    if affinity == "TEXT":
        if isinstance(value, (int, float)):
            return number_to_text(value)
        return value
    return value


# ----------------------------------------------------------------------------
# Text conversion
# ----------------------------------------------------------------------------


def number_to_text(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if value != value:
        return "NaN"
    if value == float("inf"):
        return "Inf"
    if value == float("-inf"):
        return "-Inf"
    if value == 0:
        return "0.0"
    s = f"{value:.15g}"
    if "e" in s:
        mantissa, exp = s.split("e")
        if "." not in mantissa:
            mantissa += ".0"
        return mantissa + "e" + exp
    if "." not in s:
        s += ".0"
    return s


def to_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return number_to_text(value)  # type: ignore[arg-type]


# ----------------------------------------------------------------------------
# Numeric conversion for arithmetic / truthiness
# ----------------------------------------------------------------------------


def numeric_prefix(s: str) -> int | float:
    """Convert the longest numeric prefix of text, like SQLite does for arithmetic."""
    m = _PREFIX_NUMBER_RE.match(s)
    if not m:
        return 0
    return _parse_number_text(m.group(1))


def to_numeric(value: object) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, str):
        return numeric_prefix(value)
    return value  # type: ignore[return-value]


def truth(value: object) -> bool | None:
    """Three-valued truth of a value: True, False or None (unknown)."""
    if value is None:
        return None
    n = to_numeric(value)
    return n != 0


def bool_to_int(t: bool | None) -> int | None:
    if t is None:
        return None
    return 1 if t else 0


def and3(a: bool | None, b: bool | None) -> bool | None:
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def or3(a: bool | None, b: bool | None) -> bool | None:
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def not3(a: bool | None) -> bool | None:
    if a is None:
        return None
    return not a


# ----------------------------------------------------------------------------
# Arithmetic
# ----------------------------------------------------------------------------


def _int_result(value: int, fa: float, fb: float, op: str) -> int | float:
    if INT_MIN <= value <= INT_MAX:
        return value
    if op == "+":
        return fa + fb
    if op == "-":
        return fa - fb
    return fa * fb


def arith(op: str, a: object, b: object) -> object:
    if a is None or b is None:
        return None
    x = to_numeric(a)
    y = to_numeric(b)
    assert x is not None and y is not None
    both_int = isinstance(x, int) and isinstance(y, int)
    if op == "+":
        r = x + y
        return _int_result(r, float(x), float(y), op) if both_int else r
    if op == "-":
        r = x - y
        return _int_result(r, float(x), float(y), op) if both_int else r
    if op == "*":
        r = x * y
        return _int_result(r, float(x), float(y), op) if both_int else r
    if op == "/":
        if y == 0:
            return None
        if both_int:
            q = abs(x) // abs(y)
            if (x < 0) != (y < 0):
                q = -q
            if q > INT_MAX:
                return float(x) / float(y)
            return q
        return float(x) / float(y)
    if op == "%":
        try:
            ix = int(x)
            iy = int(y)
        except (OverflowError, ValueError):
            return None
        if iy == 0:
            return None
        if iy == -1:
            r = 0
        else:
            r = abs(ix) % abs(iy)
            if ix < 0:
                r = -r
        return float(r) if not both_int else r
    raise ValueError(op)


def negate(value: object) -> object:
    """Unary minus; SQLite computes it as ``0 - value`` (so -(0.0) is 0.0, not -0.0)."""
    return arith("-", 0, value)


def concat(a: object, b: object) -> str | None:
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)  # type: ignore[operator]


# ----------------------------------------------------------------------------
# Comparison and ordering
# ----------------------------------------------------------------------------


def storage_rank(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return 2
    return 1


def compare(a: object, b: object) -> int:
    """Total order over non-NULL values: numbers < text; numbers numerically; text by code point."""
    ra = storage_rank(a)
    rb = storage_rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if a < b:  # type: ignore[operator]
        return -1
    if a > b:  # type: ignore[operator]
        return 1
    return 0


def sort_key(value: object) -> tuple:
    if value is None:
        return (0, 0)
    if isinstance(value, str):
        return (2, value)
    return (1, value)


def coerce_for_comparison(
    a: object, b: object, aff_a: str | None, aff_b: str | None
) -> tuple[object, object]:
    """Apply SQLite's affinity conversions before a comparison.

    ``None`` means the operand is not a column (no affinity); ``"BLOB"`` is a column declared
    without a type, which is distinct from "no affinity" for the TEXT rule below.
    """
    a_num = aff_a in NUMERIC_AFFINITIES
    b_num = aff_b in NUMERIC_AFFINITIES
    if a_num and not b_num:
        b = apply_affinity(b, "NUMERIC")
    elif b_num and not a_num:
        a = apply_affinity(a, "NUMERIC")
    elif aff_a == "TEXT" and aff_b is None:
        b = apply_affinity(b, "TEXT")
    elif aff_b == "TEXT" and aff_a is None:
        a = apply_affinity(a, "TEXT")
    return a, b


def compare_op(op: str, a: object, b: object) -> bool | None:
    """Evaluate a comparison operator with NULL propagation (operands already coerced)."""
    if a is None or b is None:
        return None
    c = compare(a, b)
    if op in ("=", "=="):
        return c == 0
    if op in ("!=", "<>"):
        return c != 0
    if op == "<":
        return c < 0
    if op == "<=":
        return c <= 0
    if op == ">":
        return c > 0
    if op == ">=":
        return c >= 0
    raise ValueError(op)


def is_op(a: object, b: object) -> bool:
    """Null-safe equality (IS)."""
    if a is None or b is None:
        return a is None and b is None
    return compare(a, b) == 0


# ----------------------------------------------------------------------------
# LIKE
# ----------------------------------------------------------------------------


@lru_cache(maxsize=256)
def _like_regex(pattern: str) -> re.Pattern[str]:
    parts: list[str] = []
    for ch in pattern:
        if ch == "%":
            parts.append(".*")
        elif ch == "_":
            parts.append(".")
        elif ch.isascii() and ch.isalpha():
            parts.append(f"[{ch.lower()}{ch.upper()}]")
        else:
            parts.append(re.escape(ch))
    return re.compile("".join(parts), re.DOTALL)


def like(value: object, pattern: object) -> bool | None:
    if value is None or pattern is None:
        return None
    text = to_text(value)
    pat = to_text(pattern)
    assert text is not None and pat is not None
    return _like_regex(pat).fullmatch(text) is not None
