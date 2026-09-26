"""Seeded randomized differential tests against SQLite."""

import random

import pytest

from tests.conftest import Pair

INT_VALUES = ["NULL", "0", "1", "-1", "2", "3", "7", "-5", "10", "100"]
REAL_VALUES = ["NULL", "0.0", "1.5", "-2.25", "3.0", "0.1", "1e10", "-7.5", "2.5"]
TEXT_VALUES = ["NULL", "''", "'a'", "'A'", "'abc'", "'ABD'", "'b%'", "'10'", "'x_y'", "'zz'"]


def _setup(rng: random.Random) -> Pair:
    p = Pair(
        "CREATE TABLE t (a INTEGER, b REAL, c TEXT, g INTEGER)",
        "CREATE TABLE u (a INTEGER, d TEXT)",
    )
    rows = [
        f"({rng.choice(INT_VALUES)}, {rng.choice(REAL_VALUES)}, {rng.choice(TEXT_VALUES)}, "
        f"{rng.randint(0, 3)})"
        for _ in range(25)
    ]
    p.run("INSERT INTO t VALUES " + ", ".join(rows))
    urows = [f"({rng.choice(INT_VALUES)}, {rng.choice(TEXT_VALUES)})" for _ in range(8)]
    p.run("INSERT INTO u VALUES " + ", ".join(urows))
    return p


def _operand(rng: random.Random, depth: int) -> str:
    choices = ["t.a", "t.b", "t.c", "t.g", "u.a", "u.d"]
    if depth <= 0 or rng.random() < 0.4:
        if rng.random() < 0.7:
            return rng.choice(choices)
        return rng.choice(INT_VALUES + REAL_VALUES + TEXT_VALUES)
    op = rng.choice(["+", "-", "*", "/", "%", "||"])
    return f"({_operand(rng, depth - 1)} {op} {_operand(rng, depth - 1)})"


def _predicate(rng: random.Random, depth: int) -> str:
    kind = rng.randrange(9)
    if depth > 0 and kind == 0:
        op = rng.choice(["AND", "OR"])
        return f"({_predicate(rng, depth - 1)} {op} {_predicate(rng, depth - 1)})"
    if depth > 0 and kind == 1:
        return f"NOT ({_predicate(rng, depth - 1)})"
    x = _operand(rng, 1)
    if kind == 2:
        return f"{x} IS {rng.choice(['', 'NOT '])}NULL"
    if kind == 3:
        items = ", ".join(rng.choice(INT_VALUES + TEXT_VALUES) for _ in range(3))
        return f"{x} {rng.choice(['', 'NOT '])}IN ({items})"
    if kind == 4:
        lo, hi = rng.choice(INT_VALUES), rng.choice(INT_VALUES)
        return f"{x} {rng.choice(['', 'NOT '])}BETWEEN {lo} AND {hi}"
    if kind == 5:
        pat = rng.choice(["'a%'", "'%b%'", "'_'", "'%'", "'1%'", "'A_C'"])
        return f"{x} {rng.choice(['', 'NOT '])}LIKE {pat}"
    op = rng.choice(["=", "!=", "<", "<=", ">", ">=", "<>", "=="])
    return f"{x} {op} {_operand(rng, 1)}"


@pytest.mark.parametrize("seed", range(40))
def test_random_where_and_projection(seed):
    rng = random.Random(seed)
    p = _setup(rng)
    for _ in range(15):
        join = rng.choice(["JOIN u ON t.a = u.a", "LEFT JOIN u ON t.a = u.a",
                           "LEFT JOIN u ON " + _predicate(rng, 1)])
        cols = ", ".join(_operand(rng, 2) for _ in range(3))
        p.check(f"SELECT {cols} FROM t {join} WHERE {_predicate(rng, 2)}")


@pytest.mark.parametrize("seed", range(40))
def test_random_aggregates(seed):
    rng = random.Random(1000 + seed)
    p = _setup(rng)
    for _ in range(10):
        agg = rng.choice(["COUNT", "SUM", "AVG", "MIN", "MAX", "total"])
        arg = rng.choice(["t.a", "t.b", "t.c", "DISTINCT t.a", "t.a * t.b", "u.d"])
        key = rng.choice(["t.g", "t.c", "t.a % 3", "u.d"])
        join = rng.choice(["JOIN u ON t.a = u.a", "LEFT JOIN u ON t.a = u.a"])
        having = rng.choice(["", f" HAVING COUNT(*) > {rng.randint(0, 5)}"])
        p.check(
            f"SELECT {key}, {agg}({arg}), COUNT(*) FROM t {join} WHERE {_predicate(rng, 1)} "
            f"GROUP BY {key}{having}"
        )
        p.check(f"SELECT {agg}({arg}) FROM t {join} WHERE {_predicate(rng, 1)}")


@pytest.mark.parametrize("seed", range(20))
def test_random_order_by(seed):
    rng = random.Random(5000 + seed)
    p = _setup(rng)
    for _ in range(10):
        terms = [f"{rng.choice(['t.a', 't.b', 't.c', 't.g'])} {rng.choice(['ASC', 'DESC', ''])}"
                 for _ in range(2)]
        # t.rowid-like total order: append every column so ties are fully broken.
        order = ", ".join(terms + ["t.a", "t.b", "t.c", "t.g"])
        limit = rng.choice(["", " LIMIT 5", " LIMIT 3 OFFSET 4", " LIMIT -1 OFFSET 20"])
        p.check(f"SELECT DISTINCT t.a, t.b, t.c, t.g FROM t ORDER BY {order}{limit}")
