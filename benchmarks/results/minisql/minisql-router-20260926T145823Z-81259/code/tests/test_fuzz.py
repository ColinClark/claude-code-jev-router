"""Seeded random differential testing against sqlite3."""

import random

import pytest

from minisql import SQLError

from .conftest import assert_same

INT_COLS = ["n.a", "n.b"]
REAL_COLS = ["n.x"]
TEXT_COLS = ["n.s"]
LITERALS = ["0", "1", "2", "-3", "7", "0.5", "2.0", "-1.25", "NULL", "'a'", "'10'", "'x_%'", "''"]
BINARY = ["+", "-", "*", "/", "%", "||", "=", "!=", "<", "<=", ">", ">=", "AND", "OR", "IS"]


def gen_expr(rng: random.Random, depth: int) -> str:
    if depth <= 0 or rng.random() < 0.25:
        return rng.choice(INT_COLS + REAL_COLS + TEXT_COLS + LITERALS)
    kind = rng.randrange(10)
    sub = lambda: gen_expr(rng, depth - 1)  # noqa: E731
    if kind < 4:
        return f"({sub()} {rng.choice(BINARY)} {sub()})"
    if kind == 4:
        return f"(NOT {sub()})" if rng.random() < 0.5 else f"(-{sub()})"
    if kind == 5:
        return f"({sub()} IS {'NOT ' if rng.random() < 0.5 else ''}NULL)"
    if kind == 6:
        items = ", ".join(sub() for _ in range(rng.randrange(1, 4)))
        return f"({sub()} {'NOT ' if rng.random() < 0.3 else ''}IN ({items}))"
    if kind == 7:
        return f"({sub()} {'NOT ' if rng.random() < 0.3 else ''}BETWEEN {sub()} AND {sub()})"
    if kind == 8:
        pattern = rng.choice(["'%'", "'a%'", "'%0'", "'_'", "'1%'", "'%A%'", "n.s", "'-%'"])
        return f"({sub()} {'NOT ' if rng.random() < 0.3 else ''}LIKE {pattern})"
    if rng.random() < 0.5:
        return f"{rng.choice(['abs', 'typeof', 'length', 'upper'])}({sub()})"
    return f"{rng.choice(['coalesce', 'ifnull', 'nullif', 'min', 'max'])}({sub()}, {sub()})"


def make_cases(seed: int, count: int) -> list[str]:
    rng = random.Random(seed)
    cases = []
    while len(cases) < count:
        e1, e2 = gen_expr(rng, 3), gen_expr(rng, 3)
        choice = rng.randrange(5)
        if choice == 0:
            cases.append(f"SELECT {e1}, {e2} FROM nums n")
        elif choice == 1:
            cases.append(f"SELECT n.a, n.b, n.x, n.s FROM nums n WHERE {e1}")
        elif choice == 2:
            cases.append(
                f"SELECT COUNT({e1}), SUM({e1}), AVG({e1}), MIN({e1}), MAX({e1}), "
                f"COUNT(DISTINCT {e1}) FROM nums n"
            )
        elif choice == 3:
            cases.append(
                f"SELECT {e2} AS k, COUNT(*), SUM({e1}), MAX({e1}) FROM nums n "
                f"GROUP BY k ORDER BY k"
            )
        else:
            cases.append(
                f"SELECT {e1} AS k, n.a, n.b, n.x, n.s FROM nums n "
                f"ORDER BY k {rng.choice(['ASC', 'DESC'])}, n.a, n.b, n.x, n.s"
            )
    return cases


CASES = make_cases(20260926, 600)


@pytest.mark.parametrize("sql", CASES)
def test_fuzz_matches_sqlite(db, lite, sql):
    try:
        lite.execute(sql).fetchall()
    except Exception as exc:  # e.g. integer overflow in SUM
        with pytest.raises(SQLError):
            db.execute(sql)
        pytest.skip(f"sqlite rejects: {exc}")
    assert_same(db, lite, sql)


JOIN_CONDS = [
    "e.dept = d.name",
    "e.age > d.floor * 10",
    "e.boss = d.floor",
    "d.budget > e.salary",
    "e.dept = d.name AND d.floor > 1",
    "e.dept LIKE d.name || '%' OR d.name IS NULL",
    "1",
]
PREDICATES = [
    "e.age > 30",
    "e.salary IS NULL",
    "d.name IS NULL",
    "e.dept IN ('eng', 'hr') OR d.floor BETWEEN 2 AND 4",
    "NOT (e.age < 40 AND d.budget > 100)",
    "e.name LIKE '%a%'",
    "e.boss IS NOT NULL AND e.boss <> 1",
    "d.floor % 2 = 1",
]
GROUP_KEYS = ["e.dept", "d.floor", "e.age / 10", "e.boss", "d.name || e.dept", "e.salary > 70000"]
AGGS = [
    "COUNT(*)",
    "COUNT(d.name)",
    "SUM(e.salary)",
    "AVG(e.age)",
    "MIN(d.budget)",
    "MAX(e.name)",
    "COUNT(DISTINCT d.floor)",
    "SUM(e.age * d.floor)",
    "TOTAL(d.budget)",
]
HAVINGS = [
    "COUNT(*) > 1",
    "SUM(e.salary) > 100000",
    "MAX(e.age) IS NOT NULL",
    "AVG(e.age) < 40 OR COUNT(*) = 1",
]
ROW_EXPRS = ["e.name", "e.salary / 1000", "d.floor", "e.age + d.floor", "d.name || '-' || e.dept"]


def make_query_shapes(seed: int, count: int) -> list[str]:
    rng = random.Random(seed)
    cases = []
    for _ in range(count):
        join = f"{rng.choice(['JOIN', 'LEFT JOIN', 'INNER JOIN', 'LEFT OUTER JOIN'])} dept d"
        from_clause = f"FROM emp e {join} ON {rng.choice(JOIN_CONDS)}"
        where = f" WHERE {rng.choice(PREDICATES)}" if rng.random() < 0.6 else ""
        limit = ""
        if rng.random() < 0.4:
            limit = f" LIMIT {rng.randrange(0, 8)}"
            if rng.random() < 0.5:
                limit += f" OFFSET {rng.randrange(0, 5)}"
        direction = rng.choice(["", " ASC", " DESC"])
        if rng.random() < 0.5:
            expr = rng.choice(ROW_EXPRS)
            if rng.random() < 0.2:
                cases.append(f"SELECT DISTINCT {expr} {from_clause}{where}")
                continue
            cases.append(
                f"SELECT e.id, {expr} AS v {from_clause}{where} "
                f"ORDER BY {rng.choice(['v', expr, 'e.age'])}{direction}, e.id, d.floor{limit}"
            )
        else:
            key = rng.choice(GROUP_KEYS)
            aggs = rng.sample(AGGS, 3)
            having = f" HAVING {rng.choice(HAVINGS)}" if rng.random() < 0.4 else ""
            order = rng.choice(["g", aggs[0], "2", "COUNT(*)"])
            cases.append(
                f"SELECT {key} AS g, {', '.join(aggs)} {from_clause}{where} GROUP BY g{having} "
                f"ORDER BY {order}{direction}, g{limit}"
            )
    return cases


@pytest.mark.parametrize("sql", make_query_shapes(7, 300))
def test_query_shapes_match_sqlite(db, lite, sql):
    assert_same(db, lite, sql)
