"""Seeded randomized differential testing: generated expressions and queries vs sqlite3.

Every generated statement is run on both engines. Results must be identical (values and
Python types); statements that both engines reject count as agreement but are tracked so
the generator stays mostly valid.
"""

from __future__ import annotations

import random
import re
import sqlite3

import pytest

from minisql import Database, SQLError
from tests.conftest import typed

SEED = 20260926

INT_LITERALS = [-5, -1, 0, 1, 2, 3, 7, 12]
REAL_LITERALS = ["0.5", "1.5", "2.0", "-2.5", "0.0", "10.0", "0.25"]
STRING_LITERALS = ["'abc'", "'ABC'", "'b'", "'5'", "'10'", "'3abc'", "''", "'a%'", "'x_y'",
                   "'2.5'", "' 7'", "'-1'", "'it''s'", "'Z'"]
LIKE_PATTERNS = ["'a%'", "'%B%'", "'_'", "'%5'", "'___'", "'%'", "'x_y'", "'A_C'", "'%c'", "'1%'"]

T1_ROWS = [
    (1, 5, 1.5, "abc"), (2, -3, 0.0, "ABC"), (3, None, 2.25, "b"), (4, 7, None, "5"),
    (5, 0, 10.0, None), (6, 10, -1.5, "10"), (7, 5, 1.5, "3abc"), (8, 2, 0.5, ""),
    (9, None, None, None), (10, 1, 2.0, "a%"), (11, -1, 0.25, " 7"), (12, 3, 1.5, "x_y"),
]
T2_ROWS = [
    (1, 1, "abc", 2.0), (2, 2, "b", 0.5), (3, None, "ABC", None), (4, 5, None, 1.5),
    (5, 1, "5", -2.5), (6, 3, "z", 0.0), (7, 2, "10", 10.0), (8, 7, "", 0.25),
]


def _lit(v: object) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return repr(v)


def _insert(table: str, rows: list[tuple]) -> str:
    return f"INSERT INTO {table} VALUES " + ", ".join(
        "(" + ", ".join(_lit(v) for v in r) + ")" for r in rows
    )


SCHEMA = [
    "CREATE TABLE t1 (id INTEGER, a INTEGER, b REAL, c TEXT)",
    _insert("t1", T1_ROWS),
    "CREATE TABLE t2 (id INTEGER, k INTEGER, name TEXT, w REAL)",
    _insert("t2", T2_ROWS),
]


class Gen:
    def __init__(self, rng: random.Random, columns: list[str]) -> None:
        self.rng = rng
        self.columns = columns

    def leaf(self) -> str:
        r = self.rng.random()
        if r < 0.45 and self.columns:
            return self.rng.choice(self.columns)
        if r < 0.65:
            return str(self.rng.choice(INT_LITERALS))
        if r < 0.80:
            return self.rng.choice(REAL_LITERALS)
        if r < 0.95:
            return self.rng.choice(STRING_LITERALS)
        return "NULL"

    def wrap(self, s: str) -> str:
        # Mostly parenthesize; sometimes rely on operator precedence.
        return s if self.rng.random() < 0.3 else f"({s})"

    def expr(self, depth: int) -> str:
        if depth <= 0 or self.rng.random() < 0.25:
            return self.leaf()
        rng = self.rng
        kind = rng.choice(
            ["arith", "arith", "concat", "cmp", "cmp", "logic", "not", "isnull", "is", "in",
             "between", "like", "neg", "func"]
        )
        d = depth - 1
        if kind == "arith":
            op = rng.choice(["+", "-", "*", "/", "%"])
            return self.wrap(f"{self.expr(d)} {op} {self.expr(d)}")
        if kind == "concat":
            return self.wrap(f"{self.expr(d)} || {self.expr(d)}")
        if kind == "cmp":
            op = rng.choice(["=", "==", "!=", "<>", "<", "<=", ">", ">="])
            return self.wrap(f"{self.expr(d)} {op} {self.expr(d)}")
        if kind == "logic":
            op = rng.choice(["AND", "OR"])
            return self.wrap(f"{self.expr(d)} {op} {self.expr(d)}")
        if kind == "not":
            return self.wrap(f"NOT {self.expr(d)}")
        if kind == "isnull":
            return self.wrap(f"{self.expr(d)} IS {rng.choice(['', 'NOT '])}NULL")
        if kind == "is":
            return self.wrap(f"{self.expr(d)} IS {rng.choice(['', 'NOT '])}{self.expr(d)}")
        if kind == "in":
            n = rng.choice([0, 1, 2, 3])
            items = ", ".join(self.expr(d) for _ in range(n))
            return self.wrap(f"{self.expr(d)} {rng.choice(['', 'NOT '])}IN ({items})")
        if kind == "between":
            neg = rng.choice(["", "NOT "])
            return self.wrap(f"{self.expr(d)} {neg}BETWEEN {self.expr(d)} AND {self.expr(d)}")
        if kind == "like":
            pat = rng.choice(LIKE_PATTERNS) if rng.random() < 0.7 else self.expr(d)
            return self.wrap(f"{self.expr(d)} {rng.choice(['', 'NOT '])}LIKE {pat}")
        if kind == "neg":
            return f"-({self.expr(d)})"  # parenthesized: "- -5" must not become a "--" comment
        fn = rng.choice(["typeof", "abs", "length", "upper", "lower", "coalesce", "ifnull"])
        if fn in ("coalesce", "ifnull"):
            return f"{fn}({self.expr(d)}, {self.expr(d)})"
        return f"{fn}({self.expr(d)})"

    def order_term(self, depth: int) -> str:
        """An ORDER BY expression that is never a bare integer (those are positional)."""
        e = self.expr(depth)
        return f"{e} + 0" if re.fullmatch(r"-?\d+", e) else e

    def aggregate(self, depth: int) -> str:
        fn = self.rng.choice(["COUNT", "SUM", "AVG", "MIN", "MAX", "COUNT DISTINCT", "COUNT(*)"])
        if fn == "COUNT(*)":
            return "COUNT(*)"
        if fn == "COUNT DISTINCT":
            return f"COUNT(DISTINCT {self.expr(depth)})"
        return f"{fn}({self.expr(depth)})"


class Runner:
    def __init__(self) -> None:
        self.db = Database()
        self.sq = sqlite3.connect(":memory:")
        for s in SCHEMA:
            self.db.execute(s)
            self.sq.execute(s)
        self.errors = 0
        self.ok = 0

    def check(self, sql: str, ordered: bool) -> None:
        try:
            expected: object = self.sq.execute(sql).fetchall()
        except sqlite3.Error as exc:
            expected = ("error", str(exc))
        try:
            actual: object = self.db.execute(sql)
        except SQLError as exc:
            actual = ("error", str(exc))
        if isinstance(expected, tuple) or isinstance(actual, tuple):
            assert isinstance(expected, tuple) and isinstance(actual, tuple), (
                f"\nSQL: {sql}\nminisql: {actual}\nsqlite : {expected}"
            )
            self.errors += 1
            return
        e, a = typed(expected), typed(actual)
        if not ordered:
            e, a = sorted(e, key=repr), sorted(a, key=repr)
        assert a == e, f"\nSQL: {sql}\nminisql: {actual}\nsqlite : {expected}"
        self.ok += 1


T1_COLS = ["a", "b", "c", "id"]


def test_random_scalar_expressions() -> None:
    rng = random.Random(SEED)
    gen = Gen(rng, [])
    runner = Runner()
    for _ in range(600):
        runner.check(f"SELECT {gen.expr(4)}, {gen.expr(3)}", ordered=True)
    assert runner.errors < runner.ok / 20


def test_random_single_table_queries() -> None:
    rng = random.Random(SEED + 1)
    gen = Gen(rng, T1_COLS)
    runner = Runner()
    for _ in range(500):
        n = rng.choice([1, 2, 3])
        items = ", ".join(gen.expr(3) for _ in range(n))
        distinct = rng.random() < 0.15
        sql = f"SELECT {'DISTINCT ' if distinct else ''}{items} FROM t1"
        if rng.random() < 0.7:
            sql += f" WHERE {gen.expr(3)}"
        ordered = False
        if rng.random() < 0.7:
            terms = [f"{gen.order_term(2)} {rng.choice(['', 'ASC', 'DESC'])}"
                     for _ in range(rng.choice([1, 2]))]
            if not distinct:
                terms.append("id")
                ordered = True
            sql += " ORDER BY " + ", ".join(terms)
            if rng.random() < 0.5:
                sql += f" LIMIT {rng.randint(0, 6)}"
                if rng.random() < 0.5:
                    sql += f" OFFSET {rng.randint(0, 4)}"
        runner.check(sql, ordered)
    assert runner.errors < runner.ok / 20


def test_random_aggregate_queries() -> None:
    rng = random.Random(SEED + 2)
    gen = Gen(rng, T1_COLS)
    runner = Runner()
    for _ in range(400):
        aggs = ", ".join(gen.aggregate(2) for _ in range(rng.choice([1, 2, 3])))
        where = f" WHERE {gen.expr(3)}" if rng.random() < 0.5 else ""
        if rng.random() < 0.6:
            key = gen.expr(2)
            sql = f"SELECT {key} AS grp, {aggs} FROM t1{where} GROUP BY {key}"
            if rng.random() < 0.5:
                op = rng.choice([">", "<", "=", "<>"])
                sql += f" HAVING {gen.aggregate(2)} {op} {gen.leaf()}"
            sql += " ORDER BY grp"
            if rng.random() < 0.3:
                sql += f", {gen.aggregate(2)} DESC"
            runner.check(sql, ordered=True)
        else:
            runner.check(f"SELECT {aggs} FROM t1{where}", ordered=True)
    assert runner.errors < runner.ok / 20


def test_random_join_queries() -> None:
    rng = random.Random(SEED + 3)
    cols = ["x.a", "x.b", "x.c", "x.id", "y.k", "y.name", "y.w", "y.id"]
    gen = Gen(rng, cols)
    runner = Runner()
    for _ in range(300):
        kind = rng.choice(["JOIN", "LEFT JOIN", "INNER JOIN", "LEFT OUTER JOIN"])
        on = gen.expr(3)
        items = ", ".join(gen.expr(2) for _ in range(rng.choice([1, 2])))
        sql = f"SELECT x.id, y.id, {items} FROM t1 x {kind} t2 y ON {on}"
        if rng.random() < 0.5:
            sql += f" WHERE {gen.expr(3)}"
        if rng.random() < 0.3:
            agg_cols = ["x.a", "x.b", "y.k", "y.w", "x.c"]
            g = Gen(rng, agg_cols)
            sql = (f"SELECT x.id, COUNT(*), {g.aggregate(2)}, {g.aggregate(2)}"
                   f" FROM t1 x {kind} t2 y ON {on} GROUP BY x.id ORDER BY x.id")
        else:
            sql += " ORDER BY x.id, y.id"
        runner.check(sql, ordered=True)
    assert runner.errors < runner.ok / 20


def test_random_self_joins_and_star() -> None:
    rng = random.Random(SEED + 4)
    gen = Gen(rng, ["p.a", "p.b", "p.c", "q.a", "q.b", "q.c", "p.id", "q.id"])
    runner = Runner()
    for _ in range(150):
        kind = rng.choice(["JOIN", "LEFT JOIN"])
        star = rng.choice(["*", "p.*", "q.*", "p.*, q.id"])
        sql = (f"SELECT {star} FROM t1 p {kind} t1 q ON {gen.expr(3)}"
               f" WHERE {gen.expr(2)} ORDER BY p.id, q.id")
        runner.check(sql, ordered=True)
    assert runner.errors < runner.ok / 20


def test_random_updates_and_deletes() -> None:
    rng = random.Random(SEED + 5)
    gen = Gen(rng, ["a", "b", "c", "id"])
    runner = Runner()
    next_id = 100
    for i in range(200):
        r = rng.random()
        if r < 0.6:
            cols = rng.sample(["a", "b", "c"], rng.choice([1, 2, 3]))
            sets = ", ".join(f"{col} = {gen.expr(3)}" for col in cols)
            where = f" WHERE {gen.expr(3)}" if rng.random() < 0.8 else ""
            runner.check(f"UPDATE t1 SET {sets}{where}", ordered=True)
        elif r < 0.85:
            runner.check(f"DELETE FROM t1 WHERE {gen.expr(3)}", ordered=True)
        else:
            rows = [(next_id + j, *row[1:]) for j, row in enumerate(rng.sample(T1_ROWS, 4))]
            next_id += 10
            runner.check(_insert("t1", rows), ordered=True)
        runner.check("SELECT id, a, typeof(a), b, typeof(b), c, typeof(c) FROM t1 ORDER BY id",
                     ordered=True)
        if i % 10 == 0:
            runner.check("SELECT COUNT(*), SUM(a), AVG(b), MIN(c), MAX(c) FROM t1", ordered=True)
    assert runner.errors < runner.ok / 20


@pytest.mark.parametrize("seed_offset", range(3))
def test_random_precedence_without_parentheses(seed_offset: int) -> None:
    """Flat operator chains rely purely on precedence and associativity."""
    rng = random.Random(SEED + 10 + seed_offset)
    runner = Runner()
    ops = ["+", "-", "*", "/", "%", "||", "<", "<=", ">", ">=", "=", "==", "!=", "<>", "AND", "OR",
           "IS", "IS NOT", "LIKE", "NOT LIKE"]
    for _ in range(300):
        parts = [str(rng.choice(INT_LITERALS + REAL_LITERALS + STRING_LITERALS + ["NULL"]))]
        for _ in range(rng.randint(1, 5)):
            parts.append(rng.choice(ops))
            prefix = rng.choice(["", "", "", "- ", "NOT "])
            parts.append(prefix + str(rng.choice(INT_LITERALS + REAL_LITERALS + STRING_LITERALS)))
        runner.check("SELECT " + " ".join(parts), ordered=True)
    assert runner.errors < runner.ok / 4
