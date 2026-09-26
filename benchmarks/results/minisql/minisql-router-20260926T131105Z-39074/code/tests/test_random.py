"""Randomized differential tests: random data and generated queries vs sqlite3 (fixed seed)."""

from __future__ import annotations

import random

import pytest
from conftest import Pair

SEED = 20240601
TEXTS = ["a", "B", "abc", "Abd", "3", "1.5", "", " 2", "x_y", "10", "b%"]
LIKE_PATTERNS = ["%a%", "a_", "%", "_", "b%", "%3%", "A%C", "__", "%b"]

COLUMNS = {
    "t1": [("id", "INTEGER"), ("a", "INTEGER"), ("b", "REAL"), ("c", "TEXT"), ("k", "INTEGER")],
    "t2": [("id", "INTEGER"), ("k", "INTEGER"), ("d", "TEXT"), ("e", "REAL")],
}


def random_value(rng: random.Random, type_name: str):
    roll = rng.random()
    if roll < 0.15:
        return None
    if roll < 0.2:
        # Occasionally store a value of a "foreign" type to exercise affinity.
        return rng.choice([rng.choice(TEXTS), rng.randint(-5, 5), rng.randint(-8, 8) / 4])
    if type_name == "INTEGER":
        return rng.randint(-5, 12)
    if type_name == "REAL":
        return rng.randint(-40, 40) / 4
    return rng.choice(TEXTS)


def literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return repr(value)


def build_pair(rng: random.Random) -> Pair:
    pair = Pair()
    for table, columns in COLUMNS.items():
        pair.run(f"CREATE TABLE {table} ({', '.join(f'{n} {t}' for n, t in columns)})")
        rows = []
        for row_id in range(rng.randint(0, 14)):
            values = [str(row_id)]
            for name, type_name in columns[1:]:
                if name == "k":
                    values.append(literal(rng.choice([None, 1, 2, 3, 4, 5])))
                else:
                    values.append(literal(random_value(rng, type_name)))
            rows.append(f"({', '.join(values)})")
        if rows:
            pair.run(f"INSERT INTO {table} VALUES {', '.join(rows)}")
    return pair


class ExprGen:
    def __init__(self, rng: random.Random, columns: list[str]) -> None:
        self.rng = rng
        self.columns = columns

    def atom(self) -> str:
        rng = self.rng
        roll = rng.random()
        if roll < 0.55:
            return rng.choice(self.columns)
        if roll < 0.7:
            return str(rng.randint(-3, 10))
        if roll < 0.8:
            return repr(rng.randint(-12, 12) / 4)
        if roll < 0.93:
            return literal(rng.choice(TEXTS))
        return "NULL"

    def expr(self, depth: int = 3) -> str:
        rng = self.rng
        if depth == 0 or rng.random() < 0.3:
            return self.atom()
        d = depth - 1
        choice = rng.randrange(12)
        if choice < 3:
            op = rng.choice(["+", "-", "*", "/", "%"])
            return f"({self.expr(d)} {op} {self.expr(d)})"
        if choice == 3:
            return f"({self.expr(d)} || {self.expr(d)})"
        if choice == 4:
            return f"(- {self.expr(d)})"
        return self.predicate(d)

    def predicate(self, depth: int = 2) -> str:
        rng = self.rng
        d = max(depth - 1, 0)
        choice = rng.randrange(10)
        if choice < 3:
            op = rng.choice(["=", "==", "!=", "<>", "<", "<=", ">", ">="])
            return f"({self.expr(d)} {op} {self.expr(d)})"
        if choice == 3:
            op = rng.choice(["AND", "OR"])
            return f"({self.predicate(d)} {op} {self.predicate(d)})"
        if choice == 4:
            return f"(NOT {self.predicate(d)})"
        if choice == 5:
            return f"({self.expr(d)} IS {rng.choice(['', 'NOT '])}NULL)"
        if choice == 6:
            items = ", ".join(self.atom() for _ in range(rng.randint(1, 4)))
            return f"({self.expr(d)} {rng.choice(['', 'NOT '])}IN ({items}))"
        if choice == 7:
            neg = rng.choice(["", "NOT "])
            return f"({self.expr(d)} {neg}BETWEEN {self.atom()} AND {self.atom()})"
        if choice == 8:
            neg = rng.choice(["", "NOT "])
            return f"({self.expr(d)} {neg}LIKE {literal(rng.choice(LIKE_PATTERNS))})"
        op = rng.choice(["IS", "IS NOT"])
        return f"({self.expr(d)} {op} {self.atom()})"


T1_COLS = ["t1.id", "t1.a", "t1.b", "t1.c", "t1.k"]
T2_COLS = ["t2.id", "t2.k", "t2.d", "t2.e"]


def scalar_query(rng: random.Random) -> str:
    gen = ExprGen(rng, ["a", "b", "c", "k", "id"])
    exprs = ", ".join(gen.expr() for _ in range(rng.randint(1, 3)))
    where = f" WHERE {gen.predicate()}" if rng.random() < 0.5 else ""
    return f"SELECT {exprs} FROM t1{where}"


def join_query(rng: random.Random) -> str:
    gen = ExprGen(rng, T1_COLS + T2_COLS)
    join = rng.choice(["JOIN", "LEFT JOIN", "INNER JOIN", "LEFT OUTER JOIN"])
    on = "t1.k = t2.k" if rng.random() < 0.7 else gen.predicate(1)
    cols = rng.sample(T1_COLS + T2_COLS, rng.randint(1, 4))
    where = f" WHERE {gen.predicate(1)}" if rng.random() < 0.5 else ""
    order = ""
    if rng.random() < 0.5:
        keys = [f"{c} {rng.choice(['ASC', 'DESC'])}" for c in cols]
        order = f" ORDER BY {', '.join(keys)}, t1.id, t2.id"
        if rng.random() < 0.5:
            order += f" LIMIT {rng.randint(-1, 6)} OFFSET {rng.randint(0, 3)}"
    return f"SELECT {', '.join(cols)} FROM t1 {join} t2 ON {on}{where}{order}"


def aggregate_query(rng: random.Random) -> str:
    gen = ExprGen(rng, ["a", "b", "c", "k", "id"])
    group_col = rng.choice(["a", "c", "k", "b", "a % 3", "c IS NULL"])
    agg_arg = rng.choice(["a", "b", "c", "id", "k", "a * 2", "b + a"])
    aggs = [
        "COUNT(*)",
        f"COUNT({agg_arg})",
        f"SUM({agg_arg})",
        f"AVG({agg_arg})",
        f"MIN({agg_arg})",
        f"MAX({agg_arg})",
        f"COUNT(DISTINCT {agg_arg})",
    ]
    selected = rng.sample(aggs, rng.randint(1, 4))
    where = f" WHERE {gen.predicate(1)}" if rng.random() < 0.4 else ""
    if rng.random() < 0.25:
        return f"SELECT {', '.join(selected)} FROM t1{where}"
    having = ""
    if rng.random() < 0.4:
        having = f" HAVING {rng.choice(['COUNT(*) > 1', f'SUM({agg_arg}) > 2', 'MIN(id) < 5'])}"
    order = f" ORDER BY 1 {rng.choice(['ASC', 'DESC'])}" if rng.random() < 0.5 else ""
    return (
        f"SELECT {group_col}, {', '.join(selected)} FROM t1{where} "
        f"GROUP BY {group_col}{having}{order}"
    )


def distinct_query(rng: random.Random) -> str:
    cols = rng.sample(["a", "b", "c", "k"], rng.randint(1, 3))
    direction = rng.choice(["ASC", "DESC"])
    limit = f" LIMIT {rng.randint(0, 5)}" if rng.random() < 0.5 else ""
    return (
        f"SELECT DISTINCT {', '.join(cols)} FROM t1 "
        f"ORDER BY {', '.join(f'{c} {direction}' for c in cols)}{limit}"
    )


GENERATORS = [scalar_query, scalar_query, join_query, aggregate_query, distinct_query]


@pytest.mark.parametrize("case", range(40))
def test_random_queries(case):
    rng = random.Random(SEED + case)
    pair = build_pair(rng)
    for _ in range(25):
        sql = rng.choice(GENERATORS)(rng)
        pair.query(sql)


@pytest.mark.parametrize("case", range(10))
def test_random_updates_and_deletes(case):
    rng = random.Random(SEED * 7 + case)
    pair = build_pair(rng)
    gen = ExprGen(rng, ["a", "b", "c", "k", "id"])
    for _ in range(6):
        if rng.random() < 0.6:
            column = rng.choice(["a", "b", "c", "k"])
            pair.run(f"UPDATE t1 SET {column} = {gen.expr(2)} WHERE {gen.predicate(1)}")
        else:
            pair.run(f"DELETE FROM t1 WHERE {gen.predicate(1)}")
        pair.query("SELECT id, a, b, c, k FROM t1")
