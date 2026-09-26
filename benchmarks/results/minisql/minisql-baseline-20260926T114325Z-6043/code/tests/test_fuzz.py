"""Randomised differential testing against sqlite3 (deterministic seeds)."""

import random
import sqlite3

import pytest

from minisql import Database, SQLError

from .conftest import typed, unordered

TABLES = {
    "t1": [("a", "INTEGER"), ("b", "REAL"), ("c", "TEXT"), ("d", "INTEGER")],
    "t2": [("a", "INTEGER"), ("e", "TEXT"), ("f", "REAL")],
}
TEXTS = ["apple", "Apple", "banana", "b", "", "a_b", "a%b", "10", "9", "Zed", "zed", "x y"]


def random_value(rng, type_name):
    if rng.random() < 0.15:
        return "NULL"
    if type_name == "INTEGER":
        return str(rng.choice([rng.randint(-5, 5), rng.randint(-100, 100), 0, 1]))
    if type_name == "REAL":
        return repr(rng.choice([rng.randint(-20, 20) / 4, rng.uniform(-100, 100), 0.0, 1.5]))
    text = rng.choice(TEXTS)
    return "'" + text.replace("'", "''") + "'"


class Gen:
    def __init__(self, rng, columns):
        self.rng = rng
        self.columns = columns  # list of (qualified name, type)

    def column(self, want=None):
        cols = [c for c in self.columns if want is None or c[1] == want] or self.columns
        return self.rng.choice(cols)[0]

    def literal(self):
        return random_value(self.rng, self.rng.choice(["INTEGER", "INTEGER", "REAL", "TEXT"]))

    def expr(self, depth=0):
        r = self.rng.random()
        if depth >= 3 or r < 0.3:
            return self.column() if self.rng.random() < 0.7 else self.literal()
        choice = self.rng.randrange(8)
        if choice == 0:
            op = self.rng.choice(["+", "-", "*", "/", "%"])
            return f"({self.expr(depth + 1)} {op} {self.expr(depth + 1)})"
        if choice == 1:
            return f"(-{self.expr(depth + 1)})"
        if choice == 2:
            return f"({self.column('TEXT')} || {self.expr(depth + 1)})"
        return self.cond(depth + 1)

    def cond(self, depth=0):
        choice = self.rng.randrange(9)
        e = self.expr
        if depth >= 3:
            choice = self.rng.choice([0, 3])
        if choice == 0:
            op = self.rng.choice(["=", "==", "!=", "<>", "<", "<=", ">", ">="])
            return f"({e(depth + 1)} {op} {e(depth + 1)})"
        if choice == 1:
            op = self.rng.choice(["AND", "OR"])
            return f"({self.cond(depth + 1)} {op} {self.cond(depth + 1)})"
        if choice == 2:
            return f"(NOT {self.cond(depth + 1)})"
        if choice == 3:
            return f"({e(depth + 1)} IS {self.rng.choice(['', 'NOT '])}NULL)"
        if choice == 4:
            items = ", ".join(self.literal() for _ in range(self.rng.randint(0, 3)))
            neg = self.rng.choice(["", "NOT "])
            return f"({e(depth + 1)} {neg}IN ({items}))"
        if choice == 5:
            neg = self.rng.choice(["", "NOT "])
            return f"({e(depth + 1)} {neg}BETWEEN {e(depth + 1)} AND {e(depth + 1)})"
        if choice == 6:
            pat = self.rng.choice(["'a%'", "'%b%'", "'_'", "'%'", "'A_P%'", "'1%'", "'%.%'"])
            neg = self.rng.choice(["", "NOT "])
            return f"({e(depth + 1)} {neg}LIKE {pat})"
        return e(depth + 1)

    def aggregate(self):
        fn = self.rng.choice(["COUNT", "SUM", "AVG", "MIN", "MAX", "TOTAL", "COUNT"])
        if fn == "COUNT" and self.rng.random() < 0.3:
            return "COUNT(*)"
        distinct = "DISTINCT " if self.rng.random() < 0.2 else ""
        if fn in ("SUM", "AVG", "TOTAL"):
            arg = self.column(self.rng.choice(["INTEGER", "REAL"]))
        else:
            arg = self.expr(2)
        return f"{fn}({distinct}{arg})"


def setup(rng):
    db, ref = Database(), sqlite3.connect(":memory:")
    for name, cols in TABLES.items():
        ddl = f"CREATE TABLE {name} ({', '.join(f'{c} {t}' for c, t in cols)})"
        rows = [
            "(" + ", ".join(random_value(rng, t) for _, t in cols) + ")"
            for _ in range(rng.randint(0, 12))
        ]
        stmts = [ddl] + ([f"INSERT INTO {name} VALUES {', '.join(rows)}"] if rows else [])
        for sql in stmts:
            db.execute(sql)
            ref.execute(sql)
    return db, ref


def build_query(rng):
    join = rng.random() < 0.5
    if join:
        kind = rng.choice(["JOIN", "LEFT JOIN", "LEFT OUTER JOIN", "INNER JOIN"])
        columns = [(f"x.{c}", t) for c, t in TABLES["t1"]] + [
            (f"y.{c}", t) for c, t in TABLES["t2"]
        ]
        gen = Gen(rng, columns)
        on = rng.choice(["x.a = y.a", "x.d = y.a", gen.cond(1)])
        source = f"t1 x {kind} t2 y ON {on}"
    else:
        columns = [(c, t) for c, t in TABLES["t1"]]
        gen = Gen(rng, columns)
        source = "t1"
    where = f" WHERE {gen.cond()}" if rng.random() < 0.6 else ""
    if rng.random() < 0.4:
        keys = [gen.column() for _ in range(rng.randint(1, 2))]
        items = keys + [gen.aggregate() for _ in range(rng.randint(1, 3))]
        group = f" GROUP BY {', '.join(keys)}"
        having = ""
        if rng.random() < 0.4:
            op = rng.choice([">", "<", "=", ">="])
            having = f" HAVING {gen.aggregate()} {op} {rng.randint(-2, 5)}"
        distinct = ""
    elif rng.random() < 0.2:
        items = [gen.aggregate() for _ in range(rng.randint(1, 4))]
        group = having = distinct = ""
    else:
        items = [gen.expr() for _ in range(rng.randint(1, 4))]
        group = having = ""
        distinct = "DISTINCT " if rng.random() < 0.2 else ""
    order = ""
    limit = ""
    if rng.random() < 0.6:
        terms = [f"{i} {rng.choice(['ASC', 'DESC', ''])}" for i in range(1, len(items) + 1)]
        rng.shuffle(terms)
        order = " ORDER BY " + ", ".join(terms)
        if rng.random() < 0.4:
            limit = f" LIMIT {rng.randint(0, 6)}"
            if rng.random() < 0.5:
                limit += f" OFFSET {rng.randint(0, 3)}"
    sql = f"SELECT {distinct}{', '.join(items)} FROM {source}{where}{group}{having}{order}{limit}"
    return sql, bool(order)


@pytest.mark.parametrize("seed", range(300))
def test_random_queries(seed):
    rng = random.Random(seed)
    db, ref = setup(rng)
    for _ in range(15):
        sql, ordered = build_query(rng)
        try:
            expected = ref.execute(sql).fetchall()
        except sqlite3.Error:
            with pytest.raises(SQLError):
                db.execute(sql)
            continue
        actual = db.execute(sql)
        if ordered:
            assert typed(actual) == typed(expected), sql
        else:
            assert unordered(actual) == unordered(expected), sql


def build_ordered_query(rng):
    """Up to three-way joins, ORDER BY arbitrary expressions (appended to the output so that
    the sort keys can be compared even when ties leave the row order unspecified)."""
    n = rng.choice([1, 2, 3])
    cols = [(f"x.{c}", t) for c, t in TABLES["t1"]]
    source = "t1 x"
    if n >= 2:
        cols += [(f"y.{c}", t) for c, t in TABLES["t2"]]
        on = rng.choice(["x.a = y.a", "x.c = y.e", "x.b > y.f", Gen(rng, cols).cond(1)])
        source += f" {rng.choice(['JOIN', 'LEFT JOIN'])} t2 y ON {on}"
    if n == 3:
        cols += [(f"z.{c}", t) for c, t in TABLES["t1"]]
        on = rng.choice(["z.a = y.a", "z.d = x.a", "z.c LIKE x.c", Gen(rng, cols).cond(1)])
        source += f" {rng.choice(['JOIN', 'LEFT JOIN'])} t1 z ON {on}"
    gen = Gen(rng, cols)
    where = f" WHERE {gen.cond()}" if rng.random() < 0.5 else ""
    if rng.random() < 0.5:
        keys = [gen.expr(2) for _ in range(rng.randint(1, 2))]
        items = keys + [gen.aggregate() for _ in range(rng.randint(1, 2))]
        having = ""
        if rng.random() < 0.5:
            op = rng.choice([">", "<", "=", "<>"])
            having = f" HAVING {gen.aggregate()} {op} {gen.literal()}"
        tail = f" GROUP BY {', '.join(keys)}{having}"
        order_keys = [rng.choice(keys + [gen.aggregate()]) for _ in range(rng.randint(1, 2))]
    else:
        items = [gen.expr() for _ in range(rng.randint(1, 3))]
        tail = ""
        order_keys = [gen.expr(1) for _ in range(rng.randint(1, 2))]
    width = len(items)
    items += order_keys
    order = ", ".join(f"{o} {rng.choice(['ASC', 'DESC', ''])}" for o in order_keys)
    return f"SELECT {', '.join(items)} FROM {source}{where}{tail} ORDER BY {order}", width


@pytest.mark.parametrize("seed", range(200))
def test_random_ordered_queries(seed):
    rng = random.Random(seed * 7 + 1)
    db, ref = setup(rng)
    for _ in range(10):
        sql, width = build_ordered_query(rng)
        try:
            expected = ref.execute(sql).fetchall()
        except sqlite3.Error:
            with pytest.raises(SQLError):
                db.execute(sql)
            continue
        actual = db.execute(sql)
        assert unordered(actual) == unordered(expected), sql
        assert typed([r[width:] for r in actual]) == typed([r[width:] for r in expected]), sql
