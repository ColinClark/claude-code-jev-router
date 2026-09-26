"""SQLite-compatible value semantics: affinity, conversion, comparison and arithmetic."""

from __future__ import annotations

import math
import re
import struct

from minisql.errors import SQLError

INT_MIN = -(2**63)
INT_MAX = 2**63 - 1

INTEGER = "INTEGER"
REAL = "REAL"
TEXT = "TEXT"
NUMERIC = "NUMERIC"
BLOB = None  # no affinity

NUMERIC_AFFINITIES = (INTEGER, REAL, NUMERIC)

_NUM_PREFIX = re.compile(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")
_NUM_FULL = re.compile(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*\Z")
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def type_affinity(type_name: str) -> str | None:
    """Map a declared column type to an affinity using SQLite's rules."""
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


def _int_or_float(i: int) -> int | float:
    return i if INT_MIN <= i <= INT_MAX else float(i)


def _parse_number(text: str) -> int | float:
    if "." in text or "e" in text or "E" in text:
        return float(text)
    return _int_or_float(int(text))


def text_prefix_number(s: str) -> int | float:
    """Numeric value of the longest numeric prefix of s (0 if none), as SQLite casts text."""
    m = _NUM_PREFIX.match(s)
    if not m:
        return 0
    return _parse_number(m.group(1))


def text_exact_number(s: str) -> int | float | None:
    """Number represented by s if s is entirely a well-formed number, else None."""
    m = _NUM_FULL.match(s)
    if not m:
        return None
    return _parse_number(m.group(1))


def _high_bits(x: float) -> float:
    m = struct.unpack("<Q", struct.pack("<d", x))[0] & 0xFFFFFFFFFC000000
    return struct.unpack("<d", struct.pack("<Q", m))[0]


def _dekker_mul2(x: list[float], y: float, yy: float) -> None:
    """Double-double multiply x *= (y + yy), exactly as SQLite's dekkerMul2()."""
    hx = _high_bits(x[0])
    tx = x[0] - hx
    hy = _high_bits(y)
    ty = y - hy
    p = hx * hy
    q = hx * ty + tx * hy
    c = p + q
    cc = p - c + q + tx * ty
    cc = x[0] * yy + x[1] * y + cc
    x0 = c + cc
    x[1] = (c - x0) + cc
    x[0] = x0


def _decimal_digits(r: float, n_round: int) -> tuple[str, int]:
    """Port of SQLite's sqlite3FpDecode() for r > 0.

    Returns (significant digits, position of the decimal point) rounded half-up to
    n_round digits, reproducing SQLite's own (slightly inexact) decimal conversion.
    """
    e = 0
    rr = [r, 0.0]
    if rr[0] > 9.223372036854774784e18:
        while rr[0] > 9.223372036854774784e118:
            e += 100
            _dekker_mul2(rr, 1.0e-100, -1.99918998026028836196e-117)
        while rr[0] > 9.223372036854774784e28:
            e += 10
            _dekker_mul2(rr, 1.0e-10, -3.6432197315497741579e-27)
        while rr[0] > 9.223372036854774784e18:
            e += 1
            _dekker_mul2(rr, 1.0e-01, -5.5511151231257827021e-18)
    else:
        while rr[0] < 9.223372036854774784e-83:
            e -= 100
            _dekker_mul2(rr, 1.0e100, -1.5902891109759918046e83)
        while rr[0] < 9.223372036854774784e07:
            e -= 10
            _dekker_mul2(rr, 1.0e10, 0.0)
        while rr[0] < 9.22337203685477478e17:
            e -= 1
            _dekker_mul2(rr, 1.0e01, 0.0)
    v = int(rr[0]) - int(-rr[1]) if rr[1] < 0 else int(rr[0]) + int(rr[1])
    digits = str(v)
    point = len(digits) + e
    if len(digits) > n_round:
        head = int(digits[:n_round])
        if digits[n_round] >= "5":
            head += 1
        digits = str(head)
        if len(digits) > n_round:  # carried into a new leading digit
            point += 1
    return digits.rstrip("0") or "0", point


def format_real(v: float) -> str:
    """Render a float as text the way SQLite does (printf "%!.15g")."""
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "Inf" if v > 0 else "-Inf"
    if v == 0:
        return "0.0"
    sign = "-" if v < 0 else ""
    digits, point = _decimal_digits(abs(v), 15)
    exp = point - 1
    if exp < -4 or exp > 14:
        mant = digits[0] + "." + (digits[1:] or "0")
        return f"{sign}{mant}e{'+' if exp >= 0 else '-'}{abs(exp):02d}"
    if point <= 0:
        return f"{sign}0.{'0' * -point}{digits}"
    return f"{sign}{digits[:point].ljust(point, '0')}.{digits[point:] or '0'}"


def to_text(v):
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    return format_real(v)


def to_number(v):
    """Convert a value for use in arithmetic (text uses its numeric prefix)."""
    if isinstance(v, str):
        return text_prefix_number(v)
    return v


def real_to_int(v: float) -> int:
    """Convert a float to an integer, clamping like SQLite's sqlite3VdbeIntValue."""
    if math.isnan(v):
        return 0
    if v <= INT_MIN:
        return INT_MIN
    if v >= INT_MAX:
        return INT_MAX
    return int(v)


def to_int(v) -> int | None:
    v = to_number(v)
    if v is None:
        return None
    if isinstance(v, float):
        return real_to_int(v)
    return v


def _integral_real_to_int(v: float):
    if v.is_integer() and -(2.0**63) <= v < 2.0**63:
        return int(v)
    return v


def apply_affinity(v, affinity):
    """Coerce a value to be stored in (or compared as) a column of the given affinity."""
    if v is None or affinity is None:
        return v
    if affinity == TEXT:
        return to_text(v)
    if isinstance(v, str):
        n = text_exact_number(v)
        if n is None:
            return v
        v = n
    if affinity == REAL:
        return float(v) + 0.0  # + 0.0 turns -0.0 into 0.0, as SQLite stores it
    if isinstance(v, float):
        return _integral_real_to_int(v)
    return v


def cast(v, type_name: str):
    """CAST(v AS type_name)."""
    if v is None:
        return None
    affinity = type_affinity(type_name)
    if affinity == TEXT:
        return to_text(v)
    if affinity is None:
        return v
    if affinity == INTEGER:
        return to_int(v)
    if affinity == REAL:
        return float(to_number(v))
    # NUMERIC
    if isinstance(v, str):
        n = text_prefix_number(v)
        return _integral_real_to_int(n) if isinstance(n, float) else n
    return _integral_real_to_int(v) if isinstance(v, float) else v


def truth(v):
    """Three-valued truth of a value: True, False or None (unknown)."""
    if v is None:
        return None
    if isinstance(v, str):
        v = text_prefix_number(v)
    return v != 0


def type_class(v) -> int:
    if v is None:
        return 0
    if isinstance(v, str):
        return 2
    return 1


def compare(a, b) -> int:
    """Total order of non-NULL values: numbers < text, text compared by code point."""
    ca, cb = type_class(a), type_class(b)
    if ca != cb:
        return -1 if ca < cb else 1
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def sort_key(v):
    """Key implementing SQLite's ORDER BY order (NULL first, then numbers, then text)."""
    if v is None:
        return (0, 0)
    if isinstance(v, str):
        return (2, v)
    return (1, v)


def arithmetic(op: str, a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    if op == "%":
        return _modulo(a, b)
    if isinstance(a, int) and isinstance(b, int):
        if op == "+":
            r = a + b
        elif op == "-":
            r = a - b
        elif op == "*":
            r = a * b
        else:
            if b == 0:
                return None
            q = abs(a) // abs(b)
            r = q if (a >= 0) == (b >= 0) else -q
        if INT_MIN <= r <= INT_MAX:
            return r
        a, b = float(a), float(b)
    a, b = float(a), float(b)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if b == 0.0:
        return None
    try:
        return a / b
    except OverflowError:
        return math.copysign(math.inf, a) * math.copysign(1.0, b)


def _modulo(a, b):
    is_real = isinstance(a, float) or isinstance(b, float)
    ia = real_to_int(a) if isinstance(a, float) else a
    ib = real_to_int(b) if isinstance(b, float) else b
    if ib == 0:
        return None
    if ib == -1:
        r = 0
    else:
        r = abs(ia) % abs(ib)
        if ia < 0:
            r = -r
    return float(r) if is_real else r


def negate(v):
    if v is None:
        return None
    v = to_number(v)
    if isinstance(v, int):
        return _int_or_float(-v)
    # SQLite keeps integral reals as integers internally, so negating 0.0 yields 0.0.
    return -v if v != 0 else 0.0


def concat(a, b):
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)


_like_cache: dict[str, re.Pattern] = {}


def like(value, pattern):
    if value is None or pattern is None:
        return None
    value = to_text(value).translate(_ASCII_LOWER)
    pattern = to_text(pattern).translate(_ASCII_LOWER)
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
        rx = re.compile("".join(parts), re.DOTALL)
        _like_cache[pattern] = rx
    return 1 if rx.fullmatch(value) else 0


def check_int64(v: int) -> int:
    if not INT_MIN <= v <= INT_MAX:
        raise SQLError("integer overflow")
    return v
