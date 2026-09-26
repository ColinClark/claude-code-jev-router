"""Expression evaluation with SQLite semantics.

Key pieces:

* :class:`Source` / :class:`Scope` describe which columns are visible to an
  expression (one ``Source`` per table in the FROM clause, named by its alias
  or table name).  ``Scope.resolve`` turns a ``ColumnRef`` into a
  ``(source_index, column_index)`` pair and raises ``SQLError`` for unknown or
  ambiguous columns.
* :class:`RowContext` binds a scope to concrete rows (one tuple per source, or
  ``None`` for a NULL-extended source in a LEFT JOIN) plus an optional mapping
  of aggregate-call nodes to precomputed values (for grouped SELECTs).
* :func:`eval_expr` evaluates an expression node against a ``RowContext``.
* :func:`validate_expr` statically checks an expression against a scope
  (unknown columns/functions, misuse of aggregates) so errors are raised even
  when a table has no rows.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache

from .errors import SQLError
from .nodes import (
    Between,
    BinaryOp,
    Case,
    Cast,
    ColumnRef,
    Expr,
    FunctionCall,
    InList,
    IsNull,
    Like,
    Literal,
    UnaryOp,
    is_aggregate_call,
    iter_children,
)
from .values import (
    BLOB,
    INTEGER,
    MAX_INT64,
    MIN_INT64,
    NUMERIC,
    REAL,
    TEXT,
    apply_numeric_affinity_for_compare,
    compare_values,
    fits_int64,
    float_to_int_if_exact,
    is_true,
    text_to_number,
    to_number,
    to_numeric_prefix,
    to_text,
    type_affinity,
)

# ---------------------------------------------------------------------------
# Scopes and row contexts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    """A named set of columns visible to expressions (a table in FROM)."""

    name: str  # qualifier: alias if given, else table name
    columns: tuple[str, ...]
    affinities: tuple[str, ...]

    def column_index(self, name: str) -> int | None:
        lname = name.lower()
        for i, c in enumerate(self.columns):
            if c.lower() == lname:
                return i
        return None


class Scope:
    """Column-name resolution over one or more sources."""

    def __init__(self, sources: Sequence[Source] = ()):
        self.sources: tuple[Source, ...] = tuple(sources)
        self._cache: dict[ColumnRef, tuple[int, int]] = {}

    def resolve(self, ref: ColumnRef) -> tuple[int, int]:
        hit = self._cache.get(ref)
        if hit is not None:
            return hit
        display = f"{ref.table}.{ref.name}" if ref.table else ref.name
        if ref.table is not None:
            lt = ref.table.lower()
            matches = [i for i, s in enumerate(self.sources) if s.name.lower() == lt]
            if not matches:
                raise SQLError(f"no such column: {display}")
            if len(matches) > 1:
                raise SQLError(f"ambiguous column name: {display}")
            si = matches[0]
            ci = self.sources[si].column_index(ref.name)
            if ci is None:
                raise SQLError(f"no such column: {display}")
            result = (si, ci)
        else:
            found: list[tuple[int, int]] = []
            for si, s in enumerate(self.sources):
                ci = s.column_index(ref.name)
                if ci is not None:
                    found.append((si, ci))
            if not found:
                raise SQLError(f"no such column: {display}")
            if len(found) > 1:
                raise SQLError(f"ambiguous column name: {display}")
            result = found[0]
        self._cache[ref] = result
        return result

    def affinity(self, ref: ColumnRef) -> str:
        si, ci = self.resolve(ref)
        return self.sources[si].affinities[ci]


EMPTY_SCOPE = Scope()


class RowContext:
    """Concrete values for evaluating expressions.

    ``rows[i]`` is the current row (tuple) of ``scope.sources[i]``, or ``None``
    when that source is NULL-extended (LEFT JOIN without a match).
    ``aggregates`` maps aggregate ``FunctionCall`` nodes to their value for the
    current group; if it is ``None``, evaluating an aggregate raises SQLError.
    """

    __slots__ = ("aggregates", "rows", "scope")

    def __init__(
        self,
        scope: Scope,
        rows: Sequence[tuple | None] = (),
        aggregates: Mapping[Expr, object] | None = None,
    ):
        self.scope = scope
        self.rows = rows
        self.aggregates = aggregates

    def lookup(self, ref: ColumnRef) -> object:
        si, ci = self.scope.resolve(ref)
        row = self.rows[si]
        return None if row is None else row[ci]


EMPTY_CONTEXT = RowContext(EMPTY_SCOPE, ())


# ---------------------------------------------------------------------------
# Static validation and affinity
# ---------------------------------------------------------------------------

# name -> (min_args, max_args) ; max None = unbounded
SCALAR_FUNCTIONS: dict[str, tuple[int, int | None]] = {
    "ABS": (1, 1),
    "LENGTH": (1, 1),
    "LOWER": (1, 1),
    "UPPER": (1, 1),
    "COALESCE": (2, None),
    "IFNULL": (2, 2),
    "NULLIF": (2, 2),
    "TYPEOF": (1, 1),
    "MIN": (2, None),
    "MAX": (2, None),
    "SUBSTR": (2, 3),
    "SUBSTRING": (2, 3),
    "ROUND": (1, 2),
    "TRIM": (1, 2),
    "LTRIM": (1, 2),
    "RTRIM": (1, 2),
    "REPLACE": (3, 3),
    "INSTR": (2, 2),
}

AGGREGATE_ARITY: dict[str, tuple[int, int]] = {
    "COUNT": (0, 1),
    "SUM": (1, 1),
    "AVG": (1, 1),
    "MIN": (1, 1),
    "MAX": (1, 1),
    "TOTAL": (1, 1),
    "GROUP_CONCAT": (1, 2),
}


def validate_expr(node: Expr, scope: Scope, allow_aggregates: bool = False) -> None:
    """Raise SQLError for unknown columns/functions or misplaced aggregates.

    With ``allow_aggregates=True`` aggregate calls are accepted, but nested
    aggregates (an aggregate inside another aggregate's arguments) are not.
    """
    if isinstance(node, ColumnRef):
        scope.resolve(node)
        return
    if isinstance(node, FunctionCall):
        if is_aggregate_call(node):
            if not allow_aggregates:
                raise SQLError(f"misuse of aggregate function {node.name.lower()}()")
            lo, hi = AGGREGATE_ARITY[node.name]
            n = len(node.args)
            if node.star:
                if node.name != "COUNT":
                    raise SQLError(f"wrong number of arguments to function {node.name.lower()}()")
            elif not lo <= n <= hi or (node.name == "COUNT" and n == 0):
                raise SQLError(f"wrong number of arguments to function {node.name.lower()}()")
            if node.distinct and n != 1:
                raise SQLError(
                    "DISTINCT aggregates must have exactly one argument"
                )
            for arg in node.args:
                validate_expr(arg, scope, allow_aggregates=False)
            return
        spec = SCALAR_FUNCTIONS.get(node.name)
        if spec is None:
            raise SQLError(f"no such function: {node.name}")
        lo, hi = spec
        n = len(node.args)
        if node.star or node.distinct or n < lo or (hi is not None and n > hi):
            raise SQLError(f"wrong number of arguments to function {node.name.lower()}()")
    for child in iter_children(node):
        validate_expr(child, scope, allow_aggregates)


def expr_affinity(node: Expr, scope: Scope) -> str | None:
    """Affinity of an expression for comparison purposes (None = no affinity)."""
    if isinstance(node, ColumnRef):
        return scope.affinity(node)
    if isinstance(node, Cast):
        return type_affinity(node.type_name)
    return None


_NUMERIC_AFFS = (INTEGER, REAL, NUMERIC)


def _coerce_pair(a: object, b: object, aff_a: str | None, aff_b: str | None) -> tuple[object, object]:
    """Apply SQLite's comparison affinity rules to two non-NULL operands."""
    none_a = aff_a is None or aff_a == BLOB
    none_b = aff_b is None or aff_b == BLOB
    if aff_a in _NUMERIC_AFFS and (none_b or aff_b == TEXT):
        b = apply_numeric_affinity_for_compare(b)
    elif aff_b in _NUMERIC_AFFS and (none_a or aff_a == TEXT):
        a = apply_numeric_affinity_for_compare(a)
    elif aff_a == TEXT and none_b and isinstance(b, (int, float)):
        b = to_text(b)
    elif aff_b == TEXT and none_a and isinstance(a, (int, float)):
        a = to_text(a)
    return a, b


def sql_compare(a: object, b: object, aff_a: str | None = None, aff_b: str | None = None) -> int | None:
    """Three-way comparison with NULL propagation (None if either is NULL)."""
    if a is None or b is None:
        return None
    a, b = _coerce_pair(a, b, aff_a, aff_b)
    return compare_values(a, b)


# ---------------------------------------------------------------------------
# Arithmetic helpers
# ---------------------------------------------------------------------------


def _int_or_float(v: int) -> int | float:
    return v if fits_int64(v) else float(v)


def _real_result(f: float) -> float | None:
    return None if math.isnan(f) else f


def arithmetic(op: str, a: object, b: object) -> object:
    if a is None or b is None:
        return None
    x = to_number(a)
    y = to_number(b)
    if op == "%":
        xi = _to_int_trunc(x)
        yi = _to_int_trunc(y)
        if yi == 0:
            return None
        r = abs(xi) % abs(yi)
        if xi < 0:
            r = -r
        if isinstance(x, float) or isinstance(y, float):
            return float(r)
        return r
    if isinstance(x, int) and isinstance(y, int):
        if op == "+":
            return _int_or_float(x + y)
        if op == "-":
            return _int_or_float(x - y)
        if op == "*":
            return _int_or_float(x * y)
        if op == "/":
            if y == 0:
                return None
            q = abs(x) // abs(y)
            if (x < 0) != (y < 0):
                q = -q
            return _int_or_float(q)
        raise AssertionError(op)
    fx, fy = float(x), float(y)  # type: ignore[arg-type]
    try:
        if op == "+":
            return _real_result(fx + fy)
        if op == "-":
            return _real_result(fx - fy)
        if op == "*":
            return _real_result(fx * fy)
        if op == "/":
            if fy == 0.0:
                return None
            return _real_result(fx / fy)
    except OverflowError:
        return math.inf
    raise AssertionError(op)


def _to_int_trunc(v: object) -> int:
    """Convert a number to a 64-bit integer the way CAST(x AS INTEGER) does."""
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if math.isnan(v):
            return 0
        if v >= 9.223372036854775807e18:
            return MAX_INT64
        if v <= -9.223372036854775808e18:
            return MIN_INT64
        return int(v)
    if isinstance(v, str):
        return _to_int_trunc(to_numeric_prefix(v))
    return 0


def _wrap64(v: int) -> int:
    v &= 0xFFFFFFFFFFFFFFFF
    return v - 2**64 if v > MAX_INT64 else v


def bitwise(op: str, a: object, b: object) -> object:
    if a is None or b is None:
        return None
    x = _to_int_trunc(to_number(a))
    y = _to_int_trunc(to_number(b))
    if op == "&":
        return x & y
    if op == "|":
        return x | y
    if op in ("<<", ">>"):
        if op == ">>":
            y = -y
        if y >= 0:
            return 0 if y >= 64 else _wrap64(x << y)
        y = -y
        if y >= 64:
            return -1 if x < 0 else 0
        return x >> y
    raise AssertionError(op)


def cast_value(v: object, type_name: str) -> object:
    if v is None:
        return None
    aff = type_affinity(type_name)
    if aff == TEXT:
        return to_text(v)
    if aff == BLOB:
        return v
    if aff == INTEGER:
        if isinstance(v, str):
            v = to_numeric_prefix(v)
        return _to_int_trunc(v)
    if aff == REAL:
        if isinstance(v, str):
            v = to_numeric_prefix(v)
        return float(v)  # type: ignore[arg-type]
    # NUMERIC
    if isinstance(v, str):
        n = text_to_number(v)
        v = n if n is not None else to_numeric_prefix(v)
    if isinstance(v, float):
        return float_to_int_if_exact(v)
    return v


# ---------------------------------------------------------------------------
# LIKE / GLOB
# ---------------------------------------------------------------------------


@lru_cache(maxsize=256)
def _like_regex(pattern: str, escape: str | None) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if escape is not None and ch == escape:
            i += 1
            if i < len(pattern):
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
    return re.compile("".join(out), re.DOTALL | re.IGNORECASE | re.ASCII)


@lru_cache(maxsize=256)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        elif ch == "[":
            j = i + 1
            if j < n and pattern[j] == "^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(ch))
            else:
                body = pattern[i + 1 : j]
                neg = body.startswith("^")
                if neg:
                    body = body[1:]
                body = body.replace("\\", "\\\\").replace("[", "\\[")
                if body.startswith("]"):
                    body = "\\]" + body[1:]
                out.append("[" + ("^" if neg else "") + body + "]")
                i = j
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out), re.DOTALL)


def like(value: object, pattern: object, escape: object = None, op: str = "LIKE") -> int | None:
    if value is None or pattern is None:
        return None
    s = to_text(value)
    p = to_text(pattern)
    if op == "GLOB":
        return 1 if _glob_regex(p).fullmatch(s) else 0  # type: ignore[arg-type]
    esc = None
    if escape is not None:
        esc = to_text(escape)
        if esc is None or len(esc) != 1:
            raise SQLError("ESCAPE expression must be a single character")
    return 1 if _like_regex(p, esc).fullmatch(s) else 0  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Scalar functions
# ---------------------------------------------------------------------------


def _fn_round(args: list[object]) -> object:
    x = args[0]
    n = args[1] if len(args) > 1 else 0
    if x is None or n is None:
        return None
    digits = _to_int_trunc(to_number(n))
    digits = max(0, min(digits, 30))
    f = float(to_number(x))  # type: ignore[arg-type]
    if not math.isfinite(f) or abs(f) >= 4503599627370496.0:
        return f
    scale = 10.0**digits
    r = math.floor(abs(f) * scale + 0.5) / scale
    if digits == 0:
        r = float(math.floor(abs(f) + 0.5))
    else:
        # Prefer the decimal-formatted value to avoid representation noise.
        r = float(f"{r:.{digits}f}")
    return -r if f < 0 else r


def _fn_substr(args: list[object]) -> object:
    if any(a is None for a in args):
        return None
    s = to_text(args[0])
    assert s is not None
    start = _to_int_trunc(to_number(args[1]))
    length = _to_int_trunc(to_number(args[2])) if len(args) > 2 else None
    n = len(s)
    if start > 0:
        begin = start - 1
    elif start == 0:
        begin = -1  # position 0 is "before the first character"
    else:
        begin = n + start
    if length is None:
        end = n
        begin = max(begin, 0)
    elif length >= 0:
        end = begin + length
        begin = max(begin, 0)
    else:
        end = begin
        begin = begin + length
        begin = max(begin, 0)
    end = max(0, min(end, n))
    begin = min(begin, n)
    return s[begin:end] if end > begin else ""


def _fn_trim(name: str, args: list[object]) -> object:
    if any(a is None for a in args):
        return None
    s = to_text(args[0])
    chars = to_text(args[1]) if len(args) > 1 else " "
    assert s is not None and chars is not None
    if name == "TRIM":
        return s.strip(chars)
    if name == "LTRIM":
        return s.lstrip(chars)
    return s.rstrip(chars)


def _fn_typeof(v: object) -> str:
    if v is None:
        return "null"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "real"
    if isinstance(v, str):
        return "text"
    return "blob"


def call_scalar(name: str, args: list[object]) -> object:
    if name == "COALESCE" or name == "IFNULL":
        for a in args:
            if a is not None:
                return a
        return None
    if name == "NULLIF":
        a, b = args
        return None if sql_compare(a, b) == 0 else a
    if name == "TYPEOF":
        return _fn_typeof(args[0])
    if name in ("MIN", "MAX"):
        if any(a is None for a in args):
            return None
        best = args[0]
        for a in args[1:]:
            c = compare_values(a, best)
            if (name == "MIN" and c < 0) or (name == "MAX" and c > 0):
                best = a
        return best
    if name == "ROUND":
        return _fn_round(args)
    if name in ("SUBSTR", "SUBSTRING"):
        return _fn_substr(args)
    if name in ("TRIM", "LTRIM", "RTRIM"):
        return _fn_trim(name, args)
    v = args[0]
    if name == "ABS":
        if v is None:
            return None
        if isinstance(v, int):
            if v == MIN_INT64:
                raise SQLError("integer overflow")
            return abs(v)
        if isinstance(v, float):
            return abs(v)
        n = to_number(v)
        return abs(float(n))  # type: ignore[arg-type]
    if name == "LENGTH":
        if v is None:
            return None
        return len(to_text(v))  # type: ignore[arg-type]
    if name == "LOWER":
        s = to_text(v)
        return None if s is None else "".join(c.lower() if c.isascii() else c for c in s)
    if name == "UPPER":
        s = to_text(v)
        return None if s is None else "".join(c.upper() if c.isascii() else c for c in s)
    if name == "REPLACE":
        if any(a is None for a in args):
            return None
        s, old, new = (to_text(a) for a in args)
        if old == "":
            return s
        return s.replace(old, new)  # type: ignore[union-attr, arg-type]
    if name == "INSTR":
        if any(a is None for a in args):
            return None
        s, sub = to_text(args[0]), to_text(args[1])
        return s.find(sub) + 1  # type: ignore[union-attr, arg-type]
    raise SQLError(f"no such function: {name}")


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

_CMP = {
    "=": lambda c: c == 0,
    "!=": lambda c: c != 0,
    "<": lambda c: c < 0,
    "<=": lambda c: c <= 0,
    ">": lambda c: c > 0,
    ">=": lambda c: c >= 0,
}


def _truth_to_int(t: bool | None) -> int | None:
    return None if t is None else int(t)


def eval_expr(node: Expr, ctx: RowContext = EMPTY_CONTEXT) -> object:
    """Evaluate ``node`` in ``ctx`` and return a Python value (int/float/str/None)."""
    t = type(node)
    if t is Literal:
        return node.value  # type: ignore[attr-defined]
    if t is ColumnRef:
        return ctx.lookup(node)  # type: ignore[arg-type]
    if t is BinaryOp:
        return _eval_binary(node, ctx)  # type: ignore[arg-type]
    if t is UnaryOp:
        return _eval_unary(node, ctx)  # type: ignore[arg-type]
    if t is IsNull:
        v = eval_expr(node.operand, ctx)  # type: ignore[attr-defined]
        return int((v is not None) if node.negated else (v is None))  # type: ignore[attr-defined]
    if t is InList:
        return _eval_in(node, ctx)  # type: ignore[arg-type]
    if t is Between:
        return _eval_between(node, ctx)  # type: ignore[arg-type]
    if t is Like:
        v = eval_expr(node.operand, ctx)  # type: ignore[attr-defined]
        p = eval_expr(node.pattern, ctx)  # type: ignore[attr-defined]
        e = eval_expr(node.escape, ctx) if node.escape is not None else None  # type: ignore[attr-defined]
        if node.escape is not None and e is None:  # type: ignore[attr-defined]
            return None
        r = like(v, p, e, node.op)  # type: ignore[attr-defined]
        if r is None:
            return None
        return 1 - r if node.negated else r  # type: ignore[attr-defined]
    if t is FunctionCall:
        return _eval_function(node, ctx)  # type: ignore[arg-type]
    if t is Case:
        return _eval_case(node, ctx)  # type: ignore[arg-type]
    if t is Cast:
        return cast_value(eval_expr(node.operand, ctx), node.type_name)  # type: ignore[attr-defined]
    raise SQLError(f"cannot evaluate expression node {type(node).__name__}")


def _eval_binary(node: BinaryOp, ctx: RowContext) -> object:
    op = node.op
    if op == "AND":
        left = is_true(eval_expr(node.left, ctx))
        if left is False:
            return 0
        right = is_true(eval_expr(node.right, ctx))
        if right is False:
            return 0
        if left is None or right is None:
            return None
        return 1
    if op == "OR":
        left = is_true(eval_expr(node.left, ctx))
        if left is True:
            return 1
        right = is_true(eval_expr(node.right, ctx))
        if right is True:
            return 1
        if left is None or right is None:
            return None
        return 0
    a = eval_expr(node.left, ctx)
    b = eval_expr(node.right, ctx)
    if op in _CMP:
        c = sql_compare(
            a, b, expr_affinity(node.left, ctx.scope), expr_affinity(node.right, ctx.scope)
        )
        return None if c is None else int(_CMP[op](c))
    if op in ("IS", "IS NOT"):
        if a is None or b is None:
            eq = a is None and b is None
        else:
            eq = sql_compare(
                a, b, expr_affinity(node.left, ctx.scope), expr_affinity(node.right, ctx.scope)
            ) == 0
        return int(eq if op == "IS" else not eq)
    if op in ("+", "-", "*", "/", "%"):
        return arithmetic(op, a, b)
    if op == "||":
        if a is None or b is None:
            return None
        return to_text(a) + to_text(b)  # type: ignore[operator]
    if op in ("&", "|", "<<", ">>"):
        return bitwise(op, a, b)
    raise SQLError(f"unknown operator {op}")


def _eval_unary(node: UnaryOp, ctx: RowContext) -> object:
    v = eval_expr(node.operand, ctx)
    op = node.op
    if op == "NOT":
        return _truth_to_int(None if v is None else not is_true(v))
    if v is None:
        return None
    if op == "+":
        return v
    if op == "-":
        n = to_number(v)
        if isinstance(n, int):
            return _int_or_float(-n)
        return -n  # type: ignore[operator]
    if op == "~":
        return ~_to_int_trunc(to_number(v))
    raise SQLError(f"unknown unary operator {op}")


def _eval_in(node: InList, ctx: RowContext) -> object:
    v = eval_expr(node.operand, ctx)
    if not node.items:
        return 1 if node.negated else 0
    if v is None:
        return None
    aff = expr_affinity(node.operand, ctx.scope)
    saw_null = False
    for item in node.items:
        iv = eval_expr(item, ctx)
        c = sql_compare(v, iv, aff, expr_affinity(item, ctx.scope))
        if c is None:
            saw_null = True
        elif c == 0:
            return 0 if node.negated else 1
    if saw_null:
        return None
    return 1 if node.negated else 0


def _eval_between(node: Between, ctx: RowContext) -> object:
    v = eval_expr(node.operand, ctx)
    lo = eval_expr(node.low, ctx)
    hi = eval_expr(node.high, ctx)
    aff = expr_affinity(node.operand, ctx.scope)
    c1 = sql_compare(v, lo, aff, expr_affinity(node.low, ctx.scope))
    c2 = sql_compare(v, hi, aff, expr_affinity(node.high, ctx.scope))
    ge = None if c1 is None else c1 >= 0
    le = None if c2 is None else c2 <= 0
    if ge is False or le is False:
        result: bool | None = False
    elif ge is None or le is None:
        result = None
    else:
        result = True
    if result is None:
        return None
    return int(not result) if node.negated else int(result)


def _eval_function(node: FunctionCall, ctx: RowContext) -> object:
    if is_aggregate_call(node):
        if ctx.aggregates is None or node not in ctx.aggregates:
            raise SQLError(f"misuse of aggregate function {node.name.lower()}()")
        return ctx.aggregates[node]
    if node.name not in SCALAR_FUNCTIONS:
        raise SQLError(f"no such function: {node.name}")
    if node.name in ("COALESCE", "IFNULL"):
        for arg in node.args:
            v = eval_expr(arg, ctx)
            if v is not None:
                return v
        return None
    return call_scalar(node.name, [eval_expr(a, ctx) for a in node.args])


def _eval_case(node: Case, ctx: RowContext) -> object:
    if node.operand is not None:
        base = eval_expr(node.operand, ctx)
        base_aff = expr_affinity(node.operand, ctx.scope)
        for when, result in node.whens:
            wv = eval_expr(when, ctx)
            if sql_compare(base, wv, base_aff, expr_affinity(when, ctx.scope)) == 0:
                return eval_expr(result, ctx)
    else:
        for when, result in node.whens:
            if is_true(eval_expr(when, ctx)):
                return eval_expr(result, ctx)
    return eval_expr(node.else_, ctx) if node.else_ is not None else None
