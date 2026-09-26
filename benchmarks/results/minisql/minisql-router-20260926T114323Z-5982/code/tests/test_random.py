"""Randomized differential tests: random data, expressions and queries vs sqlite3.

All generators use fixed seeds so failures are reproducible; each failing query is reported
verbatim in the assertion message.
"""

from __future__ import annotations

import random
from collections.abc import Callable

import pytest
from conftest import Differential

INT_POOL = [None, -100, -3, -1, 0, 1, 2, 3, 5, 7, 10, 42]
REAL_POOL = [None, -2.5, -1.0, -0.0, 0.0, 0.1, 0.5, 1.0, 1.5, 2.0, 3.25, 1e10, 1e-3]
TEXT_POOL = [None, "a", "B", "abc", "Abc", "1", "2.5", " 3", "", "10", "a%", "x_y", "-1", "é", "zz"]
LIKE_PATTERNS = ["'a%'", "'%b%'", "'_'", "'%'", "'1%'", "'A_c'", "'%é'", "''", "'x\\_y'"]

TABLES = {
    "t1": [("a", "INTEGER"), ("b", "REAL"), ("c", "TEXT"), ("d", "INTEGER")],
    "t2": [("a", "INTEGER"), ("e", "TEXT"), ("f", "REAL")],
}
POOLS = {"INTEGER": INT_POOL, "REAL": REAL_POOL, "TEXT": TEXT_POOL}


def sql_literal(v: object) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    if isinstance(v, float):
        return repr(v)
    return str(v)


def build_pair(rng: random.Random, sizes: dict[str, int]) -> Differential:
    d = Differential()
    for name, cols in TABLES.items():
        d.run(f"CREATE TABLE {name} (" + ", ".join(f"{c} {t}" for c, t in cols) + ")")
        rows = []
        for _ in range(sizes[name]):
            rows.append("(" + ", ".join(sql_literal(rng.choice(POOLS[t])) for _, t in cols) + ")")
        if rows:
            d.run(f"INSERT INTO {name} VALUES " + ", ".join(rows))
    return d


class ExprGen:
    """Generates fully parenthesized random expressions over the given column refs."""

    def __init__(self, rng: random.Random, columns: list[str]) -> None:
        self.rng = rng
        self.columns = columns

    def literal(self) -> str:
        pool = self.rng.choice([INT_POOL, REAL_POOL, TEXT_POOL])
        return sql_literal(self.rng.choice(pool))

    def leaf(self) -> str:
        if self.columns and self.rng.random() < 0.6:
            return self.rng.choice(self.columns)
        return self.literal()

    def expr(self, depth: int) -> str:
        rng = self.rng
        if depth <= 0 or rng.random() < 0.2:
            return self.leaf()
        sub = self.expr
        d = depth - 1
        kind = rng.randrange(17)
        if kind == 0:
            op = rng.choice(["+", "-", "*", "/", "%"])
            return f"({sub(d)} {op} {sub(d)})"
        if kind == 1:
            return f"({sub(d)} || {sub(d)})"
        if kind == 2:
            op = rng.choice(["=", "==", "!=", "<>", "<", "<=", ">", ">="])
            return f"({sub(d)} {op} {sub(d)})"
        if kind == 3:
            op = rng.choice(["AND", "OR"])
            return f"({sub(d)} {op} {sub(d)})"
        if kind == 4:
            return f"(NOT {sub(d)})"
        if kind == 5:
            return f"({rng.choice(['-', '+'])} {sub(d)})"
        if kind == 6:
            op = rng.choice(["IS NULL", "IS NOT NULL", "NOTNULL", "ISNULL"])
            return f"({sub(d)} {op})"
        if kind == 7:
            op = rng.choice(["IS", "IS NOT"])
            return f"({sub(d)} {op} {sub(d)})"
        if kind == 8:
            items = ", ".join(sub(d - 1) for _ in range(rng.randint(1, 4)))
            neg = rng.choice(["", "NOT "])
            return f"({sub(d)} {neg}IN ({items}))"
        if kind == 9:
            neg = rng.choice(["", "NOT "])
            return f"({sub(d)} {neg}BETWEEN {sub(d)} AND {sub(d)})"
        if kind == 10:
            neg = rng.choice(["", "NOT "])
            pat = rng.choice(LIKE_PATTERNS) if rng.random() < 0.7 else sub(d)
            esc = " ESCAPE '\\'" if "\\" in pat else ""
            return f"({sub(d)} {neg}LIKE {pat}{esc})"
        if kind == 11:
            whens = " ".join(f"WHEN {sub(d)} THEN {sub(d)}" for _ in range(rng.randint(1, 3)))
            base = sub(d) + " " if rng.random() < 0.5 else ""
            els = f" ELSE {sub(d)}" if rng.random() < 0.6 else ""
            return f"(CASE {base}{whens}{els} END)"
        if kind == 12:
            t = rng.choice(["INTEGER", "REAL", "TEXT", "NUMERIC"])
            return f"CAST({sub(d)} AS {t})"
        if kind == 13:
            fn = rng.choice(["abs", "length", "typeof", "upper", "lower"])
            return f"{fn}({sub(d)})"
        if kind == 14:
            fn = rng.choice(["coalesce", "ifnull", "nullif", "min", "max"])
            n = 2 if fn in ("ifnull", "nullif") else rng.randint(2, 3)
            return f"{fn}(" + ", ".join(sub(d) for _ in range(n)) + ")"
        if kind == 15:
            op = rng.choice(["&", "|", "<<", ">>"])
            return f"({sub(d)} {op} {sub(d)})"
        return f"(~ {sub(d)})"


def assert_same(d: Differential, sql: str, **kwargs: object) -> None:
    try:
        expected_error = None
        d.expected(sql)
    except Exception as exc:  # sqlite rejected it: minisql must reject too
        expected_error = exc
    if expected_error is not None:
        from minisql import SQLError

        with pytest.raises(SQLError):
            d.mini.execute(sql)
        return
    d.check(sql, **kwargs)  # type: ignore[arg-type]


def _run_queries(seed: int, count: int, make_query: Callable[[random.Random], str], **kw) -> None:
    rng = random.Random(seed)
    d = build_pair(rng, {"t1": 24, "t2": 12})
    try:
        for _ in range(count):
            assert_same(d, make_query(rng), **kw)
    finally:
        d.close()


T1_COLS = ["a", "b", "c", "d", "t1.a", "t1.c"]
JOIN_COLS = ["t1.a", "t1.b", "t1.c", "t1.d", "t2.a", "t2.e", "t2.f", "b", "c", "e", "f"]


@pytest.mark.parametrize("seed", range(10))
def test_random_projection_and_filter(seed: int) -> None:
    def make(rng: random.Random) -> str:
        g = ExprGen(rng, T1_COLS)
        cols = ", ".join(g.expr(3) for _ in range(rng.randint(1, 3)))
        where = f" WHERE {g.expr(3)}" if rng.random() < 0.7 else ""
        return f"SELECT {cols} FROM t1{where}"

    _run_queries(1000 + seed, 300, make)


@pytest.mark.parametrize("seed", range(4))
def test_random_constant_expressions(seed: int) -> None:
    def make(rng: random.Random) -> str:
        g = ExprGen(rng, [])
        return "SELECT " + ", ".join(g.expr(4) for _ in range(3))

    _run_queries(2000 + seed, 400, make)


@pytest.mark.parametrize("seed", range(4))
def test_random_joins(seed: int) -> None:
    def make(rng: random.Random) -> str:
        g = ExprGen(rng, JOIN_COLS)
        kind = rng.choice(["JOIN", "LEFT JOIN", "LEFT OUTER JOIN", "INNER JOIN"])
        on = rng.choice(
            ["t1.a = t2.a", "t1.c = t2.e", "t1.d > t2.a", "t1.b = t2.f", g.expr(2)]
        )
        cols = ", ".join(g.expr(2) for _ in range(rng.randint(1, 3)))
        where = f" WHERE {g.expr(2)}" if rng.random() < 0.5 else ""
        if rng.random() < 0.3:
            where = rng.choice([" WHERE t2.a IS NULL", " WHERE t2.e IS NOT NULL"])
        return f"SELECT {cols} FROM t1 {kind} t2 ON {on}{where}"

    _run_queries(3000 + seed, 150, make)


@pytest.mark.parametrize("seed", range(6))
def test_random_aggregates(seed: int) -> None:
    def make(rng: random.Random) -> str:
        g = ExprGen(rng, T1_COLS)
        arg = g.expr(2)
        aggs = [
            "COUNT(*)",
            f"COUNT({arg})",
            f"SUM({arg})",
            f"AVG({arg})",
            f"MIN({arg})",
            f"MAX({arg})",
            f"TOTAL({arg})",
            f"COUNT(DISTINCT {arg})",
            f"SUM(DISTINCT {arg})",
        ]
        chosen = rng.sample(aggs, rng.randint(1, 4))
        where = f" WHERE {g.expr(2)}" if rng.random() < 0.5 else ""
        if rng.random() < 0.7:
            key = rng.choice(["a", "c", "d", "b", "a % 3", "c IS NULL", "length(c)", "d > 2"])
            having = ""
            if rng.random() < 0.3:
                having = f" HAVING {rng.choice(chosen)} > {rng.randint(0, 3)}"
            return f"SELECT {key}, {', '.join(chosen)} FROM t1{where} GROUP BY {key}{having}"
        return f"SELECT {', '.join(chosen)} FROM t1{where}"

    _run_queries(4000 + seed, 200, make)


@pytest.mark.parametrize("seed", range(4))
def test_random_order_by_limit(seed: int) -> None:
    def make(rng: random.Random) -> str:
        pool = ["a", "b", "c", "d", "a + d", "b * 2", "c || 'x'", "-a", "a % 4", "lower(c)"]
        cols = rng.sample(pool, rng.randint(1, 3))
        terms = []
        for i in rng.sample(range(len(cols)), len(cols)):
            ref = cols[i] if rng.random() < 0.5 else str(i + 1)
            direction = rng.choice(["", " ASC", " DESC"])
            nulls = rng.choice(["", "", "", " NULLS FIRST", " NULLS LAST"])
            terms.append(ref + direction + nulls)
        distinct = "DISTINCT " if rng.random() < 0.3 else ""
        where = f" WHERE {ExprGen(rng, T1_COLS).expr(2)}" if rng.random() < 0.4 else ""
        limit = ""
        if rng.random() < 0.6:
            limit = f" LIMIT {rng.randint(-1, 10)}"
            if rng.random() < 0.5:
                limit += f" OFFSET {rng.randint(0, 6)}"
        order = ", ".join(terms)
        return f"SELECT {distinct}{', '.join(cols)} FROM t1{where} ORDER BY {order}{limit}"

    _run_queries(5000 + seed, 200, make, ordered=True, ties=True)


@pytest.mark.parametrize("seed", range(4))
def test_random_operator_precedence(seed: int) -> None:
    """Unparenthesized operator chains exercise precedence and associativity."""
    ops = [
        "+", "-", "*", "/", "%", "||", "=", "==", "!=", "<>", "<", "<=", ">", ">=",
        "AND", "OR", "&", "|", "<<", ">>", "IS", "IS NOT",
    ]  # fmt: skip

    def make(rng: random.Random) -> str:
        g = ExprGen(rng, T1_COLS)

        def atom() -> str:
            r = rng.random()
            if r < 0.1:
                return f"{g.leaf()} BETWEEN {g.leaf()} AND {g.leaf()}"
            if r < 0.15:
                return f"{g.leaf()} LIKE {rng.choice(LIKE_PATTERNS[:-1])}"
            if r < 0.2:
                return f"{g.leaf()} IN ({g.leaf()}, {g.leaf()})"
            if r < 0.25:
                return f"- {g.leaf()}"
            if r < 0.3:
                return f"NOT {g.leaf()}"
            return g.leaf()

        parts = [atom()]
        for _ in range(rng.randint(1, 5)):
            op = rng.choice(ops)
            nxt = atom()
            if nxt.startswith("NOT ") and op not in ("AND", "OR"):
                nxt = f"({nxt})"
            parts.append(op)
            parts.append(nxt)
        return f"SELECT {' '.join(parts)} FROM t1"

    _run_queries(6000 + seed, 400, make)


@pytest.mark.parametrize("seed", range(3))
def test_random_dml(seed: int) -> None:
    rng = random.Random(7000 + seed)
    d = build_pair(rng, {"t1": 15, "t2": 8})
    try:
        for _ in range(80):
            g = ExprGen(rng, ["a", "b", "c", "d"])
            r = rng.random()
            if r < 0.35:
                consts = ExprGen(rng, [])  # VALUES may not reference columns
                vals = ", ".join(
                    "(" + ", ".join(consts.expr(1) for _ in range(4)) + ")"
                    for _ in range(rng.randint(1, 3))
                )
                sql = f"INSERT INTO t1 VALUES {vals}"
            elif r < 0.7:
                col = rng.choice(["a", "b", "c", "d"])
                col2 = rng.choice(["a", "b", "c", "d"])
                sets = f"{col} = {g.expr(2)}"
                if col2 != col:
                    sets += f", {col2} = {g.expr(2)}"
                where = f" WHERE {g.expr(2)}" if rng.random() < 0.7 else ""
                sql = f"UPDATE t1 SET {sets}{where}"
            else:
                sql = f"DELETE FROM t1 WHERE {g.expr(2)}"
            try:
                d.lite.execute(sql)
                lite_ok = True
            except Exception:
                lite_ok = False
            if lite_ok:
                assert d.mini.execute(sql) == [], sql
            else:
                from minisql import SQLError

                with pytest.raises(SQLError):
                    d.mini.execute(sql)
            d.check("SELECT a, b, c, d, typeof(a), typeof(b), typeof(c), typeof(d) FROM t1")
    finally:
        d.close()
