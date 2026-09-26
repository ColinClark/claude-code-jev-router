"""Value semantics mirroring SQLite: affinity, conversion, comparison, arithmetic."""

from __future__ import annotations

import math
import re
import struct
from functools import lru_cache

from minisql.errors import SQLError

INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1

# Affinity names.  ``None`` means "no affinity" (e.g. a literal or computed value).
BLOB = "BLOB"
TEXT = "TEXT"
NUMERIC = "NUMERIC"
INTEGER = "INTEGER"
REAL = "REAL"
NUMERIC_AFFINITIES = frozenset({NUMERIC, INTEGER, REAL})

_SPACES = frozenset(" \t\n\v\f\r")  # sqlite3Isspace()
_DIGITS = frozenset("0123456789")
_U64 = (1 << 64) - 1


def type_affinity(type_name: str) -> str:
    """Column affinity from a declared type name (SQLite section 3.1 rules)."""
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


# ------------------------------------------------------------------ text/number


def _hi_part(d: float) -> float:
    (bits,) = struct.unpack("<Q", struct.pack("<d", d))
    (out,) = struct.unpack("<d", struct.pack("<Q", bits & 0xFFFFFFFFFC000000))
    return out


def _dekker_mul2(x0: float, x1: float, y: float, yy: float) -> tuple[float, float]:
    """Double-double multiply, a direct port of SQLite's dekkerMul2()."""
    hx = _hi_part(x0)
    tx = x0 - hx
    hy = _hi_part(y)
    ty = y - hy
    p = hx * hy
    q = hx * ty + tx * hy
    c = p + q
    cc = p - c + q + tx * ty
    cc = x0 * yy + x1 * y + cc
    r0 = c + cc
    r1 = c - r0
    r1 += cc
    return r0, r1


def _fp_decode(r: float, i_round: int) -> tuple[str, int]:
    """Port of sqlite3FpDecode() for finite, positive *r*: returns (digits, iDP) where the
    value is 0.<digits> * 10**iDP, rounded half-up to *i_round* significant digits."""
    exp = 0
    r0, r1 = r, 0.0
    if r0 > 9.223372036854774784e18:
        while r0 > 9.223372036854774784e118:
            exp += 100
            r0, r1 = _dekker_mul2(r0, r1, 1.0e-100, -1.99918998026028836196e-117)
        while r0 > 9.223372036854774784e28:
            exp += 10
            r0, r1 = _dekker_mul2(r0, r1, 1.0e-10, -3.6432197315497741579e-27)
        while r0 > 9.223372036854774784e18:
            exp += 1
            r0, r1 = _dekker_mul2(r0, r1, 1.0e-01, -5.5511151231257827021e-18)
    else:
        while r0 < 9.223372036854774784e-83:
            exp -= 100
            r0, r1 = _dekker_mul2(r0, r1, 1.0e100, -1.5902891109759918046e83)
        while r0 < 9.223372036854774784e07:
            exp -= 10
            r0, r1 = _dekker_mul2(r0, r1, 1.0e10, 0.0)
        while r0 < 9.22337203685477478e17:
            exp -= 1
            r0, r1 = _dekker_mul2(r0, r1, 1.0e01, 0.0)
    v = int(r0) - int(-r1) if r1 < 0.0 else int(r0) + int(r1)
    digits = list(str(v))
    idp = len(digits) + exp
    if i_round < len(digits):
        tail = digits[i_round]
        digits = digits[:i_round]
        if tail >= "5":
            j = i_round - 1
            while True:
                if digits[j] != "9":
                    digits[j] = chr(ord(digits[j]) + 1)
                    break
                digits[j] = "0"
                if j == 0:
                    digits.insert(0, "1")
                    idp += 1
                    break
                j -= 1
    text = "".join(digits).rstrip("0")
    return text or "0", idp


def format_real(x: float) -> str:
    """Render a float the way SQLite does (printf ``%!.15g`` via sqlite3FpDecode)."""
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Inf" if x > 0 else "-Inf"
    if x == 0:
        return "0.0"
    sign = ""
    if x < 0:
        sign = "-"
        x = -x
    digits, idp = _fp_decode(x, 15)
    exp = idp - 1
    if exp < -4 or exp > 14:
        mant = digits[0] + "." + (digits[1:] or "0")
        return f"{sign}{mant}e{'-' if exp < 0 else '+'}{abs(exp):02d}"
    if idp <= 0:
        return f"{sign}0.{'0' * -idp}{digits}"
    if idp >= len(digits):
        return f"{sign}{digits}{'0' * (idp - len(digits))}.0"
    return f"{sign}{digits[:idp]}.{digits[idp:]}"


def to_text(v: object) -> str:
    if type(v) is str:
        return v
    if type(v) is int:
        return str(v)
    if type(v) is float:
        return format_real(v)
    raise TypeError(f"unexpected value {v!r}")


def sqlite_atof(z: str) -> tuple[float, int]:
    """Port of sqlite3AtoF(): returns ``(value, rc)``.

    rc is 1 for a pure integer, 2 or 3 for a real (decimal point and/or exponent) when the
    whole string (bar surrounding whitespace) is a number; -1 when a real-looking prefix is
    followed by junk; 0 otherwise.  *value* is the value of the numeric prefix."""
    n = len(z)
    i = 0
    while i < n and z[i] in _SPACES:
        i += 1
    if i >= n:
        return 0.0, 0
    sign = 1
    if z[i] == "-":
        sign = -1
        i += 1
    elif z[i] == "+":
        i += 1
    s = 0
    d = 0
    esign = 1
    e = 0
    e_valid = True
    n_digit = 0
    e_type = 1
    limit = (_U64 - 9) // 10
    while i < n and z[i] in _DIGITS:
        s = s * 10 + (ord(z[i]) - 48)
        i += 1
        n_digit += 1
        if s >= limit:
            while i < n and z[i] in _DIGITS:
                i += 1
                d += 1
    if i < n and z[i] == ".":
        i += 1
        e_type += 1
        while i < n and z[i] in _DIGITS:
            if s < limit:
                s = s * 10 + (ord(z[i]) - 48)
                d -= 1
                n_digit += 1
            i += 1
    if i < n and z[i] in "eE":
        i += 1
        e_valid = False
        e_type += 1
        if i < n:
            if z[i] == "-":
                esign = -1
                i += 1
            elif z[i] == "+":
                i += 1
            while i < n and z[i] in _DIGITS:
                e = e * 10 + (ord(z[i]) - 48) if e < 10000 else 10000
                i += 1
                e_valid = True
        while i < n and z[i] in _SPACES:
            i += 1
    else:
        while i < n and z[i] in _SPACES:
            i += 1

    if s == 0:
        result = -0.0 if sign < 0 else 0.0
    else:
        e = e * esign + d
        while e > 0 and s < (_U64 - 0x7FF) // 10:
            s *= 10
            e -= 1
        while e < 0 and s % 10 == 0:
            s //= 10
            e += 1
        r0 = float(s)
        if r0 <= 18446744073709549568.0:
            s2 = int(r0)
            r1 = float(s - s2) if s >= s2 else -float(s2 - s)
        else:
            r1 = 0.0
        if e > 0:
            while e >= 100:
                e -= 100
                r0, r1 = _dekker_mul2(r0, r1, 1.0e100, -1.5902891109759918046e83)
            while e >= 10:
                e -= 10
                r0, r1 = _dekker_mul2(r0, r1, 1.0e10, 0.0)
            while e >= 1:
                e -= 1
                r0, r1 = _dekker_mul2(r0, r1, 1.0e01, 0.0)
        else:
            while e <= -100:
                e += 100
                r0, r1 = _dekker_mul2(r0, r1, 1.0e-100, -1.99918998026028836196e-117)
            while e <= -10:
                e += 10
                r0, r1 = _dekker_mul2(r0, r1, 1.0e-10, -3.6432197315497741579e-27)
            while e <= -1:
                e += 1
                r0, r1 = _dekker_mul2(r0, r1, 1.0e-01, -5.5511151231257827021e-18)
        result = r0 + r1
        if result != result:
            result = math.inf
        if sign < 0:
            result = -result
    if i == n and n_digit > 0 and e_valid:
        return result, e_type
    if e_type >= 2 and (e_type == 3 or e_valid) and n_digit > 0:
        return result, -1
    return result, 0


def sqlite_atoi64(z: str) -> tuple[int, int]:
    """Port of sqlite3Atoi64(): returns ``(value, rc)``.

    rc: 0 exact fit, 1 trailing non-space text, -1 no digits, 2 overflow,
    3 exactly 9223372036854775808 (positive)."""
    n = len(z)
    i = 0
    while i < n and z[i] in _SPACES:
        i += 1
    neg = False
    if i < n:
        if z[i] == "-":
            neg = True
            i += 1
        elif z[i] == "+":
            i += 1
    start = i
    while i < n and z[i] == "0":
        i += 1
    j = i
    u = 0
    while j < n and z[j] in _DIGITS:
        u = (u * 10 + ord(z[j]) - 48) & _U64
        j += 1
    ndig = j - i
    if u > INT64_MAX:
        value = INT64_MIN if neg else INT64_MAX
    else:
        value = -u if neg else u
    rc = 0
    if ndig == 0 and start == i:
        rc = -1
    elif j < n and any(ch not in _SPACES for ch in z[j:]):
        rc = 1
    if ndig < 19:
        return value, rc
    c = 1 if ndig > 19 else (z[i:j] > "9223372036854775808") - (z[i:j] < "9223372036854775808")
    if c < 0:
        return value, rc
    value = INT64_MIN if neg else INT64_MAX
    if c > 0:
        return value, 2
    return value, (rc if neg else 3)


def parse_full_number(s: str) -> int | float | None:
    """applyNumericAffinity(): the numeric value if *s* (ignoring surrounding whitespace) is
    entirely a well-formed number, else ``None``.  Integers that fit in 64 bits are ints."""
    r, rc = sqlite_atof(s)
    if rc <= 0:
        return None
    if rc == 1:
        iv = real_to_int64(r)
        if _real_same_as_int(r, iv):
            return iv
        iv, irc = sqlite_atoi64(s)
        if irc == 0:
            return iv
    return r


def _real_same_as_int(r: float, i: int) -> bool:
    """sqlite3RealSameAsInt()."""
    return r == 0.0 or (float(i) == r and -2251799813685248 <= i < 2251799813685248)


def numeric_affinity(v: object) -> object:
    """Apply NUMERIC affinity for comparisons (text that looks like a number)."""
    if type(v) is str:
        num = parse_full_number(v)
        if num is not None:
            return num
    return v


def real_to_int_if_exact(x: float) -> int | float:
    """sqlite3VdbeIntegerAffinity()."""
    if math.isfinite(x):
        i = real_to_int64(x)
        if x == i and INT64_MIN < i < INT64_MAX:
            return i
    return x


def apply_storage_affinity(v: object, affinity: str) -> object:
    """Convert a value being stored into a column with the given affinity."""
    if v is None:
        return None
    if affinity == TEXT:
        return to_text(v)
    if affinity == BLOB:
        return v
    if type(v) is str:
        num = parse_full_number(v)
        if num is None:
            return v
        v = num
    if affinity == REAL:
        return float(v)  # type: ignore[arg-type]
    # INTEGER / NUMERIC
    if type(v) is float:
        return real_to_int_if_exact(v)
    return v


def to_number(v: object) -> int | float:
    """Numeric value used by arithmetic operators (computeNumericType())."""
    t = type(v)
    if t is int or t is float:
        return v  # type: ignore[return-value]
    s: str = v  # type: ignore[assignment]
    r, rc = sqlite_atof(s)
    if rc <= 0:
        if rc == 0:
            iv, irc = sqlite_atoi64(s)
            if irc <= 1:
                return iv
        return r
    if rc == 1:
        iv, irc = sqlite_atoi64(s)
        if irc == 0:
            return iv
    return r


def numerify(s: str) -> int | float:
    """sqlite3VdbeMemNumerify() for text (used by CAST AS NUMERIC)."""
    r, rc = sqlite_atof(s)
    if rc in (0, 1):
        iv, irc = sqlite_atoi64(s)
        if irc <= 1:
            return iv
    iv = real_to_int64(r)
    if _real_same_as_int(r, iv):
        return iv
    return r


def to_real(v: object) -> float:
    """sqlite3VdbeRealValue()."""
    t = type(v)
    if t is float:
        return v  # type: ignore[return-value]
    if t is int:
        return float(v)  # type: ignore[arg-type]
    if v is None:
        return 0.0
    return sqlite_atof(v)[0]  # type: ignore[arg-type]


def real_to_int64(x: float) -> int:
    """doubleToInt64(): saturating truncation."""
    if math.isnan(x):
        return 0
    if x <= -9.223372036854775808e18:
        return INT64_MIN
    if x >= 9.223372036854775808e18:
        return INT64_MAX
    return int(x)


def to_int(v: object) -> int:
    """sqlite3VdbeIntValue()."""
    t = type(v)
    if t is int:
        return v  # type: ignore[return-value]
    if t is float:
        return real_to_int64(v)  # type: ignore[arg-type]
    if v is None:
        return 0
    return sqlite_atoi64(v)[0]  # type: ignore[arg-type]


def truth(v: object) -> bool | None:
    """SQL truth value: None for NULL."""
    if v is None:
        return None
    t = type(v)
    if t is int or t is float:
        return v != 0
    return to_real(v) != 0.0


# ------------------------------------------------------------------ comparison


def compare(a: object, b: object) -> int:
    """Compare two non-NULL values: numbers < text; text compared by code point."""
    sa = type(a) is str
    sb = type(b) is str
    if sa != sb:
        return 1 if sa else -1
    if a < b:  # type: ignore[operator]
        return -1
    if a > b:  # type: ignore[operator]
        return 1
    return 0


def compare_full(a: object, b: object) -> int:
    """Compare including NULL (NULL sorts first)."""
    if a is None:
        return 0 if b is None else -1
    if b is None:
        return 1
    return compare(a, b)


def comparison_affinity(a1: str | None, a2: str | None) -> str | None:
    """Affinity applied to the operands of a binary comparison (SQLite rules)."""
    if a1 is not None and a2 is not None:
        if a1 in NUMERIC_AFFINITIES or a2 in NUMERIC_AFFINITIES:
            return NUMERIC
        return None
    a = a1 if a1 is not None else a2
    if a is None or a == BLOB:
        return None
    return NUMERIC if a in NUMERIC_AFFINITIES else TEXT


def apply_compare_affinity(a: object, b: object, aff: str | None) -> tuple[object, object]:
    if aff is None:
        return a, b
    if aff == TEXT:
        if type(a) is str or type(b) is str:
            if type(a) is not str:
                a = to_text(a)
            if type(b) is not str:
                b = to_text(b)
        return a, b
    if type(a) is str:
        a = numeric_affinity(a)
    if type(b) is str:
        b = numeric_affinity(b)
    return a, b


def sort_key(v: object) -> tuple[int, object]:
    if v is None:
        return (0, 0)
    if type(v) is str:
        return (2, v)
    return (1, v)


# ------------------------------------------------------------------ arithmetic


def _real_result(r: float) -> float | None:
    if r != r:  # NaN
        return None
    return r


# The arithmetic operators follow SQLite's OP_Add/OP_Subtract/OP_Multiply/OP_Divide/
# OP_Remainder: integer math when both operands have (or convert to) integer type and no
# overflow occurs, otherwise real math on sqlite3VdbeRealValue() of the original operands.


def op_add(a: object, b: object) -> object:
    if a is None or b is None:
        return None
    x = to_number(a)
    y = to_number(b)
    if type(x) is int and type(y) is int:
        r = x + y
        if INT64_MIN <= r <= INT64_MAX:
            return r
    return _real_result(to_real(a) + to_real(b))


def op_sub(a: object, b: object) -> object:
    if a is None or b is None:
        return None
    x = to_number(a)
    y = to_number(b)
    if type(x) is int and type(y) is int:
        r = x - y
        if INT64_MIN <= r <= INT64_MAX:
            return r
    return _real_result(to_real(a) - to_real(b))


def op_mul(a: object, b: object) -> object:
    if a is None or b is None:
        return None
    x = to_number(a)
    y = to_number(b)
    if type(x) is int and type(y) is int:
        r = x * y
        if INT64_MIN <= r <= INT64_MAX:
            return r
    return _real_result(to_real(a) * to_real(b))


def op_div(a: object, b: object) -> object:
    if a is None or b is None:
        return None
    x = to_number(a)
    y = to_number(b)
    if type(x) is int and type(y) is int:
        if y == 0:
            return None
        if not (x == INT64_MIN and y == -1):
            q = abs(x) // abs(y)
            return -q if (x < 0) != (y < 0) else q
    divisor = to_real(b)
    if divisor == 0.0:
        return None
    return _real_result(to_real(a) / divisor)


def _c_rem(x: int, y: int) -> int:
    r = abs(x) % abs(y)
    return -r if x < 0 else r


def op_mod(a: object, b: object) -> object:
    if a is None or b is None:
        return None
    x = to_number(a)
    y = to_number(b)
    if type(x) is int and type(y) is int:
        if y == 0:
            return None
        if y == -1:
            return 0
        return _c_rem(x, y)
    ix = to_int(a)
    iy = to_int(b)
    if iy == 0:
        return None
    if iy == -1:
        iy = 1
    return float(_c_rem(ix, iy))


def op_concat(a: object, b: object) -> object:
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)


def _wrap64(v: int) -> int:
    v &= (1 << 64) - 1
    return v - (1 << 64) if v >= 1 << 63 else v


def op_bitand(a: object, b: object) -> object:
    if a is None or b is None:
        return None
    return to_int(a) & to_int(b)


def op_bitor(a: object, b: object) -> object:
    if a is None or b is None:
        return None
    return to_int(a) | to_int(b)


def _shift(a: object, b: object, left: bool) -> object:
    if a is None or b is None:
        return None
    x = to_int(a)
    y = to_int(b)
    if y < 0:
        left = not left
        y = -y if y > -64 else 64
    if y >= 64:
        return 0 if (x >= 0 or left) else -1
    if left:
        return _wrap64(x << y)
    return x >> y


def op_shl(a: object, b: object) -> object:
    return _shift(a, b, True)


def op_shr(a: object, b: object) -> object:
    return _shift(a, b, False)


def op_negate(a: object) -> object:
    return op_sub(0, a)


def op_bitnot(a: object) -> object:
    if a is None:
        return None
    return ~to_int(a)


# ------------------------------------------------------------------ LIKE / GLOB

_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def ascii_lower(s: str) -> str:
    return s.translate(_ASCII_LOWER)


_ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def ascii_upper(s: str) -> str:
    return s.translate(_ASCII_UPPER)


@lru_cache(maxsize=4096)
def _like_regex(pattern: str, escape: str | None) -> re.Pattern[str] | None:
    parts: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if escape is not None and ch == escape:
            i += 1
            if i >= n:
                return None
            parts.append(re.escape(pattern[i]))
        elif ch == "%":
            if not parts or parts[-1] != ".*":
                parts.append(".*")
        elif ch == "_":
            parts.append(".")
        else:
            parts.append(re.escape(ch))
        i += 1
    return re.compile("".join(parts), re.DOTALL)


def like(value: object, pattern: object, escape: object = None) -> int | None:
    if value is None or pattern is None:
        return None
    esc = None
    if escape is not None:
        esc = to_text(escape)
        if len(esc) != 1:
            raise SQLError("ESCAPE expression must be a single character")
        esc = ascii_lower(esc)
    rx = _like_regex(ascii_lower(to_text(pattern)), esc)
    if rx is None:
        return 0
    return 1 if rx.fullmatch(ascii_lower(to_text(value))) else 0


@lru_cache(maxsize=4096)
def _glob_regex(pattern: str) -> re.Pattern[str] | None:
    parts: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            parts.append(".*")
        elif ch == "?":
            parts.append(".")
        elif ch == "[":
            j = i + 1
            negate = False
            if j < n and pattern[j] == "^":
                negate = True
                j += 1
            items: list[str] = []
            if j < n and pattern[j] == "]":
                items.append(re.escape("]"))
                j += 1
            while j < n and pattern[j] != "]":
                if j + 2 < n and pattern[j + 1] == "-" and pattern[j + 2] != "]":
                    items.append(re.escape(pattern[j]) + "-" + re.escape(pattern[j + 2]))
                    j += 3
                else:
                    items.append(re.escape(pattern[j]))
                    j += 1
            if j >= n:
                return None
            parts.append("[" + ("^" if negate else "") + "".join(items) + "]")
            i = j
        else:
            parts.append(re.escape(ch))
        i += 1
    return re.compile("".join(parts), re.DOTALL)


def glob(value: object, pattern: object) -> int | None:
    if value is None or pattern is None:
        return None
    rx = _glob_regex(to_text(pattern))
    if rx is None:
        return 0
    return 1 if rx.fullmatch(to_text(value)) else 0


def typeof(v: object) -> str:
    if v is None:
        return "null"
    t = type(v)
    if t is int:
        return "integer"
    if t is float:
        return "real"
    return "text"
