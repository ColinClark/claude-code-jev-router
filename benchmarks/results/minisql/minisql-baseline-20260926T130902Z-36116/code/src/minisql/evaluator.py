from __future__ import annotations

import re
from dataclasses import dataclass

from .ast_nodes import (
    Between,
    BinaryOp,
    ColumnRef,
    Expr,
    FunctionCall,
    InList,
    IsNull,
    Like,
    Literal,
    Star,
    UnaryOp,
)
from .errors import SQLError

AGGREGATE_NAMES = {"count", "sum", "avg", "min", "max"}


@dataclass
class EvalContext:
    row: dict | None  # (alias_lower, col_lower) -> value
    resolver: dict  # col_lower -> list[alias_lower]
    group_rows: list | None = None  # list of row dicts, for aggregate evaluation


def _resolve_column(table: str | None, name: str, ctx: EvalContext):
    row = ctx.row
    if row is None:
        return None
    if table is not None:
        key = (table.lower(), name.lower())
        if key not in row:
            raise SQLError(f"Unknown column {table}.{name}")
        return row[key]
    candidates = ctx.resolver.get(name.lower(), [])
    if len(candidates) == 0:
        raise SQLError(f"Unknown column {name}")
    if len(candidates) > 1:
        raise SQLError(f"Ambiguous column {name}")
    return row[(candidates[0], name.lower())]


def is_truthy(v) -> bool:
    return v is not None and v != 0


def sql_and(a, b):
    if (a is not None and a == 0) or (b is not None and b == 0):
        return 0
    if a is None or b is None:
        return None
    return 1


def sql_or(a, b):
    if (a is not None and a != 0) or (b is not None and b != 0):
        return 1
    if a is None or b is None:
        return None
    return 0


def sql_not(a):
    if a is None:
        return None
    return 0 if is_truthy(a) else 1


def _trunc_divmod(a: int, b: int) -> tuple[int, int]:
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    r = a - b * q
    return q, r


def _compare(op: str, a, b):
    if a is None or b is None:
        return None
    try:
        if op in ("=", "=="):
            result = a == b
        elif op in ("!=", "<>"):
            result = a != b
        elif op == "<":
            result = a < b
        elif op == "<=":
            result = a <= b
        elif op == ">":
            result = a > b
        elif op == ">=":
            result = a >= b
        else:
            raise SQLError(f"Unknown comparison operator {op}")
    except TypeError as exc:
        raise SQLError(f"Type mismatch in comparison: {exc}") from None
    return 1 if result else 0


def _arith(op: str, a, b):
    if a is None or b is None:
        return None
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            return None
        if isinstance(a, int) and isinstance(b, int):
            q, _ = _trunc_divmod(a, b)
            return q
        return a / b
    if op == "%":
        ai, bi = int(a), int(b)
        if bi == 0:
            return None
        _, r = _trunc_divmod(ai, bi)
        return r
    raise SQLError(f"Unknown operator {op}")


def _like_to_regex(pattern: str) -> str:
    out = []
    for ch in pattern:
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return "^" + "".join(out) + "$"


def _like(s, pattern):
    if s is None or pattern is None:
        return None
    regex = _like_to_regex(pattern)
    return 1 if re.match(regex, s, re.IGNORECASE | re.DOTALL) else 0


def evaluate(expr: Expr, ctx: EvalContext):
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ColumnRef):
        return _resolve_column(expr.table, expr.name, ctx)
    if isinstance(expr, Star):
        raise SQLError("Unexpected * in expression")
    if isinstance(expr, UnaryOp):
        if expr.op == "-":
            val = evaluate(expr.operand, ctx)
            return None if val is None else -val
        if expr.op == "NOT":
            return sql_not(evaluate(expr.operand, ctx))
        raise SQLError(f"Unknown unary operator {expr.op}")
    if isinstance(expr, BinaryOp):
        if expr.op == "AND":
            return sql_and(evaluate(expr.left, ctx), evaluate(expr.right, ctx))
        if expr.op == "OR":
            return sql_or(evaluate(expr.left, ctx), evaluate(expr.right, ctx))
        left = evaluate(expr.left, ctx)
        right = evaluate(expr.right, ctx)
        if expr.op in ("=", "==", "!=", "<>", "<", "<=", ">", ">="):
            return _compare(expr.op, left, right)
        if expr.op == "||":
            if left is None or right is None:
                return None
            return sql_str(left) + sql_str(right)
        if expr.op in ("+", "-", "*", "/", "%"):
            return _arith(expr.op, left, right)
        raise SQLError(f"Unknown operator {expr.op}")
    if isinstance(expr, IsNull):
        val = evaluate(expr.operand, ctx)
        is_null = val is None
        if expr.negated:
            return 0 if is_null else 1
        return 1 if is_null else 0
    if isinstance(expr, InList):
        operand = evaluate(expr.operand, ctx)
        result = _eval_in(operand, expr.items, ctx)
        if expr.negated:
            return sql_not(result)
        return result
    if isinstance(expr, Between):
        operand_expr = expr.operand
        val = evaluate(operand_expr, ctx)
        low = evaluate(expr.low, ctx)
        high = evaluate(expr.high, ctx)
        ge = _compare(">=", val, low)
        le = _compare("<=", val, high)
        result = sql_and(ge, le)
        if expr.negated:
            return sql_not(result)
        return result
    if isinstance(expr, Like):
        s = evaluate(expr.operand, ctx)
        pattern = evaluate(expr.pattern, ctx)
        result = _like(s, pattern)
        if expr.negated:
            return sql_not(result)
        return result
    if isinstance(expr, FunctionCall):
        if expr.name in AGGREGATE_NAMES:
            return _eval_aggregate(expr, ctx)
        raise SQLError(f"Unknown function {expr.name}")
    raise SQLError(f"Cannot evaluate expression {expr!r}")


def sql_str(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e16:
            return f"{v:.1f}"
        return repr(v)
    return str(v)


def _eval_in(operand, items, ctx: EvalContext):
    if operand is None:
        return None
    found = False
    saw_null = False
    for item in items:
        val = evaluate(item, ctx)
        if val is None:
            saw_null = True
            continue
        if val == operand:
            found = True
            break
    if found:
        return 1
    return None if saw_null else 0


def has_aggregate(expr: Expr) -> bool:
    if isinstance(expr, FunctionCall):
        if expr.name in AGGREGATE_NAMES:
            return True
        return any(has_aggregate(a) for a in expr.args)
    if isinstance(expr, UnaryOp):
        return has_aggregate(expr.operand)
    if isinstance(expr, BinaryOp):
        return has_aggregate(expr.left) or has_aggregate(expr.right)
    if isinstance(expr, IsNull):
        return has_aggregate(expr.operand)
    if isinstance(expr, InList):
        return has_aggregate(expr.operand) or any(has_aggregate(i) for i in expr.items)
    if isinstance(expr, Between):
        return (
            has_aggregate(expr.operand) or has_aggregate(expr.low) or has_aggregate(expr.high)
        )
    if isinstance(expr, Like):
        return has_aggregate(expr.operand) or has_aggregate(expr.pattern)
    return False


def _eval_aggregate(func: FunctionCall, ctx: EvalContext):
    if ctx.group_rows is None:
        raise SQLError(f"Aggregate function {func.name} used without a group context")
    name = func.name
    if name == "count":
        arg = func.args[0]
        if isinstance(arg, Star):
            return len(ctx.group_rows)
        values = [
            evaluate(arg, EvalContext(row=r, resolver=ctx.resolver)) for r in ctx.group_rows
        ]
        if func.distinct:
            return len({v for v in values if v is not None})
        return sum(1 for v in values if v is not None)

    arg = func.args[0]
    values = [evaluate(arg, EvalContext(row=r, resolver=ctx.resolver)) for r in ctx.group_rows]
    non_null = [v for v in values if v is not None]
    if func.distinct:
        non_null = list({v for v in non_null})

    if name == "sum":
        if not non_null:
            return None
        total = sum(non_null)
        has_float = any(isinstance(v, float) for v in non_null)
        return float(total) if has_float else total
    if name == "avg":
        if not non_null:
            return None
        return sum(non_null) / len(non_null)
    if name == "min":
        if not non_null:
            return None
        return min(non_null)
    if name == "max":
        if not non_null:
            return None
        return max(non_null)
    raise SQLError(f"Unknown aggregate function {name}")
