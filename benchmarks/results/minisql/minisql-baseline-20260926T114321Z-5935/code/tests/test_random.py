"""Randomized differential testing against sqlite3.

Random data and random queries are run through both engines and must agree exactly.
REAL values are multiples of 0.25 so sums are exact regardless of summation order.
"""

import random
import re

import pytest
from conftest import Pair

INT_COLS = ["i", "j"]
REAL_COLS = ["r"]
TEXT_COLS = ["s"]
TEXTS = ["a", "B", "ab", "", "1", "10", "abc", "A%", "x_y", " 2"]


def rand_value(rng, kind):
    if rng.random() < 0.2:
        return "NULL"
    if kind == "int":
        return str(rng.randint(-4, 6))
    if kind == "real":
        return repr(rng.randint(-12, 12) / 4)
    return "'" + rng.choice(TEXTS) + "'"


def setup(rng) -> Pair:
    p = Pair()
    p.run("CREATE TABLE t (i INTEGER, j INTEGER, r REAL, s TEXT)")
    p.run("CREATE TABLE u (i INTEGER, j INTEGER, r REAL, s TEXT)")
    for table, n in (("t", 25), ("u", 12)):
        rows = []
        for _ in range(n):
            vals = [rand_value(rng, k) for k in ("int", "int", "real", "text")]
            rows.append("(" + ", ".join(vals) + ")")
        p.run(f"INSERT INTO {table} VALUES " + ", ".join(rows))
    return p


class ExprGen:
    def __init__(self, rng, tables):
        self.rng = rng
        self.tables = tables  # qualifiers usable in column references
        # CASE can mix INTEGER and REAL results; when such values (e.g. 2 and 2.0) share a
        # group, which one SQLite reports depends on its sorter's internal row order.
        self.allow_case = True

    def column(self):
        col = self.rng.choice(INT_COLS + REAL_COLS + TEXT_COLS)
        if len(self.tables) > 1:
            return f"{self.rng.choice(self.tables)}.{col}"
        return col

    def literal(self):
        return rand_value(self.rng, self.rng.choice(["int", "int", "real", "text"]))

    def expr(self, depth=0):
        rng = self.rng
        if depth >= 3 or rng.random() < 0.3:
            return self.column() if rng.random() < 0.65 else self.literal()
        choice = rng.randrange(12)
        a = self.expr(depth + 1)
        if choice <= 2:
            op = rng.choice(["+", "-", "*", "/", "%", "||"])
            return f"({a} {op} {self.expr(depth + 1)})"
        if choice <= 4:
            op = rng.choice(["=", "!=", "<", "<=", ">", ">=", "<>", "=="])
            return f"({a} {op} {self.expr(depth + 1)})"
        if choice == 5:
            op = rng.choice(["AND", "OR"])
            return f"({a} {op} {self.expr(depth + 1)})"
        if choice == 6:
            return f"(NOT {a})" if rng.random() < 0.5 else f"(- {a})"
        if choice == 7:
            return f"({a} IS {'NOT ' if rng.random() < 0.5 else ''}NULL)"
        if choice == 8:
            items = ", ".join(self.expr(depth + 2) for _ in range(rng.randint(1, 3)))
            return f"({a} {'NOT ' if rng.random() < 0.3 else ''}IN ({items}))"
        if choice == 9:
            neg = "NOT " if rng.random() < 0.3 else ""
            return f"({a} {neg}BETWEEN {self.expr(depth + 2)} AND {self.expr(depth + 2)})"
        if choice == 10:
            pat = rng.choice(["'a%'", "'%b'", "'_'", "'%'", "'1%'", "'%a%'", "'A_'", self.column()])
            return f"({a} {'NOT ' if rng.random() < 0.3 else ''}LIKE {pat})"
        if not self.allow_case:
            return f"({a} IS NULL)"
        return f"(CASE WHEN {a} THEN {self.expr(depth + 1)} ELSE {self.expr(depth + 1)} END)"

    def aggregate(self):
        rng = self.rng
        fn = rng.choice(["count", "sum", "avg", "min", "max", "total"])
        if fn == "count" and rng.random() < 0.3:
            return "count(*)"
        distinct = "DISTINCT " if rng.random() < 0.2 else ""
        return f"{fn}({distinct}{self.expr(2)})"


def order_by_all(rng, n):
    terms = [f"{k} {rng.choice(['ASC', 'DESC'])}" for k in range(1, n + 1)]
    rng.shuffle(terms)
    return " ORDER BY " + ", ".join(terms)


@pytest.mark.parametrize("seed", range(8))
def test_random_filters(seed):
    rng = random.Random(seed)
    p = setup(rng)
    g = ExprGen(rng, ["t"])
    for _ in range(60):
        cols = [g.expr() for _ in range(rng.randint(1, 3))]
        sql = f"SELECT {', '.join(cols)} FROM t WHERE {g.expr()}"
        if rng.random() < 0.5:
            sql += order_by_all(rng, len(cols))
            if rng.random() < 0.5:
                sql += f" LIMIT {rng.randint(0, 10)} OFFSET {rng.randint(0, 5)}"
        p.check(sql)


@pytest.mark.parametrize("seed", range(8))
def test_random_aggregates(seed):
    rng = random.Random(1000 + seed)
    p = setup(rng)
    g = ExprGen(rng, ["t"])
    for _ in range(50):
        g.allow_case = False
        groups = [g.expr(2) if rng.random() < 0.5 else g.column() for _ in range(rng.randint(0, 2))]
        g.allow_case = True
        # SQLite constant-folds some column-free GROUP BY terms into column positions, and
        # which ones differs between SQLite versions; keep every term column-dependent.
        groups = [e if re.search(r"\b[ijrs]\b", e) else g.column() for e in groups]
        aggs = [g.aggregate() for _ in range(rng.randint(1, 3))]
        sql = f"SELECT {', '.join(groups + aggs)} FROM t"
        if rng.random() < 0.5:
            sql += f" WHERE {g.expr(1)}"
        if groups:
            sql += f" GROUP BY {', '.join(groups)}"
            if rng.random() < 0.4:
                sql += f" HAVING {g.aggregate()} > {g.literal()}"
        if rng.random() < 0.5:
            sql += order_by_all(rng, len(groups) + len(aggs))
        # SQLite folds some constant GROUP BY terms into column positions and then
        # rejects them; accept agreement on such errors.
        p.check_or_both_fail(sql)


@pytest.mark.parametrize("seed", range(8))
def test_random_joins(seed):
    rng = random.Random(2000 + seed)
    p = setup(rng)
    g = ExprGen(rng, ["a", "b"])
    for _ in range(40):
        kind = rng.choice(["JOIN", "LEFT JOIN", "LEFT OUTER JOIN", "INNER JOIN"])
        col = rng.choice(INT_COLS + REAL_COLS + TEXT_COLS)
        left = f"a.{col}"
        right = f"b.{rng.choice(INT_COLS + REAL_COLS + TEXT_COLS)}"
        if rng.random() < 0.3:
            left = f"({left} {rng.choice(['+', '||', '*'])} {g.literal()})"
        on = f"{left} = {right}" if rng.random() < 0.5 else f"{right} = {left}"
        if rng.random() < 0.4:
            on = f"({on}) {rng.choice(['AND', 'OR'])} {g.expr(1)}"
        cols = [g.expr(1) for _ in range(rng.randint(1, 3))]
        sql = f"SELECT {', '.join(cols)} FROM t a {kind} u b ON {on}"
        if rng.random() < 0.5:
            sql += f" WHERE {g.expr(1)}"
        if rng.random() < 0.3:
            sql = f"SELECT count(*), {g.aggregate()} FROM t a {kind} u b ON {on}"
        p.check(sql)


@pytest.mark.parametrize("seed", range(4))
def test_random_updates_and_deletes(seed):
    rng = random.Random(3000 + seed)
    p = setup(rng)
    g = ExprGen(rng, ["t"])
    for _ in range(25):
        if rng.random() < 0.7:
            col = rng.choice(INT_COLS + REAL_COLS + TEXT_COLS)
            p.run(f"UPDATE t SET {col} = {g.expr(1)} WHERE {g.expr(1)}")
        else:
            p.run(f"DELETE FROM t WHERE {g.expr(1)}")
        p.check("SELECT i, typeof(i), j, typeof(j), r, typeof(r), s, typeof(s) FROM t")
