from __future__ import annotations

import math
import re

from .errors import SQLError

_NUMERIC_PREFIX_RE = re.compile(r"^\s*[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?")
_NUMERIC_FULL_RE = re.compile(r"^\s*[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?\s*$")


def _is_real_literal(text: str) -> bool:
    return "." in text or "e" in text or "E" in text


def format_float(value: float) -> str:
    if value != value:  # NaN
        return "nan"
    if math.isinf(value):
        return "Inf" if value > 0 else "-Inf"
    text = repr(value)
    # Python uses e.g. '1e+20' already close to sqlite's formatting; ensure '+' present.
    if "e" in text and "e+" not in text and "e-" not in text:
        text = text.replace("e", "e+")
    return text


def to_text(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format_float(value)
    return str(value)


def to_number_for_arith(value: object) -> int | float:
    """Coerce a value to a number for use in arithmetic, per SQLite text-to-numeric rules."""
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        m = _NUMERIC_PREFIX_RE.match(value)
        if not m or not m.group(0).strip():
            return 0
        text = m.group(0).strip()
        if _is_real_literal(text):
            return float(text)
        return int(text)
    return 0


def coerce_to_column_type(value: object, decl_type: str) -> object:
    if value is None:
        return None
    if decl_type == "INTEGER":
        if isinstance(value, str):
            m = _NUMERIC_FULL_RE.match(value)
            if not m:
                return value
            text = value.strip()
            value = float(text) if _is_real_literal(text) else int(text)
        if isinstance(value, float):
            if value.is_integer() and not math.isinf(value):
                return int(value)
            return value
        return value
    if decl_type == "REAL":
        if isinstance(value, str):
            m = _NUMERIC_FULL_RE.match(value)
            if not m:
                return value
            text = value.strip()
            value = float(text) if _is_real_literal(text) else int(text)
        if isinstance(value, (int, float)):
            return float(value)
        return value
    if decl_type == "TEXT":
        if isinstance(value, (int, float)):
            return to_text(value)
        return value
    raise SQLError(f"Unknown column type {decl_type!r}")


def _trunc_divmod(a: float | int, b: float | int) -> tuple[int | float, int | float]:
    if isinstance(a, int) and isinstance(b, int):
        q = abs(a) // abs(b)
        if (a < 0) != (b < 0):
            q = -q
        r = a - b * q
        return q, r
    q = math.trunc(a / b)
    r = a - b * q
    return float(q), float(r)


def arith(op: str, a: object, b: object) -> object:
    if a is None or b is None:
        return None
    na = to_number_for_arith(a)
    nb = to_number_for_arith(b)
    if op == "+":
        return na + nb
    if op == "-":
        return na - nb
    if op == "*":
        return na * nb
    if op == "/":
        if nb == 0:
            return None
        if isinstance(na, int) and isinstance(nb, int):
            q, _ = _trunc_divmod(na, nb)
            return q
        return na / nb
    if op == "%":
        if nb == 0:
            return None
        _, r = _trunc_divmod(na, nb)
        return r
    raise SQLError(f"Unknown arithmetic operator {op!r}")


def unary_minus(a: object) -> object:
    if a is None:
        return None
    n = to_number_for_arith(a)
    return -n


def concat(a: object, b: object) -> object:
    if a is None or b is None:
        return None
    return to_text(a) + to_text(b)


def _storage_rank(v: object) -> int:
    # NULL < numeric < text (no BLOB support)
    if isinstance(v, (int, float)):
        return 1
    return 2


def compare(op: str, a: object, b: object) -> int | None:
    if a is None or b is None:
        return None
    ra, rb = _storage_rank(a), _storage_rank(b)
    if ra == rb:
        cmp = -1 if a < b else (1 if a > b else 0)
    else:
        cmp = -1 if ra < rb else 1
    if op in ("=", "=="):
        result = cmp == 0
    elif op in ("!=", "<>"):
        result = cmp != 0
    elif op == "<":
        result = cmp < 0
    elif op == "<=":
        result = cmp <= 0
    elif op == ">":
        result = cmp > 0
    elif op == ">=":
        result = cmp >= 0
    else:
        raise SQLError(f"Unknown comparison operator {op!r}")
    return 1 if result else 0


def like_match(text: object, pattern: object) -> int | None:
    if text is None or pattern is None:
        return None
    text = to_text(text) if not isinstance(text, str) else text
    pattern = to_text(pattern) if not isinstance(pattern, str) else pattern
    regex_parts = []
    for ch in pattern:
        if ch == "%":
            regex_parts.append(".*")
        elif ch == "_":
            regex_parts.append(".")
        else:
            regex_parts.append(re.escape(ch))
    regex = "^" + "".join(regex_parts) + "$"
    return 1 if re.match(regex, text, re.IGNORECASE | re.DOTALL) else 0


def truth(v: object) -> bool | None:
    if v is None:
        return None
    if isinstance(v, str):
        return None  # SQLite would error; we treat as unusable in boolean context
    return v != 0


def logical_and(a: object, b: object) -> int | None:
    ta, tb = truth(a), truth(b)
    if ta is False or tb is False:
        return 0
    if ta is None or tb is None:
        return None
    return 1


def logical_or(a: object, b: object) -> int | None:
    ta, tb = truth(a), truth(b)
    if ta is True or tb is True:
        return 1
    if ta is None or tb is None:
        return None
    return 0


def logical_not(a: object) -> int | None:
    t = truth(a)
    if t is None:
        return None
    return 0 if t else 1


def value_sort_key(v: object):
    return v


def compare_for_sort(a: object, b: object) -> int:
    if a is None and b is None:
        return 0
    if a is None:
        return -1
    if b is None:
        return 1
    ra, rb = _storage_rank(a), _storage_rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if a < b:
        return -1
    if a > b:
        return 1
    return 0
