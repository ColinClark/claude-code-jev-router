"""Randomized differential tests (fixed seeds) against sqlite3."""

from __future__ import annotations

import random
import sqlite3

import pytest

from minisql import SQLError
from tests.conftest import Dual, typed

COLUMNS = ["a", "b", "c", "d"]  # INTEGER, REAL, TEXT, untyped
LITERALS = [
    "0", "1", "2", "-3", "7", "10", "0.5", "-2.5", "3.0", "NULL",
    "'a'", "'B'", "'10'", "'2.5'", "''", "'abc'", "' 3'",
]
LIKE_PATTERNS = ["'a%'", "'%B%'", "'_'", "'1%'", "'%'", "'A_C'", "'%.5'"]
BINARY_OPS = [
    "+", "-", "*", "/", "%", "||", "=", "!=", "<", "<=", ">", ">=", "AND", "OR", "IS",
    "IS NOT", "==", "<>",
]
FUNCS1 = ["abs", "length", "typeof", "upper", "lower"]


def make_value(rng: random.Random) -> str:
    return rng.choice(LITERALS)


def make_expr(rng: random.Random, depth: int, columns: list[str]) -> str:
    if depth <= 0 or rng.random() < 0.25:
        if columns and rng.random() < 0.6:
            return rng.choice(columns)
        return make_value(rng)
    kind = rng.randrange(10)
    sub = lambda: make_expr(rng, depth - 1, columns)  # noqa: E731
    if kind <= 3:
        return f"({sub()} {rng.choice(BINARY_OPS)} {sub()})"
    if kind == 4:
        return f"({rng.choice(['-', 'NOT ', '+'])}{sub()})"
    if kind == 5:
        items = ", ".join(sub() for _ in range(rng.randint(1, 3)))
        neg = rng.choice(["", "NOT "])
        return f"({sub()} {neg}IN ({items}))"
    if kind == 6:
        neg = rng.choice(["", "NOT "])
        return f"({sub()} {neg}BETWEEN {sub()} AND {sub()})"
    if kind == 7:
        neg = rng.choice(["", "NOT "])
        pat = rng.choice(LIKE_PATTERNS) if rng.random() < 0.7 else sub()
        return f"({sub()} {neg}LIKE {pat})"
    if kind == 8:
        return f"{rng.choice(FUNCS1)}({sub()})"
    if rng.random() < 0.5:
        return f"coalesce({sub()}, {sub()})"
    return f"(CASE WHEN {sub()} THEN {sub()} ELSE {sub()} END)"


def populate(dual: Dual, rng: random.Random) -> None:
    dual.run("CREATE TABLE t (id INTEGER, a INTEGER, b REAL, c TEXT, d)")
    dual.run("CREATE TABLE s (id INTEGER, a INTEGER, c TEXT)")
    for i in range(12):
        vals = [str(i)] + [make_value(rng) for _ in range(4)]
        dual.run(f"INSERT INTO t VALUES ({', '.join(vals)})")
    for i in range(6):
        dual.run(f"INSERT INTO s VALUES ({i}, {make_value(rng)}, {make_value(rng)})")


def compare(dual: Dual, sql: str, ordered: bool) -> None:
    try:
        expected = dual.lite.execute(sql).fetchall()
    except sqlite3.Error:
        with pytest.raises(SQLError):
            dual.mini.execute(sql)
        return
    actual = dual.mini.execute(sql)
    exp_t, act_t = typed(expected), typed(actual)
    if not ordered:
        exp_t = sorted(exp_t, key=repr)
        act_t = sorted(act_t, key=repr)
    assert act_t == exp_t, f"\nSQL: {sql}\nsqlite:  {expected}\nminisql: {actual}"


@pytest.mark.parametrize("seed", range(8))
def test_random_expressions(seed: int) -> None:
    rng = random.Random(seed)
    dual = Dual()
    populate(dual, rng)
    for _ in range(150):
        exprs = [make_expr(rng, 3, COLUMNS) for _ in range(rng.randint(1, 3))]
        where = make_expr(rng, 3, COLUMNS)
        compare(dual, f"SELECT id, {', '.join(exprs)} FROM t WHERE {where}", ordered=False)


@pytest.mark.parametrize("seed", range(4))
def test_random_constant_expressions(seed: int) -> None:
    rng = random.Random(1000 + seed)
    dual = Dual()
    for _ in range(300):
        compare(dual, f"SELECT {make_expr(rng, 4, [])}", ordered=False)


@pytest.mark.parametrize("seed", range(6))
def test_random_aggregate_queries(seed: int) -> None:
    rng = random.Random(2000 + seed)
    dual = Dual()
    populate(dual, rng)
    aggs = ["COUNT(*)", "COUNT({})", "SUM({})", "AVG({})", "MIN({})", "MAX({})", "TOTAL({})",
            "COUNT(DISTINCT {})"]
    for _ in range(80):
        group = rng.choice(COLUMNS)
        selected = [group] + [
            rng.choice(aggs).format(make_expr(rng, 1, COLUMNS)) for _ in range(rng.randint(1, 3))
        ]
        sql = f"SELECT {', '.join(selected)} FROM t"
        if rng.random() < 0.5:
            sql += f" WHERE {make_expr(rng, 2, COLUMNS)}"
        sql += f" GROUP BY {group}"
        if rng.random() < 0.4:
            sql += f" HAVING COUNT(*) > {rng.randint(0, 2)}"
        compare(dual, sql, ordered=False)
        # without GROUP BY: always exactly one row
        agg_only = ", ".join(selected[1:])
        compare(dual, f"SELECT {agg_only} FROM t WHERE {make_expr(rng, 2, COLUMNS)}", False)


@pytest.mark.parametrize("seed", range(6))
def test_random_ordered_joins(seed: int) -> None:
    rng = random.Random(3000 + seed)
    dual = Dual()
    populate(dual, rng)
    for _ in range(60):
        join = rng.choice(["JOIN", "LEFT JOIN"])
        on = f"t.{rng.choice(['a', 'c', 'id'])} = s.{rng.choice(['a', 'c', 'id'])}"
        cols = [f"t.{rng.choice(COLUMNS)}", f"s.{rng.choice(['a', 'c'])}"]
        keys = [f"{c} {rng.choice(['ASC', 'DESC'])}" for c in cols]
        sql = (
            f"SELECT {', '.join(cols)}, t.id, s.id FROM t {join} s ON {on} "
            f"ORDER BY {', '.join(keys)}, t.id, s.id"
        )
        if rng.random() < 0.5:
            sql += f" LIMIT {rng.randint(0, 8)} OFFSET {rng.randint(0, 3)}"
        compare(dual, sql, ordered=True)
        distinct = f"SELECT DISTINCT {cols[0]} FROM t {join} s ON {on} ORDER BY 1"
        compare(dual, distinct, ordered=True)
