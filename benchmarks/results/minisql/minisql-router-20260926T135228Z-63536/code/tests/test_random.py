"""Seeded randomized differential testing against sqlite3."""

from __future__ import annotations

import random
import sqlite3

import pytest
from conftest import Pair

INT_VALUES = ["NULL", "0", "1", "-1", "2", "3", "-7", "10", "'4'", "'x'", "2.0", "1.5"]
REAL_VALUES = ["NULL", "0.0", "0.5", "-2.25", "3.0", "1.5", "10", "'2.5'", "'y'", "-0.125"]
TEXT_VALUES = ["NULL", "''", "'a'", "'B'", "'abc'", "'1'", "'2.5'", "'10'", "3", "1.5", "'a_c'"]
ANY_VALUES = ["NULL", "1", "1.0", "'1'", "'b'", "-3", "2.5", "''", "'A'", "7"]

LITERALS = ["NULL", "0", "1", "2", "-1", "3", "0.5", "2.5", "-1.5", "'a'", "'1'", "'2.5'", "''",
            "'abc'", "'B'", "10"]
LIKE_PATTERNS = ["'a%'", "'%'", "'_'", "'%b%'", "'A_C'", "'1%'", "'%.5'", "''", "NULL", "'%c'"]
COLUMNS = ["i", "r", "t", "x", "id"]


class ExprGen:
    def __init__(self, rng: random.Random, columns=COLUMNS):
        self.rng = rng
        self.columns = columns

    def leaf(self) -> str:
        if self.rng.random() < 0.6:
            return self.rng.choice(self.columns)
        return self.rng.choice(LITERALS)

    def expr(self, depth: int = 3) -> str:
        rng = self.rng
        if depth <= 0 or rng.random() < 0.25:
            return self.leaf()
        d = depth - 1
        kind = rng.randrange(14)
        if kind == 0:
            op = rng.choice(["+", "-", "*", "/", "%"])
            return f"({self.expr(d)} {op} {self.expr(d)})"
        if kind == 1:
            op = rng.choice(["=", "==", "!=", "<>", "<", "<=", ">", ">="])
            return f"({self.expr(d)} {op} {self.expr(d)})"
        if kind == 2:
            op = rng.choice(["AND", "OR"])
            return f"({self.expr(d)} {op} {self.expr(d)})"
        if kind == 3:
            return f"(NOT {self.expr(d)})"
        if kind == 4:
            return f"({self.expr(d)} IS {rng.choice(['', 'NOT '])}NULL)"
        if kind == 5:
            items = ", ".join(self.expr(0) for _ in range(rng.randrange(0, 4)))
            return f"({self.expr(d)} {rng.choice(['', 'NOT '])}IN ({items}))"
        if kind == 6:
            neg = rng.choice(["", "NOT "])
            return f"({self.expr(d)} {neg}BETWEEN {self.expr(0)} AND {self.expr(0)})"
        if kind == 7:
            neg = rng.choice(["", "NOT "])
            pat = rng.choice(LIKE_PATTERNS + [self.leaf()])
            return f"({self.expr(d)} {neg}LIKE {pat})"
        if kind == 8:
            return f"({self.expr(d)} || {self.expr(d)})"
        if kind == 9:
            return f"(- {self.expr(d)})"
        if kind == 10:
            return f"CASE WHEN {self.expr(d)} THEN {self.expr(d)} ELSE {self.expr(d)} END"
        if kind == 11:
            return f"coalesce({self.expr(d)}, {self.expr(d)})"
        if kind == 12:
            return f"({self.expr(d)} IS {rng.choice(['', 'NOT '])}{self.expr(d)})"
        return f"CASE {self.expr(d)} WHEN {self.expr(0)} THEN {self.expr(d)} END"


def make_pair(rng: random.Random, nrows: int = 12) -> Pair:
    pair = Pair()
    pair.exec("CREATE TABLE t (id INTEGER, i INTEGER, r REAL, t TEXT, x)")
    rows = []
    for n in range(nrows):
        rows.append(
            f"({n}, {rng.choice(INT_VALUES)}, {rng.choice(REAL_VALUES)}, "
            f"{rng.choice(TEXT_VALUES)}, {rng.choice(ANY_VALUES)})"
        )
    pair.exec("INSERT INTO t VALUES " + ", ".join(rows))
    return pair


@pytest.mark.parametrize("seed", range(8))
def test_random_expressions(seed):
    rng = random.Random(seed)
    pair = make_pair(rng)
    gen = ExprGen(rng)
    for _ in range(150):
        e = gen.expr()
        pair.query(f"SELECT id, {e} FROM t")
        pair.query(f"SELECT id FROM t WHERE {e}")


@pytest.mark.parametrize("seed", range(8))
def test_random_order_by(seed):
    rng = random.Random(1000 + seed)
    pair = make_pair(rng)
    gen = ExprGen(rng)
    for _ in range(60):
        e = gen.expr(2)
        direction = rng.choice(["", " ASC", " DESC"])
        limit = rng.choice(["", " LIMIT 5", " LIMIT 3 OFFSET 2", " LIMIT -1 OFFSET 4"])
        pair.query(f"SELECT id, {e} AS v FROM t ORDER BY v{direction}, id{limit}")
        pair.query(f"SELECT DISTINCT {e} FROM t")


def valid_group_key(pair: Pair, gen: ExprGen) -> str:
    """A GROUP BY term that is not constant.

    SQLite constant-folds terms such as ``(0 AND x)`` to an integer and then rejects them as
    an out-of-range ordinal; those are skipped rather than compared.
    """
    while True:
        key = gen.expr(1)
        if not any(c in key for c in COLUMNS):
            continue
        try:
            pair.conn.execute(f"SELECT 1 FROM t GROUP BY {key}")
        except sqlite3.Error:
            continue
        return key


@pytest.mark.parametrize("seed", range(8))
def test_random_aggregates(seed):
    rng = random.Random(2000 + seed)
    pair = make_pair(rng, nrows=20)
    gen = ExprGen(rng)
    for _ in range(40):
        key = valid_group_key(pair, gen)
        val = gen.expr(2)
        aggs = (
            f"COUNT(*), COUNT({val}), COUNT(DISTINCT {val}), SUM({val}), AVG({val}), "
            f"MIN({val}), MAX({val}), total({val})"
        )
        pair.query(f"SELECT {aggs} FROM t")
        pair.query(f"SELECT {key}, {aggs} FROM t GROUP BY {key}")
        cond = gen.expr(1)
        pair.query(f"SELECT {key} AS k, COUNT(*) FROM t GROUP BY k HAVING {cond} OR COUNT(*) > 2")
        pair.query(f"SELECT {aggs} FROM t WHERE {cond}")


@pytest.mark.parametrize("seed", range(4))
def test_random_joins(seed):
    rng = random.Random(3000 + seed)
    pair = make_pair(rng, nrows=8)
    pair.exec("CREATE TABLE u (id INTEGER, k INTEGER, s TEXT)")
    values = ", ".join(
        f"({n}, {rng.choice(['NULL', '0', '1', '2', '3', '5'])}, {rng.choice(TEXT_VALUES)})"
        for n in range(8)
    )
    pair.exec(f"INSERT INTO u VALUES {values}")
    for _ in range(30):
        join = rng.choice(["JOIN", "LEFT JOIN"])
        on = rng.choice(
            ["t.i = u.k", "t.id = u.k", "t.x = u.s", "t.t = u.s", "u.k < t.id AND u.k > 1",
             "t.r > u.k", "u.s LIKE t.t"]
        )
        where = rng.choice(["", " WHERE u.id IS NULL", " WHERE t.id % 2 = 0", " WHERE u.k > 1"])
        pair.query(f"SELECT t.id, u.id, t.i, u.k, u.s FROM t {join} u ON {on}{where}")
        pair.query(
            f"SELECT t.id, COUNT(u.id), SUM(u.k), MAX(u.s) FROM t {join} u ON {on}{where}"
            " GROUP BY t.id ORDER BY t.id"
        )
