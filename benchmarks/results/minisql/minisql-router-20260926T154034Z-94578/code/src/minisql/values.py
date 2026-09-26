"""Value semantics modelled on SQLite: type conversions, arithmetic, comparison and ordering."""

from __future__ import annotations

import math
import re

INT_MIN = -(2**63)
INT_MAX = 2**63 - 1

# Column affinities.
INTEGER = "INTEGER"
REAL = "REAL"
TEXT = "TEXT"
NUMERIC = "NUMERIC"
BLOB = "BLOB"

NUMERIC_AFFINITIES = (INTEGER, REAL, NUMERIC)


def affinity_of(type_name: str) -> str:
    """Return the SQLite affinity for a declared column type name."""
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


# ---------------------------------------------------------------------------
# Text <-> number conversions
# ---------------------------------------------------------------------------

_NUM_PREFIX = re.compile(r"\s*([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?")
_WHOLE_NUMBER = re.compile(r"\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*\Z")


def _int_or_float(i: int) -> int | float:
    return i if INT_MIN <= i <= INT_MAX else float(i)


def text_to_numeric(s: str) -> int | float:
    """Convert text to a number the way SQLite does in arithmetic (longest numeric prefix)."""
    m = _NUM_PREFIX.match(s)
    sign, whole, frac, exp = m.group(1), m.group(2), m.group(3), m.group(4)
    if not whole and not frac:
        return 0
    if frac is None and exp is None:
        return _int_or_float(int(sign + whole))
    text = sign + (whole or "0") + "." + (frac or "0")
    if exp is not None:
        text += "e" + exp
    try:
        return float(text)
    except OverflowError:  # pragma: no cover - float() returns inf instead
        return math.inf


def text_looks_numeric(s: str) -> bool:
    return _WHOLE_NUMBER.match(s) is not None


def to_number(v):
    """Numeric value of v for arithmetic; None stays None."""
    if v is None or isinstance(v, (int, float)):
        return v
    return text_to_numeric(v)


def format_real(x: float) -> str:
    """Render a float the way SQLite renders REAL values as TEXT ("%!.15g")."""
    if math.isnan(x):
        return "NaN"  # pragma: no cover - SQLite stores NaN as NULL
    if math.isinf(x):
        return "Inf" if x > 0 else "-Inf"
    if x == 0:
        return "0.0"
    mantissa, exp_s = f"{x:.14e}".split("e")
    exp = int(exp_s)
    sign = "-" if mantissa.startswith("-") else ""
    digits = mantissa.lstrip("-").replace(".", "").rstrip("0") or "0"
    if exp < -4 or exp >= 15:
        frac = digits[1:] or "0"
        return f"{sign}{digits[0]}.{frac}e{'-' if exp < 0 else '+'}{abs(exp):02d}"
    if exp < 0:
        return f"{sign}0.{'0' * (-exp - 1)}{digits}"
    int_part = digits[: exp + 1].ljust(exp + 1, "0")
    frac = digits[exp + 1 :] or "0"
    return f"{sign}{int_part}.{frac}"


def to_text(v):
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    return format_real(v)


def truth(v):
    """Three-valued truth of a value: True, False or None (unknown)."""
    if v is None:
        return None
    if isinstance(v, str):
        v = text_to_numeric(v)
    return v != 0


# ---------------------------------------------------------------------------
# Affinity application
# ---------------------------------------------------------------------------


def _numeric_text(s: str, prefer_int: bool) -> int | float | str:
    if not text_looks_numeric(s):
        return s
    n = text_to_numeric(s.strip())
    if isinstance(n, float) and prefer_int and n.is_integer() and INT_MIN <= n <= INT_MAX:
        stripped = s.strip()
        if "e" not in stripped.lower() or abs(n) < 2**53:
            return int(n)
    return n


def apply_storage_affinity(v, affinity: str):
    """Convert a value being stored into a column with the given affinity."""
    if v is None:
        return None
    if affinity == TEXT:
        return to_text(v)
    if affinity == REAL:
        if isinstance(v, str):
            v = _numeric_text(v, prefer_int=False)
        if isinstance(v, int):
            return float(v)
        return v
    if affinity in (INTEGER, NUMERIC):
        if isinstance(v, str):
            v = _numeric_text(v, prefer_int=True)
        if isinstance(v, float) and v.is_integer() and INT_MIN <= v < 2**63:
            return int(v)
        return v
    return v


def apply_numeric_affinity(v):
    """Numeric affinity for comparisons: convert well-formed numeric text to a number."""
    if isinstance(v, str):
        return _numeric_text(v, prefer_int=True)
    return v


# ---------------------------------------------------------------------------
# Ordering and comparison
# ---------------------------------------------------------------------------


def sort_key(v):
    """Key implementing SQLite's cross-type ordering: NULL < numbers < text."""
    if v is None:
        return (0, 0)
    if isinstance(v, str):
        return (2, v)
    return (1, v)


def compare(a, b) -> int:
    """Compare two non-NULL values; returns -1, 0 or 1."""
    ka, kb = sort_key(a), sort_key(b)
    if ka < kb:
        return -1
    if ka > kb:
        return 1
    return 0


def apply_comparison_affinity(v, affinity):
    """Apply a comparison affinity to one operand (used for IN lists)."""
    if affinity in NUMERIC_AFFINITIES:
        return apply_numeric_affinity(v)
    if affinity == TEXT:
        return to_text(v)
    return v


def coerce_for_comparison(a, b, aff_a, aff_b):
    """Apply SQLite's comparison affinity rules to a pair of operands."""
    a_num = aff_a in NUMERIC_AFFINITIES
    b_num = aff_b in NUMERIC_AFFINITIES
    if a_num and not b_num:
        b = apply_numeric_affinity(b)
    elif b_num and not a_num:
        a = apply_numeric_affinity(a)
    elif aff_a == TEXT and aff_b is None:
        b = to_text(b)
    elif aff_b == TEXT and aff_a is None:
        a = to_text(a)
    return a, b


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------


def _int_result(r: int, fallback):
    if INT_MIN <= r <= INT_MAX:
        return r
    return fallback()


def _real(r: float):
    """SQLite turns NaN results into NULL."""
    return None if r != r else r


def add(a, b):
    a, b = to_number(a), to_number(b)
    if a is None or b is None:
        return None
    if isinstance(a, int) and isinstance(b, int):
        return _int_result(a + b, lambda: float(a) + float(b))
    return _real(float(a) + float(b))


def sub(a, b):
    a, b = to_number(a), to_number(b)
    if a is None or b is None:
        return None
    if isinstance(a, int) and isinstance(b, int):
        return _int_result(a - b, lambda: float(a) - float(b))
    return _real(float(a) - float(b))


def mul(a, b):
    a, b = to_number(a), to_number(b)
    if a is None or b is None:
        return None
    if isinstance(a, int) and isinstance(b, int):
        return _int_result(a * b, lambda: float(a) * float(b))
    return _real(float(a) * float(b))


def div(a, b):
    a, b = to_number(a), to_number(b)
    if a is None or b is None or b == 0:
        return None
    if isinstance(a, int) and isinstance(b, int):
        q = abs(a) // abs(b)
        if (a < 0) != (b < 0):
            q = -q
        return _int_result(q, lambda: float(a) / float(b))
    return _real(float(a) / float(b))


_INT_PREFIX = re.compile(r"\s*([+-]?\d+)")


def int_value(v) -> int:
    """SQLite's integer conversion (sqlite3VdbeIntValue): saturating, text by integer prefix."""
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if math.isnan(v):
            return 0
        if v >= 2**63:
            return INT_MAX
        if v < INT_MIN:
            return INT_MIN
        return int(v)
    m = _INT_PREFIX.match(v)
    if not m:
        return 0
    return max(INT_MIN, min(INT_MAX, int(m.group(1))))


def mod(a, b):
    na, nb = to_number(a), to_number(b)
    if na is None or nb is None:
        return None
    if isinstance(na, int) and isinstance(nb, int):
        ia, ib, real = na, nb, False
    else:
        # The REAL path converts the original operands with integer conversion.
        ia, ib, real = int_value(a), int_value(b), True
    if ib == 0:
        return None
    r = abs(ia) % abs(ib)
    if ia < 0:
        r = -r
    return float(r) if real else r


def negate(a):
    a = to_number(a)
    if a is None:
        return None
    if isinstance(a, int):
        return _int_result(-a, lambda: -float(a))
    return -a


def concat(a, b):
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)


# ---------------------------------------------------------------------------
# LIKE
# ---------------------------------------------------------------------------

_like_cache: dict[str, re.Pattern] = {}


def like(value, pattern):
    if value is None or pattern is None:
        return None
    value, pattern = to_text(value), to_text(pattern)
    rx = _like_cache.get(pattern)
    if rx is None:
        parts = []
        for ch in pattern:
            if ch == "%":
                parts.append(".*")
            elif ch == "_":
                parts.append(".")
            else:
                parts.append(re.escape(ch))
        rx = re.compile("".join(parts), re.DOTALL | re.IGNORECASE | re.ASCII)
        if len(_like_cache) > 1000:
            _like_cache.clear()
        _like_cache[pattern] = rx
    return 1 if rx.fullmatch(value) else 0


def typeof(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "real"
    return "text"
