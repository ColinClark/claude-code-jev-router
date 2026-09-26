"""SQLite-compatible value semantics: affinity, conversion, arithmetic, comparison."""

from __future__ import annotations

import math
import re
from functools import lru_cache

from .errors import SQLError

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

# Column affinities.
INTEGER = "INTEGER"
REAL = "REAL"
TEXT = "TEXT"
NUMERIC = "NUMERIC"
BLOB = "BLOB"

_WS = " \t\n\f\r\v"
_FULL_NUM = re.compile(
    r"[ \t\n\f\r\v]*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)[ \t\n\f\r\v]*"
)
_PREFIX_NUM = re.compile(
    r"[ \t\n\f\r\v]*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
)
_INT_TEXT = re.compile(r"[+-]?[0-9]+")


def affinity_of_type(type_name: str | None) -> str:
    """Map a declared column type to an affinity using SQLite's rules."""
    if not type_name:
        return BLOB
    t = type_name.upper()
    if "INT" in t:
        return INTEGER
    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return TEXT
    if "BLOB" in t:
        return BLOB
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return REAL
    return NUMERIC


def _number_from_literal(text: str) -> int | float:
    """Convert a matched numeric literal to int (if integral form in range) or float."""
    if _INT_TEXT.fullmatch(text):
        v = int(text)
        if INT64_MIN <= v <= INT64_MAX:
            return v
        return float(v)
    return float(text)


def parse_full_number(s: str) -> int | float | None:
    """Return the number a string represents in full, or None if it is not numeric."""
    m = _FULL_NUM.fullmatch(s)
    if m is None:
        return None
    return _number_from_literal(m.group(1))


def text_to_number(s: str) -> int | float:
    """Numeric value of text used in arithmetic: the longest numeric prefix, else 0."""
    m = _PREFIX_NUM.match(s)
    if m is None:
        return 0
    return _number_from_literal(m.group(1))


def float_to_int(f: float) -> int:
    """C-style cast of a double to int64, saturating at the bounds."""
    if math.isnan(f):
        return 0
    if f >= 9.223372036854775807e18:
        return INT64_MAX
    if f <= -9.223372036854775808e18:
        return INT64_MIN
    return int(f)


def real_to_text(f: float) -> str:
    """Render a float the way SQLite does when converting REAL to TEXT ("%!.15g")."""
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


def to_text(v):
    """Convert a non-NULL value to TEXT."""
    if isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    return real_to_text(v)


def to_number(v):
    """Convert a non-NULL value to a number for arithmetic."""
    if isinstance(v, str):
        return text_to_number(v)
    return v


def to_real(v) -> float:
    if isinstance(v, str):
        return float(text_to_number(v))
    return float(v)


def to_integer(v) -> int:
    if isinstance(v, str):
        v = text_to_number(v)
    if isinstance(v, float):
        return float_to_int(v)
    return v


def numeric_affinity(v):
    """Apply NUMERIC affinity (as for comparisons): well-formed numeric text becomes a number."""
    if isinstance(v, str):
        n = parse_full_number(v)
        if n is not None:
            return n
    return v


def text_affinity(v):
    if isinstance(v, (int, float)):
        return to_text(v)
    return v


def _integral_to_int(v):
    """A float with an exact int64 value becomes that int; anything else is unchanged."""
    if isinstance(v, float) and v.is_integer() and -9.223372036854775808e18 <= v < 9.223372036854775808e18:
        return int(v)
    return v


def apply_storage_affinity(v, affinity: str):
    """Convert a value being stored into a column with the given affinity."""
    if v is None:
        return None
    if affinity in (INTEGER, NUMERIC):
        if isinstance(v, str):
            n = parse_full_number(v)
            if n is None:
                return v
            v = n
        return _integral_to_int(v)
    if affinity == REAL:
        if isinstance(v, str):
            n = parse_full_number(v)
            return v if n is None else float(n) + 0.0
        # Adding 0.0 turns -0.0 into 0.0, as SQLite's record format does.
        return float(v) + 0.0
    if affinity == TEXT:
        return to_text(v)
    return v


def cast(v, affinity: str):
    """CAST(v AS type)."""
    if v is None:
        return None
    if affinity == TEXT:
        return to_text(v)
    if affinity == REAL:
        return to_real(v)
    if affinity == INTEGER:
        return to_integer(v)
    if affinity == NUMERIC:
        return _integral_to_int(text_to_number(v) if isinstance(v, str) else v)
    return v


def truth(v):
    """Three-valued truth of a value: True, False or None (unknown)."""
    if v is None:
        return None
    if isinstance(v, str):
        v = text_to_number(v)
    return v != 0


# ---------------------------------------------------------------------------
# Arithmetic


def _fix_float(r: float):
    return None if math.isnan(r) else r


def add(a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    if type(a) is int and type(b) is int:
        r = a + b
        if INT64_MIN <= r <= INT64_MAX:
            return r
    return _fix_float(float(a) + float(b))


def sub(a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    if type(a) is int and type(b) is int:
        r = a - b
        if INT64_MIN <= r <= INT64_MAX:
            return r
    return _fix_float(float(a) - float(b))


def mul(a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    if type(a) is int and type(b) is int:
        r = a * b
        if INT64_MIN <= r <= INT64_MAX:
            return r
    return _fix_float(float(a) * float(b))


def div(a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    if type(a) is int and type(b) is int:
        if b == 0:
            return None
        if a == INT64_MIN and b == -1:
            return float(a) / float(b)
        q = abs(a) // abs(b)
        return -q if (a < 0) != (b < 0) else q
    fb = float(b)
    if fb == 0.0:
        return None
    return _fix_float(float(a) / fb)


def mod(a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    is_int = type(a) is int and type(b) is int
    ia = a if type(a) is int else float_to_int(a)
    ib = b if type(b) is int else float_to_int(b)
    if ib == 0:
        return None
    if ib == -1:
        r = 0
    else:
        r = abs(ia) % abs(ib)
        if ia < 0:
            r = -r
    return r if is_int else float(r)


def neg(a):
    if a is None:
        return None
    a = to_number(a)
    if type(a) is int:
        if a == INT64_MIN:
            return -float(a)
        return -a
    return -a


def concat(a, b):
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)


# ---------------------------------------------------------------------------
# Comparison


def _rank(v) -> int:
    if v is None:
        return 0
    if isinstance(v, str):
        return 2
    return 1


def compare(a, b) -> int:
    """Total order used by ORDER BY, MIN/MAX and comparisons: NULL < numbers < text."""
    ra = _rank(a)
    rb = _rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if ra == 0:
        return 0
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def sort_key(v):
    """Key usable with Python sorting that agrees with compare()."""
    if v is None:
        return (0, 0)
    if isinstance(v, str):
        return (2, v)
    return (1, v)


# ---------------------------------------------------------------------------
# LIKE


@lru_cache(maxsize=256)
def _like_regex(pattern: str, escape: str | None) -> re.Pattern:
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if escape is not None and c == escape:
            i += 1
            if i < n:
                out.append(re.escape(pattern[i]))
            else:
                # A trailing escape character matches nothing.
                out.append("(?!)")
        elif c == "%":
            out.append(".*")
        elif c == "_":
            out.append(".")
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out), re.DOTALL | re.IGNORECASE | re.ASCII)


def like(value, pattern, escape=None):
    if value is None or pattern is None:
        return None
    if escape is not None:
        esc = to_text(escape)
        if len(esc) != 1:
            raise SQLError("ESCAPE expression must be a single character")
    else:
        esc = None
    rx = _like_regex(to_text(pattern), esc)
    return 1 if rx.fullmatch(to_text(value)) else 0
