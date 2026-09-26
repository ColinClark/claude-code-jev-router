"""SQLite-compatible value semantics: affinity, conversion, comparison, arithmetic."""

import math
import re
from decimal import Decimal

from minisql.errors import SQLError

INT_MIN = -(1 << 63)
INT_MAX = (1 << 63) - 1

INTEGER = "INTEGER"
REAL = "REAL"
TEXT = "TEXT"
NUMERIC = "NUMERIC"
BLOB = "BLOB"
NUMERIC_AFFINITIES = (INTEGER, REAL, NUMERIC)

_EXACT_NUMBER = re.compile(r"\s*[+-]?(?:\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\s*\Z")
_NUMBER_PREFIX = re.compile(r"\s*([+-]?(?:\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?)")


def type_affinity(type_name: str) -> str:
    """Column affinity from a declared type name, following SQLite's rules."""
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


def _int_or_float(text: str, is_int: bool):
    if is_int:
        value = int(text)
        if INT_MIN <= value <= INT_MAX:
            return value
    return float(text)


def parse_exact_number(text: str):
    """Return the number if `text` is entirely a well-formed number, else None."""
    m = _EXACT_NUMBER.match(text)
    if not m:
        return None
    return _int_or_float(text.strip(), m.group(1) is None and m.group(2) is None)


def text_to_number(text: str):
    """Convert text to a number the way SQLite arithmetic does (longest numeric prefix)."""
    m = _NUMBER_PREFIX.match(text)
    if not m:
        return 0
    return _int_or_float(m.group(1), m.group(2) is None and m.group(3) is None)


def to_numeric(value):
    """Operand conversion for arithmetic. `value` must not be None."""
    if isinstance(value, str):
        return text_to_number(value)
    return value


def float_to_text(f: float) -> str:
    if math.isinf(f):
        return "Inf" if f > 0 else "-Inf"
    if f == 0:
        return "0.0"
    # SQLite renders reals like printf("%!.15g"): 15 significant digits, trailing zeros
    # removed, and exponent notation outside 1e-4 <= |f| < 1e15.
    text = f"{f:.14e}"
    sign, digits, exp = Decimal(text).normalize().as_tuple()
    sci = len(digits) + exp - 1
    prefix = "-" if sign else ""
    if -4 <= sci < 15:
        text = format(abs(Decimal(text).normalize()), "f")
        if "." not in text:
            text += ".0"
        return prefix + text
    ds = "".join(map(str, digits))
    mantissa = ds[0] + "." + (ds[1:] or "0")
    return f"{prefix}{mantissa}e{sci:+03d}"


def to_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        return float_to_text(value)
    return str(value)


def float_to_int_if_exact(value):
    if isinstance(value, float) and value.is_integer() and -(2.0**63) <= value < 2.0**63:
        return int(value)
    return value


def apply_storage_affinity(value, affinity: str):
    """Convert a value being stored into a column with the given affinity."""
    if value is None:
        return None
    if affinity == TEXT:
        return to_text(value) if not isinstance(value, str) else value
    if affinity in (INTEGER, NUMERIC):
        if isinstance(value, str):
            num = parse_exact_number(value)
            if num is None:
                return value
            value = num
        return float_to_int_if_exact(value)
    if affinity == REAL:
        if isinstance(value, str):
            num = parse_exact_number(value)
            return value if num is None else float(num)
        return float(value)
    return value


def numeric_affinity(value):
    """Numeric affinity as applied to comparison operands."""
    if isinstance(value, str):
        num = parse_exact_number(value)
        return value if num is None else num
    return value


def text_affinity(value):
    if value is None or isinstance(value, str):
        return value
    return to_text(value)


def comparison_converters(left_aff, right_aff):
    """Which conversions to apply to (left, right) operands of a comparison."""
    left_num = left_aff in NUMERIC_AFFINITIES
    right_num = right_aff in NUMERIC_AFFINITIES
    if left_num and not right_num:
        return None, numeric_affinity
    if right_num and not left_num:
        return numeric_affinity, None
    if left_aff == TEXT and right_aff is None:
        return None, text_affinity
    if right_aff == TEXT and left_aff is None:
        return text_affinity, None
    return None, None


def in_list_converter(left_aff):
    """Conversion applied to both operands of `x IN (list)` comparisons."""
    if left_aff in NUMERIC_AFFINITIES:
        return numeric_affinity
    if left_aff == TEXT:
        return text_affinity
    return None


def sort_key(value):
    """Key ordering values as SQLite does: NULL < numbers < text."""
    if value is None:
        return (0, 0)
    if isinstance(value, str):
        return (2, value)
    return (1, value)


def compare(a, b) -> int:
    ka, kb = sort_key(a), sort_key(b)
    return (ka > kb) - (ka < kb)


def truth(value):
    """Three-valued truth: None for NULL, else bool."""
    if value is None:
        return None
    if isinstance(value, str):
        value = text_to_number(value)
    return value != 0


def is_true(value) -> bool:
    return truth(value) is True


def _int_result(value):
    if INT_MIN <= value <= INT_MAX:
        return value
    return None


def arith(op: str, a, b):
    if a is None or b is None:
        return None
    if op == "||":
        return to_text(a) + to_text(b)
    a = to_numeric(a)
    b = to_numeric(b)
    both_int = isinstance(a, int) and isinstance(b, int)
    if op == "+":
        if both_int:
            r = _int_result(a + b)
            return r if r is not None else float(a) + float(b)
        return float(a) + float(b)
    if op == "-":
        if both_int:
            r = _int_result(a - b)
            return r if r is not None else float(a) - float(b)
        return float(a) - float(b)
    if op == "*":
        if both_int:
            r = _int_result(a * b)
            return r if r is not None else float(a) * float(b)
        return float(a) * float(b)
    if op == "/":
        if both_int:
            if b == 0:
                return None
            if a == INT_MIN and b == -1:
                return float(a) / float(b)
            q = abs(a) // abs(b)
            return q if (a < 0) == (b < 0) else -q
        if float(b) == 0.0:
            return None
        return float(a) / float(b)
    if op == "%":
        if both_int:
            return _int_mod(a, b)
        # Real operands are truncated to integers; integer operands are used as-is.
        ia = a if isinstance(a, int) else _float_to_i64(a)
        ib = b if isinstance(b, int) else _float_to_i64(b)
        r = _int_mod(ia, ib)
        return None if r is None else float(r)
    raise SQLError(f"unknown operator {op}")


def _float_to_i64(f: float) -> int:
    if math.isnan(f):
        return 0
    if f >= 2.0**63:
        return INT_MAX
    if f < -(2.0**63):
        return INT_MIN
    return int(f)


def _int_mod(a: int, b: int):
    if b == 0:
        return None
    r = abs(a) % abs(b)
    return -r if a < 0 else r


def negate(value):
    # SQLite evaluates unary minus as (0 - value).
    return arith("-", 0, value)
