"""Randomized differential testing against sqlite3 with fixed seeds."""

from __future__ import annotations

import random
import re

import pytest

COLUMNS = ["id", "i", "j", "r", "t", "u"]
ROWS = [
    (1, 1, 2, 1.5, "a", "1"),
    (2, -3, 0, -0.5, "B", "2.5"),
    (3, None, 7, None, None, None),
    (4, 0, None, 2.0, "abc", "x"),
    (5, 10, -10, 1e3, "", "10"),
    (6, 7, 3, 0.25, "Ab", " 3 "),
    (7, 2, 2, None, "b%", "-4"),
    (8, None, None, 3.75, "a_c", "1e2"),
    (9, -8, 5, -2.5, "zz", "0"),
    (10, 4, -1, 0.0, "A", None),
]

LITERALS = [
    "0", "1", "2", "-1", "3", "10", "0.5", "-2.5", "1.0", "NULL", "'a'", "'1'", "'2.5'",
    "'abc'", "''", "'A%'", "'%b%'", "'_'", "7", "100", "1e2",
]

BINARY_OPS = ["+", "-", "*", "/", "%", "||", "=", "==", "!=", "<>", "<", "<=", ">", ">=",
              "AND", "OR", "IS", "IS NOT"]


def gen_expr(rng: random.Random, depth: int, cols: list[str]) -> str:
    if depth <= 0 or rng.random() < 0.25:
        if rng.random() < 0.55:
            return rng.choice(cols)
        return rng.choice(LITERALS)
    kind = rng.random()
    if kind < 0.45:
        op = rng.choice(BINARY_OPS)
        return f"({gen_expr(rng, depth - 1, cols)} {op} {gen_expr(rng, depth - 1, cols)})"
    if kind < 0.55:
        return f"(- {gen_expr(rng, depth - 1, cols)})"
    if kind < 0.62:
        return f"(NOT {gen_expr(rng, depth - 1, cols)})"
    if kind < 0.70:
        items = ", ".join(gen_expr(rng, depth - 2, cols) for _ in range(rng.randint(1, 3)))
        neg = "NOT " if rng.random() < 0.3 else ""
        return f"({gen_expr(rng, depth - 1, cols)} {neg}IN ({items}))"
    if kind < 0.78:
        neg = "NOT " if rng.random() < 0.3 else ""
        return (
            f"({gen_expr(rng, depth - 1, cols)} {neg}BETWEEN "
            f"{gen_expr(rng, depth - 2, cols)} AND {gen_expr(rng, depth - 2, cols)})"
        )
    if kind < 0.85:
        neg = "NOT " if rng.random() < 0.3 else ""
        return f"({gen_expr(rng, depth - 1, cols)} {neg}LIKE {gen_expr(rng, depth - 2, cols)})"
    if kind < 0.92:
        neg = "NOT " if rng.random() < 0.5 else ""
        return f"({gen_expr(rng, depth - 1, cols)} IS {neg}NULL)"
    # unparenthesised chain to exercise precedence
    parts = [gen_expr(rng, depth - 2, cols)]
    for _ in range(rng.randint(1, 3)):
        parts.append(rng.choice(BINARY_OPS))
        parts.append(gen_expr(rng, depth - 2, cols))
    return " ".join(parts)


@pytest.fixture
def rand_pair(pair):
    pair.run("CREATE TABLE t (id INTEGER, i INTEGER, j INTEGER, r REAL, t TEXT, u)")
    values = ", ".join(
        "(" + ", ".join("NULL" if v is None else repr(v) for v in row) + ")" for row in ROWS
    )
    pair.run(f"INSERT INTO t VALUES {values}")
    pair.run("CREATE TABLE s (id INTEGER, k INTEGER, name TEXT)")
    pair.run("INSERT INTO s VALUES (1, 1, 'one'), (2, 2, 'two'), (3, 2, 'deux'), (4, NULL, 'n')")
    return pair


@pytest.mark.parametrize("seed", range(8))
def test_random_projections(rand_pair, seed):
    rng = random.Random(seed)
    for _ in range(60):
        expr = gen_expr(rng, 4, COLUMNS[1:])
        rand_pair.check_same(f"SELECT id, {expr} FROM t ORDER BY id")


@pytest.mark.parametrize("seed", range(8))
def test_random_where(rand_pair, seed):
    rng = random.Random(1000 + seed)
    for _ in range(60):
        cond = gen_expr(rng, 4, COLUMNS[1:])
        rand_pair.check_same(f"SELECT id FROM t WHERE {cond}", ordered=False)


@pytest.mark.parametrize("seed", range(6))
def test_random_literal_expressions(rand_pair, seed):
    rng = random.Random(2000 + seed)
    for _ in range(80):
        expr = gen_expr(rng, 5, ["1", "2", "-7", "3.5", "'x'", "NULL", "'12'", "0"])
        rand_pair.check_same(f"SELECT {expr}")


def gen_key(rng: random.Random, depth: int, cols: list[str]) -> str:
    """An expression referencing at least one column.

    Constant GROUP BY / ORDER BY terms are avoided: SQLite's optimizer constant-folds
    expressions such as ``(7 IS NULL)`` or ``(x AND 0)`` into integers and then treats them
    as positional column references, which is version-dependent optimizer behaviour.
    """
    while True:
        expr = gen_expr(rng, depth, cols)
        if not any(re.search(rf"(?<![\w.']){re.escape(c)}\b", expr) for c in cols):
            continue
        if _FOLDABLE_LOGIC.search(expr):
            continue
        return expr


_FOLDABLE_LOGIC = re.compile(r"\b(AND|OR)\s+[(\s]*[-\d'N]|[\d'L)]\s+(AND|OR)\b")


AGGS = ["COUNT(*)", "COUNT({e})", "COUNT(DISTINCT {e})", "SUM({e})", "AVG({e})", "MIN({e})",
        "MAX({e})", "TOTAL({e})"]


@pytest.mark.parametrize("seed", range(6))
def test_random_group_by(rand_pair, seed):
    rng = random.Random(3000 + seed)
    for _ in range(30):
        key = gen_key(rng, 2, COLUMNS[1:])
        aggs = [
            rng.choice(AGGS).format(e=gen_expr(rng, 2, COLUMNS[1:]))
            for _ in range(rng.randint(1, 3))
        ]
        having = ""
        if rng.random() < 0.4:
            having = f" HAVING {rng.choice(AGGS).format(e=rng.choice(COLUMNS))} > 1"
        sql = f"SELECT {key}, {', '.join(aggs)} FROM t GROUP BY {key}{having}"
        rand_pair.check_same(sql, ordered=False)
        rand_pair.check_same(f"SELECT {', '.join(aggs)} FROM t", ordered=False)


@pytest.mark.parametrize("seed", range(4))
def test_random_order_by(rand_pair, seed):
    rng = random.Random(4000 + seed)
    for _ in range(30):
        keys = [
            f"{gen_key(rng, 2, COLUMNS[1:])} {rng.choice(['ASC', 'DESC', ''])}"
            for _ in range(rng.randint(1, 2))
        ]
        # 'id' as a final tie-breaker makes the order fully deterministic.
        limit = rng.choice(["", " LIMIT 3", " LIMIT 4 OFFSET 2", " LIMIT -1 OFFSET 7"])
        sql = f"SELECT id, i, t FROM t ORDER BY {', '.join(keys)}, id{limit}"
        rand_pair.check_same(sql)


@pytest.mark.parametrize("seed", range(4))
def test_random_joins(rand_pair, seed):
    rng = random.Random(5000 + seed)
    cols = ["t.i", "t.j", "t.r", "t.t", "s.k", "s.id", "s.name", "t.id"]
    for _ in range(25):
        on = gen_expr(rng, 2, cols)
        kind = rng.choice(["JOIN", "LEFT JOIN"])
        where = f" WHERE {gen_expr(rng, 2, cols)}" if rng.random() < 0.4 else ""
        sql = f"SELECT t.id, s.id, s.name FROM t {kind} s ON {on}{where}"
        rand_pair.check_same(sql, ordered=False)
