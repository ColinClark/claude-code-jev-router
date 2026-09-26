"""Randomized differential testing against sqlite3 (deterministic seeds)."""

import os
import random
import sqlite3

import pytest

from minisql import Database, SQLError

INTS = ["0", "1", "2", "-1", "3", "5", "-7", "10", "100", "9223372036854775807"]
REALS = ["0.0", "0.5", "-2.5", "3.0", "1.25", "1e3", "-0.1", "7.75"]
TEXTS = ["'a'", "'B'", "'abc'", "'10'", "'5'", "''", "' 3'", "'x%y'", "'2.5'", "'Ab_c'"]
LIKE_PATTERNS = ["'a%'", "'%b%'", "'_'", "'%'", "'A_C'", "'1%'", "'%5'", "''", "'x\\%y'"]

TABLES = {
    "t1": [("a", "INTEGER"), ("b", "REAL"), ("c", "TEXT"), ("d", "INTEGER")],
    "t2": [("a", "INTEGER"), ("e", "TEXT"), ("f", "REAL")],
}


def literal_for(rng, typ):
    if rng.random() < 0.2:
        return "NULL"
    pool = {"INTEGER": INTS[:-1], "REAL": REALS, "TEXT": TEXTS}[typ]
    return rng.choice(pool)


class ExprGen:
    def __init__(self, rng, columns):
        self.rng = rng
        self.columns = columns  # list of SQL column refs

    def literal(self):
        return self.rng.choice(INTS + REALS + TEXTS + ["NULL"])

    def leaf(self):
        if self.columns and self.rng.random() < 0.65:
            return self.rng.choice(self.columns)
        return self.literal()

    def expr(self, depth=0):
        rng = self.rng
        if depth >= 3 or rng.random() < 0.3:
            return self.leaf()
        a = lambda: self.expr(depth + 1)  # noqa: E731
        choice = rng.randrange(14)
        if choice == 0:
            return f"({a()} {rng.choice(['+', '-', '*', '/', '%'])} {a()})"
        if choice == 1:
            return f"({a()} || {a()})"
        if choice == 2:
            op = rng.choice(["=", "==", "!=", "<>", "<", "<=", ">", ">="])
            return f"({a()} {op} {a()})"
        if choice == 3:
            return f"({a()} {rng.choice(['AND', 'OR'])} {a()})"
        if choice == 4:
            return f"(NOT {a()})"
        if choice == 5:
            return f"({a()} IS {rng.choice(['', 'NOT '])}NULL)"
        if choice == 6:
            items = ", ".join(self.expr(depth + 1) for _ in range(rng.randrange(1, 4)))
            return f"({a()} {rng.choice(['', 'NOT '])}IN ({items}))"
        if choice == 7:
            return f"({a()} {rng.choice(['', 'NOT '])}BETWEEN {a()} AND {a()})"
        if choice == 8:
            pat = rng.choice(LIKE_PATTERNS) if rng.random() < 0.7 else a()
            esc = " ESCAPE '\\'" if "\\" in pat else ""
            return f"({a()} {rng.choice(['', 'NOT '])}LIKE {pat}{esc})"
        if choice == 9:
            return f"(-{a()})"
        if choice == 10:
            return f"CASE WHEN {a()} THEN {a()} ELSE {a()} END"
        if choice == 11:
            return f"coalesce({a()}, {a()})"
        if choice == 12:
            return f"({a()} IS {rng.choice(['', 'NOT '])}{a()})"
        return f"abs({a()})"


def build(rng):
    db = Database()
    ref = sqlite3.connect(":memory:")
    for name, cols in TABLES.items():
        ddl = f"CREATE TABLE {name} ({', '.join(f'{c} {t}' for c, t in cols)})"
        db.execute(ddl)
        ref.execute(ddl)
        rows = []
        for _ in range(rng.randrange(0, 9)):
            rows.append("(" + ", ".join(literal_for(rng, t) for _, t in cols) + ")")
        if rows:
            sql = f"INSERT INTO {name} VALUES {', '.join(rows)}"
            db.execute(sql)
            ref.execute(sql)
    return db, ref


def run_both(db, ref, sql):
    try:
        expected = ref.execute(sql).fetchall()
    except sqlite3.Error:
        with pytest.raises(SQLError):
            db.execute(sql)
        return None, None
    return db.execute(sql), expected


def typed(rows):
    return [tuple((type(v).__name__, v) for v in r) for r in rows]


def assert_same(sql, actual, expected, ordered):
    a, e = typed(actual), typed(expected)
    if not ordered:
        a.sort(key=repr)
        e.sort(key=repr)
    assert a == e, f"{sql}\n minisql: {actual}\n  sqlite: {expected}"


def random_query(rng):
    joined = rng.random() < 0.4
    if joined:
        kind = rng.choice(["JOIN", "LEFT JOIN"])
        columns = ["x.a", "x.b", "x.c", "x.d", "y.a", "y.e", "y.f", "b", "c", "e", "f"]
        gen = ExprGen(rng, columns)
        on = rng.choice(["x.a = y.a", "x.c = y.e", gen.expr(1)])
        from_clause = f"t1 x {kind} t2 y ON {on}"
    else:
        columns = ["a", "b", "c", "d", "t1.a"]
        gen = ExprGen(rng, columns)
        from_clause = "t1"
    where = f" WHERE {gen.expr()}" if rng.random() < 0.6 else ""
    if rng.random() < 0.35:
        keys = [rng.choice(columns) for _ in range(rng.randrange(1, 3))]
        aggs = []
        for _ in range(rng.randrange(1, 4)):
            fn = rng.choice(["COUNT", "SUM", "AVG", "MIN", "MAX", "total"])
            arg = "*" if fn == "COUNT" and rng.random() < 0.3 else gen.expr(1)
            distinct = "DISTINCT " if arg != "*" and rng.random() < 0.2 else ""
            aggs.append(f"{fn}({distinct}{arg})")
        items = keys + aggs
        group = f" GROUP BY {', '.join(keys)}" if rng.random() < 0.8 else ""
        if not group:
            items = aggs
        having = f" HAVING {rng.choice(aggs)} > {rng.choice(INTS[:6])}" if (
            group and rng.random() < 0.3) else ""
        sql = f"SELECT {', '.join(items)} FROM {from_clause}{where}{group}{having}"
    else:
        items = [gen.expr() for _ in range(rng.randrange(1, 4))]
        distinct = "DISTINCT " if rng.random() < 0.2 else ""
        sql = f"SELECT {distinct}{', '.join(items)} FROM {from_clause}{where}"
    ordered = False
    if rng.random() < 0.5:
        n = len(items)
        terms = [f"{i} {rng.choice(['ASC', 'DESC'])}" for i in rng.sample(range(1, n + 1), n)]
        sql += " ORDER BY " + ", ".join(terms)
        ordered = True
        if rng.random() < 0.3:
            sql += f" LIMIT {rng.randrange(0, 5)} OFFSET {rng.randrange(0, 3)}"
    return sql, ordered


ITERATIONS = int(os.environ.get("MINISQL_FUZZ_ITERATIONS", "60"))


@pytest.mark.parametrize("seed", range(ITERATIONS))
def test_random_queries(seed):
    rng = random.Random(seed)
    db, ref = build(rng)
    for _ in range(25):
        sql, ordered = random_query(rng)
        actual, expected = run_both(db, ref, sql)
        if expected is not None:
            assert_same(sql, actual, expected, ordered)


@pytest.mark.parametrize("seed", range(ITERATIONS // 3))
def test_random_mutations(seed):
    rng = random.Random(10_000 + seed)
    db, ref = build(rng)
    gen = ExprGen(rng, ["a", "b", "c", "d"])
    for _ in range(8):
        r = rng.random()
        if r < 0.4:
            col = rng.choice(["a", "b", "c", "d"])
            sql = f"UPDATE t1 SET {col} = {gen.expr(1)} WHERE {gen.expr(1)}"
        elif r < 0.6:
            sql = f"DELETE FROM t1 WHERE {gen.expr(1)}"
        else:
            vals = ", ".join(gen.literal() for _ in range(4))
            sql = f"INSERT INTO t1 VALUES ({vals})"
        run_both(db, ref, sql)
        actual, expected = run_both(db, ref, "SELECT a, b, c, d FROM t1")
        assert_same(sql, actual, expected, ordered=False)
