"""SQLite-compatible value semantics: affinity, conversion, comparison, arithmetic."""

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
NUMERIC_AFFINITIES = (INTEGER, REAL, NUMERIC)

_PREFIX_RE = re.compile(r"\s*([+-]?)(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")
_FULL_RE = re.compile(r"\s*[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\s*\Z")


def type_affinity(type_name: str) -> str:
    """Map a declared column type to its affinity (SQLite rules)."""
    t = type_name.upper()
    if "INT" in t:
        return INTEGER
    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return TEXT
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return REAL
    return NUMERIC


def _int_or_real(text: str, is_real: bool):
    if not is_real:
        v = int(text)
        if INT_MIN <= v <= INT_MAX:
            return v
    return float(text)


def text_to_number(s: str):
    """Convert text to a number the way SQLite does for arithmetic (longest numeric prefix)."""
    m = _PREFIX_RE.match(s)
    if not m:
        return 0
    return _int_or_real(m.group(0), bool(m.group(3) or m.group(4) or "." in m.group(2)))


def text_to_number_strict(s: str):
    """Convert well-formed numeric text to a number, or return None if it is not one."""
    if not _FULL_RE.match(s):
        return None
    t = s.strip()
    return _int_or_real(t, "." in t or "e" in t or "E" in t)


def to_number(v):
    """Numeric value of v for arithmetic; NULL stays None."""
    if v is None or isinstance(v, (int, float)):
        return v
    return text_to_number(v)


def format_real(r: float) -> str:
    if math.isnan(r):
        return "NaN"
    if math.isinf(r):
        return "Inf" if r > 0 else "-Inf"
    s = format(r, ".15g")
    if "e" in s:
        mant, exp = s.split("e")
        if "." not in mant:
            mant += ".0"
        return mant + "e" + exp
    if "." not in s:
        s += ".0"
    if s == "-0.0":
        s = "0.0"
    return s


def to_text(v):
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, float):
        return format_real(v)
    return str(v)


def apply_affinity(v, affinity):
    """Apply a column affinity to a value (as when storing it)."""
    if v is None or affinity is None:
        return v
    if affinity == TEXT:
        return to_text(v)
    if isinstance(v, str):
        n = text_to_number_strict(v)
        if n is None:
            return v
        v = n
    if affinity == REAL:
        # SQLite stores integral reals as integers, so -0.0 reads back as 0.0.
        return float(v) + 0.0
    if isinstance(v, float) and v.is_integer() and INT_MIN <= v <= INT_MAX:
        return int(v)
    return v


def apply_numeric_for_compare(v):
    """Numeric affinity as applied to a comparison operand: only well-formed text changes."""
    if isinstance(v, str):
        n = text_to_number_strict(v)
        if n is not None:
            return n
    return v


def comparison_prep(aff_l, aff_r):
    """Return (conv_l, conv_r) conversion functions (or None) for a comparison."""
    l_num = aff_l in NUMERIC_AFFINITIES
    r_num = aff_r in NUMERIC_AFFINITIES
    if l_num and not r_num:
        return None, apply_numeric_for_compare
    if r_num and not l_num:
        return apply_numeric_for_compare, None
    if aff_l == TEXT and aff_r is None:
        return None, to_text
    if aff_r == TEXT and aff_l is None:
        return to_text, None
    return None, None


def sort_key(v):
    """Key implementing SQLite's cross-type ordering: NULL < numbers < text."""
    if v is None:
        return (0, 0)
    if isinstance(v, str):
        return (2, v)
    return (1, v)


def compare(a, b) -> int:
    """Three-way compare two non-NULL values."""
    ka, kb = sort_key(a), sort_key(b)
    if ka < kb:
        return -1
    if ka > kb:
        return 1
    return 0


def truthy(v):
    """SQL truth value: True, False, or None for NULL."""
    if v is None:
        return None
    if isinstance(v, str):
        v = text_to_number(v)
    return v != 0


def _fix_int(v):
    if INT_MIN <= v <= INT_MAX:
        return v
    return None


def add(a, b):
    a, b = to_number(a), to_number(b)
    if a is None or b is None:
        return None
    if isinstance(a, int) and isinstance(b, int):
        r = _fix_int(a + b)
        return float(a) + float(b) if r is None else r
    return float(a) + float(b)


def sub(a, b):
    a, b = to_number(a), to_number(b)
    if a is None or b is None:
        return None
    if isinstance(a, int) and isinstance(b, int):
        r = _fix_int(a - b)
        return float(a) - float(b) if r is None else r
    return float(a) - float(b)


def mul(a, b):
    a, b = to_number(a), to_number(b)
    if a is None or b is None:
        return None
    if isinstance(a, int) and isinstance(b, int):
        r = _fix_int(a * b)
        return float(a) * float(b) if r is None else r
    return float(a) * float(b)


def div(a, b):
    a, b = to_number(a), to_number(b)
    if a is None or b is None:
        return None
    if isinstance(a, int) and isinstance(b, int):
        if b == 0:
            return None
        q = abs(a) // abs(b)
        if (a < 0) != (b < 0):
            q = -q
        r = _fix_int(q)
        return float(a) / float(b) if r is None else r
    if b == 0:
        return None
    return float(a) / float(b)


def mod(a, b):
    a, b = to_number(a), to_number(b)
    if a is None or b is None:
        return None
    is_real = isinstance(a, float) or isinstance(b, float)
    ia, ib = _to_int(a), _to_int(b)
    if ib == 0:
        return None
    r = abs(ia) % abs(ib)
    if ia < 0:
        r = -r
    return float(r) if is_real else r


def _to_int(v):
    if isinstance(v, int):
        return v
    if math.isnan(v):
        return 0
    if v >= INT_MAX:
        return INT_MAX
    if v <= INT_MIN:
        return INT_MIN
    return int(v)


def negate(a):
    a = to_number(a)
    if a is None:
        return None
    if isinstance(a, int):
        r = _fix_int(-a)
        return float(-a) if r is None else r
    return -a


def concat(a, b):
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)


_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_like_cache: dict[str, re.Pattern] = {}


def like(value, pattern):
    if value is None or pattern is None:
        return None
    value, pattern = to_text(value), to_text(pattern)
    rx = _like_cache.get(pattern)
    if rx is None:
        parts = []
        for ch in pattern.translate(_ASCII_LOWER):
            if ch == "%":
                parts.append(".*")
            elif ch == "_":
                parts.append(".")
            else:
                parts.append(re.escape(ch))
        rx = re.compile("".join(parts), re.DOTALL)
        _like_cache[pattern] = rx
    return 1 if rx.fullmatch(value.translate(_ASCII_LOWER)) else 0
