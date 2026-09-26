"""Value semantics modelled on SQLite: affinity, conversion, comparison, arithmetic."""

from __future__ import annotations

import math
import re
from functools import lru_cache

INT_MIN = -(2**63)
INT_MAX = 2**63 - 1

# Affinities
INTEGER = "INTEGER"
REAL = "REAL"
NUMERIC = "NUMERIC"
TEXT = "TEXT"
BLOB = "BLOB"

NUMERIC_AFFINITIES = (INTEGER, REAL, NUMERIC)

_WS = " \t\n\f\r\v"
_NUM_BODY = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_NUM_FULL = re.compile(r"[ \t\n\f\r\v]*(" + _NUM_BODY + r")[ \t\n\f\r\v]*\Z")
_NUM_PREFIX = re.compile(r"[ \t\n\f\r\v]*(" + _NUM_BODY + r")")
_INT_PREFIX = re.compile(r"[ \t\n\f\r\v]*([+-]?\d+)")
_INT_FORM = re.compile(r"[+-]?\d+\Z")


def _num_from_text(s: str) -> int | float:
    """Convert a well formed numeric literal text to int (if integral form and in range)."""
    if _INT_FORM.match(s):
        v = int(s)
        if INT_MIN <= v <= INT_MAX:
            return v
        return float(v)
    return float(s)


def _float_to_int_if_exact(v: float) -> int | float:
    if v.is_integer() and -9.223372036854775e18 < v < 9.223372036854775e18:
        return int(v)
    return v


def float_to_int(v: float) -> int:
    """C-style (saturating) cast of a float to a 64-bit integer."""
    if v != v:
        return 0
    if v >= 9.223372036854775807e18:
        return INT_MAX
    if v <= -9.223372036854775808e18:
        return INT_MIN
    return int(v)


def text_numeric_value(s: str) -> int | float | None:
    """Return the numeric value of text if the whole text is a well-formed number."""
    m = _NUM_FULL.match(s)
    if not m:
        return None
    return _num_from_text(m.group(1))


def to_number(v):
    """Numeric value used by arithmetic: text takes its longest numeric prefix (or 0)."""
    if v is None or isinstance(v, (int, float)):
        return v
    m = _NUM_PREFIX.match(v)
    if not m:
        return 0
    return _num_from_text(m.group(1))


# How REAL values are rendered as TEXT.  SQLite <= 3.47 uses printf("%!.15g");
# newer releases use up to 17 significant digits so that the text round-trips.
# "legacy" matches the former, "roundtrip" the latter.
REAL_TEXT_MODE = "legacy"


def format_real(v: float) -> str:
    """Render a float the way SQLite converts REAL to TEXT."""
    if v != v:
        return "NaN"
    if v == math.inf:
        return "Inf"
    if v == -math.inf:
        return "-Inf"
    if v == 0:
        return "0.0"
    if REAL_TEXT_MODE == "legacy":
        return _format_real_legacy(v)
    return _format_real_roundtrip(v)


def _format_real_legacy(v: float) -> str:
    s = format(v, ".15g")
    if "e" in s:
        mant, exp = s.split("e")
        if "." not in mant:
            mant += ".0"
        return mant + "e" + exp
    if "." not in s:
        s += ".0"
    return s


def _format_real_roundtrip(v: float) -> str:
    if v == 0:
        return "0.0"
    s = format(v, ".14e")
    if float(s) != v:
        s = format(v, ".16e")
    mant, exp_s = s.split("e")
    exp = int(exp_s)
    neg = mant.startswith("-")
    digits = mant.lstrip("-").replace(".", "").rstrip("0") or "0"
    if -4 <= exp <= 16:
        if exp >= 0:
            ip = digits[: exp + 1].ljust(exp + 1, "0")
            fp = digits[exp + 1 :] or "0"
        else:
            ip = "0"
            fp = "0" * (-exp - 1) + digits
        out = ip + "." + fp
    else:
        out = digits[0] + "." + (digits[1:] or "0") + "e" + ("+" if exp >= 0 else "-")
        out += f"{abs(exp):02d}"
    return "-" + out if neg else out


def to_text(v):
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    return format_real(v)


def truth(v):
    """SQLite boolean interpretation: None (unknown), True or False."""
    if v is None:
        return None
    if isinstance(v, str):
        v = to_number(v)
    return v != 0


def type_name(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "real"
    return "text"


# ---------------------------------------------------------------------------
# Affinity


def affinity_for_type(type_name_: str | None) -> str:
    """SQLite's rules for determining column affinity from a declared type name."""
    if not type_name_:
        return BLOB
    t = type_name_.upper()
    if "INT" in t:
        return INTEGER
    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return TEXT
    if "BLOB" in t:
        return BLOB
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return REAL
    return NUMERIC


def apply_affinity(v, aff):
    """Apply a column affinity to a value being stored."""
    if v is None or aff is None or aff == BLOB:
        return v
    if aff == TEXT:
        return to_text(v)
    if aff == REAL:
        if isinstance(v, int):
            return float(v)
        if isinstance(v, str):
            n = text_numeric_value(v)
            if n is not None:
                return float(n)
        return v
    # INTEGER / NUMERIC
    if isinstance(v, float):
        return _float_to_int_if_exact(v)
    if isinstance(v, str):
        n = text_numeric_value(v)
        if n is None:
            return v
        if isinstance(n, float):
            return _float_to_int_if_exact(n)
        return n
    return v


def numeric_conv(v):
    """Numeric affinity applied to a comparison operand."""
    if isinstance(v, str):
        n = text_numeric_value(v)
        if n is not None:
            return n
    return v


def text_conv(v):
    """Text affinity applied to a comparison operand."""
    if isinstance(v, (int, float)):
        return to_text(v)
    return v


def comparison_affinity(aff1, aff2):
    """Affinity applied to both operands of a comparison (None: no conversion)."""
    if aff1 is not None and aff2 is not None:
        if aff1 in NUMERIC_AFFINITIES or aff2 in NUMERIC_AFFINITIES:
            return NUMERIC
        return None
    aff = aff1 if aff1 is not None else aff2
    if aff in NUMERIC_AFFINITIES:
        return NUMERIC
    if aff == TEXT:
        return TEXT
    return None


def converter_for(aff):
    if aff == NUMERIC:
        return numeric_conv
    if aff == TEXT:
        return text_conv
    return None


def cast_value(v, aff):
    """CAST(v AS <type with affinity aff>)."""
    if v is None:
        return None
    if aff == TEXT:
        return to_text(v)
    if aff == BLOB:
        return to_text(v) if not isinstance(v, str) else v
    if aff == INTEGER:
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return float_to_int(v)
        m = _INT_PREFIX.match(v)
        if not m:
            return 0
        n = int(m.group(1))
        return max(INT_MIN, min(INT_MAX, n))
    if aff == REAL:
        return float(to_number(v))
    # NUMERIC
    if isinstance(v, (int, float)):
        return v
    n = to_number(v)
    if isinstance(n, float):
        return _float_to_int_if_exact(n)
    return n


# ---------------------------------------------------------------------------
# Comparison and ordering


def compare(a, b) -> int:
    """Compare two non-NULL values using SQLite's ordering (numbers < text)."""
    a_text = isinstance(a, str)
    b_text = isinstance(b, str)
    if a_text != b_text:
        return 1 if a_text else -1
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def sort_key(v):
    if v is None:
        return (0, 0)
    if isinstance(v, str):
        return (2, v)
    return (1, v)


# ---------------------------------------------------------------------------
# Arithmetic


def _num_result(v):
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, int) and not (INT_MIN <= v <= INT_MAX):
        return float(v)
    return v


def add(a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    if isinstance(a, int) and isinstance(b, int):
        r = a + b
        if INT_MIN <= r <= INT_MAX:
            return r
    return _num_result(float(a) + float(b))


def sub(a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    if isinstance(a, int) and isinstance(b, int):
        r = a - b
        if INT_MIN <= r <= INT_MAX:
            return r
    return _num_result(float(a) - float(b))


def mul(a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    if isinstance(a, int) and isinstance(b, int):
        r = a * b
        if INT_MIN <= r <= INT_MAX:
            return r
    return _num_result(float(a) * float(b))


def _int_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _int_mod(a: int, b: int) -> int:
    r = abs(a) % abs(b)
    return -r if a < 0 else r


def div(a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    if isinstance(a, int) and isinstance(b, int):
        if b == 0:
            return None
        if a == INT_MIN and b == -1:
            return float(a) / -1.0
        return _int_div(a, b)
    b = float(b)
    if b == 0.0:
        return None
    return _num_result(float(a) / b)


def mod(a, b):
    if a is None or b is None:
        return None
    a = to_number(a)
    b = to_number(b)
    if isinstance(a, int) and isinstance(b, int):
        if b == 0:
            return None
        if b == -1:
            return 0
        return _int_mod(a, b)
    ia = a if isinstance(a, int) else float_to_int(a)
    ib = b if isinstance(b, int) else float_to_int(b)
    if ib == 0:
        return None
    if ib == -1:
        ib = 1
    return float(_int_mod(ia, ib))


def _to_int(v) -> int:
    v = to_number(v)
    if isinstance(v, float):
        return float_to_int(v)
    return v


def _wrap64(v: int) -> int:
    v &= (1 << 64) - 1
    return v - (1 << 64) if v >= (1 << 63) else v


def bit_and(a, b):
    if a is None or b is None:
        return None
    return _to_int(a) & _to_int(b)


def bit_or(a, b):
    if a is None or b is None:
        return None
    return _to_int(a) | _to_int(b)


def shift_left(a, b):
    if a is None or b is None:
        return None
    a = _to_int(a)
    b = _to_int(b)
    if b < 0:
        return shift_right(a, -b)
    if b >= 64:
        return 0
    return _wrap64(a << b)


def shift_right(a, b):
    if a is None or b is None:
        return None
    a = _to_int(a)
    b = _to_int(b)
    if b < 0:
        return shift_left(a, -b)
    if b >= 64:
        return -1 if a < 0 else 0
    return a >> b


def bit_not(a):
    if a is None:
        return None
    return ~_to_int(a)


def negate(a):
    if a is None:
        return None
    a = to_number(a)
    if isinstance(a, int):
        if a == INT_MIN:
            return -float(a)
        return -a
    return -a


def concat(a, b):
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)


# ---------------------------------------------------------------------------
# LIKE

_ASCII_LOWER = {c: c + 32 for c in range(ord("A"), ord("Z") + 1)}


def _ascii_lower(s: str) -> str:
    return s.translate(_ASCII_LOWER)


@lru_cache(maxsize=512)
def _like_regex(pattern: str, escape: str | None):
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if escape is not None and ch == escape:
            i += 1
            if i < n:
                out.append(re.escape(pattern[i]))
            i += 1
            continue
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out), re.DOTALL)


def like(value, pattern, escape=None):
    if value is None or pattern is None:
        return None
    value = _ascii_lower(to_text(value))
    pattern = _ascii_lower(to_text(pattern))
    if escape is not None:
        escape = to_text(escape)
        if len(escape) != 1:
            from .errors import SQLError

            raise SQLError("ESCAPE expression must be a single character")
        escape = _ascii_lower(escape)
    return 1 if _like_regex(pattern, escape).fullmatch(value) else 0
