"""Randomised differential testing against sqlite3."""

import random

import pytest
from conftest import Both

TABLES = {
    "t1": [("a", "INTEGER"), ("b", "REAL"), ("c", "TEXT")],
    "t2": [("a", "INTEGER"), ("d", "INTEGER"), ("e", "TEXT")],
}
TEXTS = ["a", "B", "abc", "Abc", "b%", "", "10", "5", "x_y", "hello world", "1.5"]


def _value(rng, typ):
    if rng.random() < 0.2:
        return "NULL"
    if typ == "INTEGER":
        return str(rng.randint(-5, 12))
    if typ == "REAL":
        return rng.choice(["0.5", "-1.25", "2.0", "3.75", "10.0", "-0.0", "7.1"])
    return "'" + rng.choice(TEXTS) + "'"


def _populate(both, rng):
    for name, cols in TABLES.items():
        both.run(f"CREATE TABLE {name} (" + ", ".join(f"{c} {t}" for c, t in cols) + ")")
        rows = [
            "(" + ", ".join(_value(rng, t) for _, t in cols) + ")" for _ in range(rng.randint(0, 9))
        ]
        if rows:
            both.run(f"INSERT INTO {name} VALUES " + ", ".join(rows))


class Gen:
    def __init__(self, rng, cols):
        self.rng = rng
        self.cols = cols  # list of (qualified name, type)

    def literal(self):
        r = self.rng.random()
        if r < 0.1:
            return "NULL"
        if r < 0.5:
            return str(self.rng.randint(-3, 10))
        if r < 0.7:
            return self.rng.choice(["0.5", "2.5", "-1.5", "3.0", "0.0"])
        return "'" + self.rng.choice(TEXTS) + "'"

    def expr(self, depth=0):
        rng = self.rng
        if depth > 2 or rng.random() < 0.3:
            return rng.choice(self.cols)[0] if rng.random() < 0.7 else self.literal()
        k = rng.randint(0, 11)
        e = lambda: self.expr(depth + 1)  # noqa: E731
        if k == 0:
            return f"({e()} {rng.choice(['+', '-', '*', '/', '%'])} {e()})"
        if k == 1:
            return f"({e()} || {e()})"
        if k == 2:
            return f"({e()} {rng.choice(['=', '!=', '<', '<=', '>', '>=', '<>', '=='])} {e()})"
        if k == 3:
            return f"({e()} {rng.choice(['AND', 'OR'])} {e()})"
        if k == 4:
            return f"(NOT {e()})"
        if k == 5:
            return f"({e()} IS {rng.choice(['', 'NOT '])}NULL)"
        if k == 6:
            items = ", ".join(self.expr(depth + 1) for _ in range(rng.randint(1, 3)))
            return f"({e()} {rng.choice(['', 'NOT '])}IN ({items}))"
        if k == 7:
            return f"({e()} {rng.choice(['', 'NOT '])}BETWEEN {e()} AND {e()})"
        if k == 8:
            pat = rng.choice(["'a%'", "'%b%'", "'_'", "'%'", "'A_C'", "'1%'", "'%.5'"])
            return f"({e()} {rng.choice(['', 'NOT '])}LIKE {pat})"
        if k == 9:
            return f"(- {e()})"
        if k == 10:
            return f"CASE WHEN {e()} THEN {e()} ELSE {e()} END"
        return f"({e()} IS {rng.choice(['', 'NOT '])}{e()})"

    def agg(self):
        rng = self.rng
        fn = rng.choice(["COUNT", "SUM", "AVG", "MIN", "MAX", "TOTAL"])
        if fn == "COUNT" and rng.random() < 0.3:
            return "COUNT(*)"
        distinct = "DISTINCT " if rng.random() < 0.2 else ""
        return f"{fn}({distinct}{self.expr(2)})"


def _from_clause(rng):
    kind = rng.choice(["single", "inner", "left", "left2"])
    if kind == "single":
        return "t1 x", [("x.a", "INTEGER"), ("x.b", "REAL"), ("x.c", "TEXT")]
    cols = [("x.a", "INTEGER"), ("x.b", "REAL"), ("x.c", "TEXT"), ("y.a", "INTEGER"),
            ("y.d", "INTEGER"), ("y.e", "TEXT")]
    on = rng.choice(["x.a = y.a", "x.a = y.d", "x.c = y.e", "x.a < y.d", "y.d IS NULL"])
    if kind == "inner":
        return f"t1 x JOIN t2 y ON {on}", cols
    if kind == "left":
        return f"t1 x LEFT JOIN t2 y ON {on}", cols
    return f"t2 y LEFT JOIN t1 x ON {on}", cols


def _query(rng):
    frm, cols = _from_clause(rng)
    g = Gen(rng, cols)
    where = f" WHERE {g.expr()}" if rng.random() < 0.6 else ""
    if rng.random() < 0.4:
        keys = [g.expr(2) for _ in range(rng.randint(0, 2))]
        items = keys + [g.agg() for _ in range(rng.randint(1, 3))]
        group = f" GROUP BY {', '.join(keys)}" if keys else ""
        having = f" HAVING {g.agg()} > {g.literal()}" if rng.random() < 0.3 else ""
        sel = ", ".join(items)
        order = " ORDER BY " + ", ".join(
            f"{i + 1} {rng.choice(['ASC', 'DESC'])}" for i in range(len(items))
        )
        return f"SELECT {sel} FROM {frm}{where}{group}{having}{order}"
    items = [g.expr() for _ in range(rng.randint(1, 3))]
    distinct = "DISTINCT " if rng.random() < 0.2 else ""
    order = " ORDER BY " + ", ".join(
        f"{i + 1} {rng.choice(['ASC', 'DESC'])}" for i in range(len(items))
    )
    limit = ""
    if rng.random() < 0.3:
        limit = f" LIMIT {rng.randint(0, 5)} OFFSET {rng.randint(0, 3)}"
    return f"SELECT {distinct}{', '.join(items)} FROM {frm}{where}{order}{limit}"


@pytest.mark.parametrize("seed", range(40))
def test_random_queries(seed):
    rng = random.Random(seed)
    both = Both()
    _populate(both, rng)
    for _ in range(60):
        sql = _query(rng)
        both.check(sql, ordered=True, allow_error=True)


@pytest.mark.parametrize("seed", range(10))
def test_random_dml(seed):
    rng = random.Random(1000 + seed)
    both = Both()
    _populate(both, rng)
    g = Gen(rng, [("a", "INTEGER"), ("b", "REAL"), ("c", "TEXT")])
    for _ in range(15):
        k = rng.random()
        if k < 0.4:
            both.run(f"UPDATE t1 SET {rng.choice('abc')} = {g.expr(1)} WHERE {g.expr()}")
        elif k < 0.6:
            both.run(f"DELETE FROM t1 WHERE {g.expr()}")
        else:
            both.run(f"INSERT INTO t1 VALUES ({g.literal()}, {g.literal()}, {g.literal()})")
        both.check("SELECT a, b, c FROM t1 ORDER BY 1, 2, 3")
