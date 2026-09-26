"""Value semantics that mirror SQLite: affinity, conversion, comparison, arithmetic."""

from __future__ import annotations

import math
import re

INT_MIN = -(1 << 63)
INT_MAX = (1 << 63) - 1

# Affinity names.
INTEGER = "INTEGER"
REAL = "REAL"
TEXT = "TEXT"
NUMERIC = "NUMERIC"
BLOB = "BLOB"

_NUM_PREFIX = re.compile(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")
_FULL_NUM = re.compile(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*\Z")


def type_affinity(type_name: str | None) -> str:
    """Return the SQLite affinity for a declared column type."""
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


def _parse_number(s: str) -> int | float:
    if "." in s or "e" in s or "E" in s:
        return float(s)
    v = int(s)
    if v < INT_MIN or v > INT_MAX:
        return float(s)
    return v


def to_number(v):
    """Convert a value to a number the way SQLite arithmetic does (numeric prefix)."""
    if isinstance(v, (int, float)) or v is None:
        return v
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    m = _NUM_PREFIX.match(v)
    if not m:
        return 0
    return _parse_number(m.group(1))


def to_real(v) -> float | None:
    if v is None:
        return None
    return float(to_number(v))


def to_integer(v) -> int | None:
    if v is None:
        return None
    n = to_number(v)
    if isinstance(n, float):
        if math.isnan(n):
            return 0
        if n >= 9.223372036854775807e18:
            return INT_MAX
        if n <= -9.223372036854775808e18:
            return INT_MIN
        return int(n)
    return n


def real_to_text(v: float) -> str:
    """Format a REAL the way SQLite renders it as TEXT."""
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "Inf" if v > 0 else "-Inf"
    if v == 0:
        return "0.0"
    # SQLite renders REAL as TEXT with printf("%!.15g"): 15 significant digits,
    # exponent form when exp < -4 or exp >= 15, and always at least one fractional digit.
    s = format(v, ".14e")
    mant, exp_s = s.split("e")
    exp = int(exp_s)
    sign = ""
    if mant.startswith("-"):
        sign = "-"
        mant = mant[1:]
    digits = mant.replace(".", "").rstrip("0") or "0"
    if exp < -4 or exp >= 15:
        frac = digits[1:] or "0"
        esign = "+" if exp >= 0 else "-"
        return f"{sign}{digits[0]}.{frac}e{esign}{abs(exp):02d}"
    if exp >= 0:
        int_part = digits[: exp + 1].ljust(exp + 1, "0")
        frac = digits[exp + 1 :] or "0"
        return f"{sign}{int_part}.{frac}"
    return f"{sign}0.{'0' * (-exp - 1)}{digits}"


def to_text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, float):
        return real_to_text(v)
    return str(v)


def numeric_affinity(v, real: bool = False):
    """Apply NUMERIC/INTEGER (or REAL when ``real``) affinity to a value."""
    if v is None:
        return None
    if isinstance(v, str):
        m = _FULL_NUM.match(v)
        if not m:
            return v
        n = _parse_number(m.group(1))
    elif isinstance(v, bytes):
        return v
    else:
        n = v
    if real:
        return float(n) + 0.0  # also normalises -0.0 as SQLite storage does
    if isinstance(n, float) and n.is_integer() and -(2.0**63) <= n < 2.0**63:
        return int(n)
    return n


def apply_affinity(v, affinity: str | None):
    if v is None or affinity is None or affinity == BLOB:
        return v
    if affinity == TEXT:
        if isinstance(v, (int, float)):
            return to_text(v)
        return v
    if affinity == REAL:
        return numeric_affinity(v, real=True)
    return numeric_affinity(v)


def _rank(v) -> int:
    if isinstance(v, (int, float)):
        return 1
    if isinstance(v, str):
        return 2
    return 3


def compare(a, b) -> int:
    """Compare two non-NULL values using SQLite ordering (numbers < text < blob)."""
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def sort_compare(a, b) -> int:
    """Compare including NULL, which sorts before everything."""
    if a is None:
        return 0 if b is None else -1
    if b is None:
        return 1
    return compare(a, b)


def is_numeric_aff(aff: str | None) -> bool:
    return aff in (INTEGER, REAL, NUMERIC)


def comparison_operands(a, aff_a, b, aff_b):
    """Apply SQLite's affinity rules prior to comparing a and b."""
    if is_numeric_aff(aff_a) and not is_numeric_aff(aff_b):
        b = numeric_affinity(b)
    elif is_numeric_aff(aff_b) and not is_numeric_aff(aff_a):
        a = numeric_affinity(a)
    elif aff_a == TEXT and aff_b is None:
        b = apply_affinity(b, TEXT)
    elif aff_b == TEXT and aff_a is None:
        a = apply_affinity(a, TEXT)
    return a, b


def truth(v) -> bool | None:
    """Three-valued truth of a value: True, False or None (unknown)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v != 0
    return to_number(v) != 0


def _int_result(r: int, fallback: float):
    if r < INT_MIN or r > INT_MAX:
        return fallback
    return r


def _real_result(r: float):
    if math.isnan(r):
        return None
    return r


def arith(op: str, a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    if isinstance(a, int) and isinstance(b, int):
        if op == "+":
            return _int_result(a + b, float(a) + float(b))
        if op == "-":
            return _int_result(a - b, float(a) - float(b))
        if op == "*":
            return _int_result(a * b, float(a) * float(b))
        if op == "/":
            if b == 0:
                return None
            if a == INT_MIN and b == -1:
                return float(a) / float(b)
            q = abs(a) // abs(b)
            return q if (a < 0) == (b < 0) else -q
        if op == "%":
            if b == 0:
                return None
            r = abs(a) % abs(b)
            return -r if a < 0 else r
        raise ValueError(op)
    fa, fb = float(a), float(b)
    if op == "+":
        return _real_result(fa + fb)
    if op == "-":
        return _real_result(fa - fb)
    if op == "*":
        return _real_result(fa * fb)
    if op == "/":
        if fb == 0.0:
            return None
        return _real_result(fa / fb)
    if op == "%":
        ia, ib = to_integer(fa), to_integer(fb)
        if ib == 0:
            return None
        if ib == -1:
            ib = 1
        r = abs(ia) % abs(ib)
        return float(-r if ia < 0 else r)
    raise ValueError(op)


def bitwise(op: str, a, b):
    if a is None or b is None:
        return None
    ia, ib = to_integer(a), to_integer(b)
    if op == "&":
        r = ia & ib
    elif op == "|":
        r = ia | ib
    elif op == "<<" or op == ">>":
        if op == ">>":
            ib = -ib
        if ib >= 64:
            r = 0
        elif ib >= 0:
            r = (ia << ib) & ((1 << 64) - 1)
        elif ib <= -64:
            r = -1 if ia < 0 else 0
        else:
            r = ia >> (-ib)
    else:
        raise ValueError(op)
    r &= (1 << 64) - 1
    if r > INT_MAX:
        r -= 1 << 64
    return r


def negate(v):
    if v is None:
        return None
    n = to_number(v)
    if isinstance(n, int):
        if n == INT_MIN:
            return -float(n)
        return -n
    return -n


def concat(a, b):
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)


_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def ascii_lower(s: str) -> str:
    return s.translate(_ASCII_LOWER)


def ascii_upper(s: str) -> str:
    return s.translate(_ASCII_UPPER)


_like_cache: dict[tuple[str, str | None], re.Pattern[str]] = {}


def like(value, pattern, escape=None):
    """SQLite LIKE: ASCII case-insensitive, % and _ wildcards."""
    if value is None or pattern is None:
        return None
    v = ascii_lower(to_text(value))
    p = ascii_lower(to_text(pattern))
    esc = None
    if escape is not None:
        esc = to_text(escape)
        if len(esc) != 1:
            raise ValueError("ESCAPE expression must be a single character")
    key = (p, esc)
    rx = _like_cache.get(key)
    if rx is None:
        parts = []
        i = 0
        while i < len(p):
            c = p[i]
            if esc is not None and c == esc:
                i += 1
                if i < len(p):
                    parts.append(re.escape(p[i]))
            elif c == "%":
                parts.append(".*")
            elif c == "_":
                parts.append(".")
            else:
                parts.append(re.escape(c))
            i += 1
        rx = re.compile("".join(parts), re.DOTALL)
        if len(_like_cache) > 1000:
            _like_cache.clear()
        _like_cache[key] = rx
    return 1 if rx.fullmatch(v) else 0


def type_name(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "real"
    if isinstance(v, str):
        return "text"
    return "blob"
