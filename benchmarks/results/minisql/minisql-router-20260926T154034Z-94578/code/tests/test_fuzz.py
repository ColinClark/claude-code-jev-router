"""Seeded random differential testing against sqlite3."""

import random

import pytest

from .conftest import Pair

INT_VALUES = ["0", "1", "-1", "2", "3", "7", "-13", "100", "NULL", "9223372036854775807"]
REAL_VALUES = ["0.0", "1.5", "-2.25", "0.1", "3.0", "1e20", "NULL", "-0.5", "1e-7"]
TEXT_VALUES = [
    "'a'",
    "'B'",
    "'abc'",
    "'Abc'",
    "''",
    "'10'",
    "'2.5'",
    "'x_y'",
    "'%'",
    "NULL",
    "'12abc'",
    "'é'",
]


def make_pair(rng: random.Random) -> Pair:
    p = Pair()
    p.exec(
        "CREATE TABLE t (id INTEGER, i INTEGER, r REAL, s TEXT)",
        "CREATE TABLE u (id INTEGER, i INTEGER, s TEXT)",
    )
    rows = [
        f"({n}, {rng.choice(INT_VALUES)}, {rng.choice(REAL_VALUES)}, {rng.choice(TEXT_VALUES)})"
        for n in range(1, 16)
    ]
    p.exec("INSERT INTO t VALUES " + ", ".join(rows))
    urows = [f"({n}, {rng.choice(INT_VALUES[:6])}, {rng.choice(TEXT_VALUES)})" for n in range(1, 8)]
    p.exec("INSERT INTO u VALUES " + ", ".join(urows))
    return p


class ExprGen:
    def __init__(self, rng: random.Random, columns: list[str]):
        self.rng = rng
        self.columns = columns

    def leaf(self) -> str:
        r = self.rng.random()
        if r < 0.5:
            return self.rng.choice(self.columns)
        return self.rng.choice(INT_VALUES + REAL_VALUES + TEXT_VALUES)

    def expr(self, depth: int = 3) -> str:
        rng = self.rng
        if depth <= 0 or rng.random() < 0.25:
            return self.leaf()
        a = self.expr(depth - 1)
        b = self.expr(depth - 1)
        kind = rng.randrange(12)
        if kind == 0:
            return f"({a} {rng.choice(['+', '-', '*', '/', '%'])} {b})"
        if kind == 1:
            return f"({a} || {b})"
        if kind == 2:
            return f"({a} {rng.choice(['=', '==', '!=', '<>', '<', '<=', '>', '>='])} {b})"
        if kind == 3:
            return f"({a} {rng.choice(['AND', 'OR'])} {b})"
        if kind == 4:
            return f"(NOT {a})"
        if kind == 5:
            return f"(- {a})"
        if kind == 6:
            return f"({a} IS {rng.choice(['', 'NOT '])}NULL)"
        if kind == 7:
            items = ", ".join(self.expr(depth - 2) for _ in range(rng.randrange(1, 4)))
            return f"({a} {rng.choice(['', 'NOT '])}IN ({items}))"
        if kind == 8:
            return f"({a} {rng.choice(['', 'NOT '])}BETWEEN {b} AND {self.expr(depth - 2)})"
        if kind == 9:
            pat = rng.choice(["'a%'", "'%b%'", "'_'", "'%'", "'A_C'", "'1%'", "''", "'%.5'"])
            if rng.random() < 0.2:
                pat = b
            return f"({a} {rng.choice(['', 'NOT '])}LIKE {pat})"
        if kind == 10:
            return f"CASE WHEN {a} THEN {b} ELSE {self.expr(depth - 2)} END"
        return f"COALESCE({a}, {b})"


SEEDS = range(40)


@pytest.mark.parametrize("seed", SEEDS)
def test_random_expressions(seed):
    rng = random.Random(seed)
    p = make_pair(rng)
    gen = ExprGen(rng, ["i", "r", "s", "id"])
    for _ in range(25):
        cols = ", ".join(gen.expr() for _ in range(3))
        p.check(f"SELECT id, {cols} FROM t ORDER BY id")
        p.check(f"SELECT id FROM t WHERE {gen.expr()} ORDER BY id")


@pytest.mark.parametrize("seed", SEEDS)
def test_random_ordering(seed):
    rng = random.Random(1000 + seed)
    p = make_pair(rng)
    gen = ExprGen(rng, ["i", "r", "s"])
    for _ in range(15):
        # Wrap keys in an expression so integer literals are not read as column positions.
        keys = ", ".join(
            f"COALESCE({gen.expr(2)}, NULL) {rng.choice(['', 'ASC', 'DESC'])}"
            for _ in range(rng.randrange(1, 3))
        )
        p.check(f"SELECT id, i, r, s FROM t ORDER BY {keys}, id")
        p.check(f"SELECT DISTINCT {gen.expr(1)} AS k FROM t ORDER BY k")


@pytest.mark.parametrize("seed", SEEDS)
def test_random_aggregates(seed):
    rng = random.Random(2000 + seed)
    p = make_pair(rng)
    gen = ExprGen(rng, ["i", "r", "s"])
    aggs = [
        "COUNT(*)",
        "COUNT({})",
        "COUNT(DISTINCT {})",
        "SUM({})",
        "AVG({})",
        "MIN({})",
        "MAX({})",
        "TOTAL({})",
        "SUM(DISTINCT {})",
    ]
    for _ in range(12):
        sel = ", ".join(rng.choice(aggs).format(gen.expr(1)) for _ in range(3))
        where = f" WHERE {gen.expr(2)}" if rng.random() < 0.5 else ""
        p.check(f"SELECT {sel} FROM t{where}")
        key = gen.expr(1)
        having = f" HAVING {rng.choice(aggs).format(gen.expr(1))} > 1" if rng.random() < 0.4 else ""
        p.check(f"SELECT {key} AS k, {sel} FROM t{where} GROUP BY k{having} ORDER BY k")


@pytest.mark.parametrize("seed", range(20))
def test_random_joins(seed):
    rng = random.Random(3000 + seed)
    p = make_pair(rng)
    gen = ExprGen(rng, ["t.i", "t.s", "u.i", "u.s", "t.r"])
    for _ in range(10):
        kind = rng.choice(["JOIN", "LEFT JOIN", "INNER JOIN", "LEFT OUTER JOIN"])
        on = rng.choice(["t.i = u.i", "t.s = u.s", "t.i < u.i", gen.expr(2)])
        p.check(f"SELECT t.id, u.id, {gen.expr(2)} FROM t {kind} u ON {on} ORDER BY t.id, u.id")
        p.check(
            f"SELECT t.id, COUNT(u.id), SUM(u.i), MAX(u.s) FROM t {kind} u ON {on} "
            f"GROUP BY t.id ORDER BY t.id"
        )
