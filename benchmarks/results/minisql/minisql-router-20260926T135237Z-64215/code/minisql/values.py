"""Value semantics mirroring SQLite: conversions, affinity, comparison, arithmetic."""

from __future__ import annotations

import math
import re

INT_MIN = -(2**63)
INT_MAX = 2**63 - 1

Value = int | float | str | None

_WS = " \t\n\f\r\v"
_INT_RE = re.compile(r"[+-]?[0-9]+\Z")
_REAL_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_PREFIX_RE = re.compile(r"[ \t\n\f\r\v]*([+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)")

NUMERIC_AFFINITIES = frozenset({"INTEGER", "REAL", "NUMERIC"})


# ---------------------------------------------------------------------------
# Text conversion


# How REAL values are rendered as text. SQLite up to 3.50 uses printf("%!.15g");
# newer releases emit the shortest representation (up to 17 digits) that round-trips.
# "classic" mirrors the former, "roundtrip" the latter.
REAL_TEXT_MODE = "classic"


def set_real_text_mode(mode: str) -> None:
    """Select how REAL values are converted to text: "classic" or "roundtrip"."""
    global REAL_TEXT_MODE
    if mode not in ("classic", "roundtrip"):
        raise ValueError(f"unknown real text mode: {mode!r}")
    REAL_TEXT_MODE = mode


def real_to_text(f: float) -> str:
    """Format a float the way SQLite renders REAL values as text."""
    if math.isnan(f):
        return "NaN"
    if math.isinf(f):
        return "Inf" if f > 0 else "-Inf"
    if f == 0.0:
        return "0.0"
    if REAL_TEXT_MODE == "classic":
        s = f"{f:.15g}"
        if "e" in s:
            mant, exp_part = s.split("e")
            if "." not in mant:
                mant += ".0"
            return f"{mant}e{exp_part}"
        if "." not in s:
            s += ".0"
        return s
    s = ""
    for prec in (15, 17):
        s = f"{f:.{prec - 1}e}"
        if float(s) == f:
            break
    mant, exp_s = s.split("e")
    exp = int(exp_s)
    neg = mant.startswith("-")
    digits = mant.lstrip("-").replace(".", "").rstrip("0") or "0"
    sign = "-" if neg else ""
    if exp < -4 or exp >= 17:
        rest = digits[1:] or "0"
        esign = "+" if exp >= 0 else "-"
        return f"{sign}{digits[0]}.{rest}e{esign}{abs(exp):02d}"
    if exp >= 0:
        int_part = digits[: exp + 1].ljust(exp + 1, "0")
        frac = digits[exp + 1 :] or "0"
        return f"{sign}{int_part}.{frac}"
    return f"{sign}0.{'0' * (-exp - 1)}{digits}"


def to_text(v: Value) -> str | None:
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, float):
        return real_to_text(v)
    return str(v)


# ---------------------------------------------------------------------------
# Numeric conversion


def _int_or_real(s: str) -> int | float:
    n = int(s)
    if INT_MIN <= n <= INT_MAX:
        return n
    return float(s)


def text_to_exact_number(s: str) -> int | float | None:
    """Parse text that is entirely a well-formed number (surrounding whitespace ok)."""
    t = s.strip(_WS)
    if _INT_RE.match(t):
        return _int_or_real(t)
    if _REAL_RE.match(t):
        return float(t)
    return None


def to_number(v: Value) -> int | float | None:
    """Convert a value to a number the way SQLite does for arithmetic (longest prefix)."""
    if v is None or isinstance(v, (int, float)):
        return v
    m = _PREFIX_RE.match(v)
    if not m:
        return 0
    txt = m.group(1)
    if _INT_RE.match(txt):
        return _int_or_real(txt)
    return float(txt)


def real_to_int(f: float) -> int:
    """C-style truncating cast of a double to a 64-bit integer (saturating)."""
    if math.isnan(f):
        return 0
    if f >= 9.223372036854775807e18:
        return INT_MAX
    if f <= -9.223372036854775808e18:
        return INT_MIN
    return int(f)


_INT_PREFIX_RE = re.compile(r"[ \t\n\f\r\v]*([+-]?[0-9]+)")


def text_to_int(s: str) -> int:
    """Integer value of text as SQLite computes it: leading integer prefix, saturating."""
    m = _INT_PREFIX_RE.match(s)
    if not m:
        return 0
    n = int(m.group(1))
    return max(INT_MIN, min(INT_MAX, n))


def to_int(v: Value) -> int | None:
    if isinstance(v, str):
        return text_to_int(v)
    n = to_number(v)
    if n is None:
        return None
    if isinstance(n, float):
        return real_to_int(n)
    return n


def to_bool(v: Value) -> bool | None:
    """SQLite truth value: NULL stays NULL, otherwise numeric value != 0."""
    if v is None:
        return None
    if isinstance(v, str):
        return to_number(v) != 0
    return v != 0


# ---------------------------------------------------------------------------
# Affinity


def affinity_of_type(type_name: str | None) -> str:
    """Determine column affinity from a declared type name (SQLite rules)."""
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


def _real_as_int(f: float) -> int | float:
    if f.is_integer() and -9.223372036854775808e18 <= f < 9.223372036854775807e18:
        return int(f)
    return f


def apply_affinity(v: Value, affinity: str | None) -> Value:
    """Apply a column affinity to a value being stored (or compared)."""
    if v is None or affinity is None or affinity == "BLOB":
        return v
    if affinity == "TEXT":
        return to_text(v)
    if isinstance(v, str):
        n = text_to_exact_number(v)
        if n is None:
            return v
        v = n
    if affinity == "REAL":
        # SQLite stores integral reals compactly as integers, so -0.0 reads back as 0.0.
        return float(v) + 0.0 if v == 0 else float(v)
    # INTEGER / NUMERIC
    if isinstance(v, float):
        return _real_as_int(v)
    return v


def apply_numeric_for_compare(v: Value) -> Value:
    if isinstance(v, str):
        n = text_to_exact_number(v)
        if n is not None:
            return n
    return v


def apply_text_for_compare(v: Value) -> Value:
    if isinstance(v, (int, float)):
        return to_text(v)
    return v


def comparison_converters(left_aff: str | None, right_aff: str | None):
    """Return (left_conv, right_conv) per SQLite's comparison affinity rules."""
    l_num = left_aff in NUMERIC_AFFINITIES
    r_num = right_aff in NUMERIC_AFFINITIES
    if l_num and not r_num:
        return None, apply_numeric_for_compare
    if r_num and not l_num:
        return apply_numeric_for_compare, None
    if left_aff == "TEXT" and right_aff is None:
        return None, apply_text_for_compare
    if right_aff == "TEXT" and left_aff is None:
        return apply_text_for_compare, None
    return None, None


# ---------------------------------------------------------------------------
# Comparison and ordering


def sort_key(v: Value) -> tuple:
    """Key implementing SQLite ordering: NULL < numbers < text (binary collation)."""
    if v is None:
        return (0, 0)
    if isinstance(v, str):
        return (2, v)
    return (1, v)


def compare(a: Value, b: Value) -> int:
    """Compare two non-NULL values; returns -1, 0 or 1."""
    a_text = isinstance(a, str)
    b_text = isinstance(b, str)
    if a_text != b_text:
        return 1 if a_text else -1
    if a < b:  # type: ignore[operator]
        return -1
    if a > b:  # type: ignore[operator]
        return 1
    return 0


# ---------------------------------------------------------------------------
# Arithmetic


def _check_int(r: int, fallback) -> int | float:
    if INT_MIN <= r <= INT_MAX:
        return r
    return fallback()


def _float_result(r: float) -> float | None:
    if math.isnan(r):
        return None
    return r


def arith(op: str, a: Value, b: Value) -> Value:
    if a is None or b is None:
        return None
    x = to_number(a)
    y = to_number(b)
    assert x is not None and y is not None
    if isinstance(x, int) and isinstance(y, int):
        if op == "+":
            return _check_int(x + y, lambda: float(x) + float(y))
        if op == "-":
            return _check_int(x - y, lambda: float(x) - float(y))
        if op == "*":
            return _check_int(x * y, lambda: float(x) * float(y))
        if op == "/":
            if y == 0:
                return None
            q = abs(x) // abs(y)
            if (x < 0) != (y < 0):
                q = -q
            return _check_int(q, lambda: float(x) / float(y))
        if op == "%":
            if y == 0:
                return None
            r = abs(x) % abs(y)
            return -r if x < 0 else r
        raise ValueError(op)
    fx = float(x)
    fy = float(y)
    try:
        if op == "+":
            return _float_result(fx + fy)
        if op == "-":
            return _float_result(fx - fy)
        if op == "*":
            return _float_result(fx * fy)
        if op == "/":
            if fy == 0.0:
                return None
            return _float_result(fx / fy)
    except OverflowError:
        return math.inf if (fx < 0) == (fy < 0) else -math.inf
    if op == "%":
        ix = text_to_int(a) if isinstance(a, str) else real_to_int(fx)
        iy = text_to_int(b) if isinstance(b, str) else real_to_int(fy)
        if iy == 0:
            return None
        r = abs(ix) % abs(iy)
        return float(-r if ix < 0 else r)
    raise ValueError(op)


def negate(v: Value) -> Value:
    if v is None:
        return None
    n = to_number(v)
    if isinstance(n, int):
        if n == INT_MIN:
            return -float(n)
        return -n
    return -n  # type: ignore[operator]


def concat(a: Value, b: Value) -> Value:
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)  # type: ignore[operator]


def bitop(op: str, a: Value, b: Value) -> Value:
    if a is None or b is None:
        return None
    x = to_int(a)
    y = to_int(b)
    assert x is not None and y is not None
    if op == "&":
        r = x & y
    elif op == "|":
        r = x | y
    elif op == "<<":
        if y < 0:
            return bitop(">>", x, -y)
        r = 0 if y >= 64 else (x << y) & 0xFFFFFFFFFFFFFFFF
    else:  # >>
        if y < 0:
            return bitop("<<", x, -y)
        r = (-1 if x < 0 else 0) if y >= 64 else x >> y
    r &= 0xFFFFFFFFFFFFFFFF
    if r > INT_MAX:
        r -= 2**64
    return r


# ---------------------------------------------------------------------------
# LIKE

_LOWER_ASCII = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_like_cache: dict[tuple[str, str | None], re.Pattern[str]] = {}


def like(value: str, pattern: str, escape: str | None = None) -> bool:
    key = (pattern, escape)
    rx = _like_cache.get(key)
    if rx is None:
        pat = pattern.translate(_LOWER_ASCII)
        parts: list[str] = []
        i = 0
        while i < len(pat):
            ch = pat[i]
            if escape is not None and ch == escape.translate(_LOWER_ASCII):
                i += 1
                if i < len(pat):
                    parts.append(re.escape(pat[i]))
                i += 1
                continue
            if ch == "%":
                parts.append(".*")
            elif ch == "_":
                parts.append(".")
            else:
                parts.append(re.escape(ch))
            i += 1
        rx = re.compile("".join(parts) + r"\Z", re.DOTALL)
        if len(_like_cache) > 1000:
            _like_cache.clear()
        _like_cache[key] = rx
    return rx.match(value.translate(_LOWER_ASCII)) is not None
