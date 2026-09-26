"""Hidden acceptance tests for the minisql benchmark, written only from benchmarks/minisql/prompt.md.

The prompt defines correct results as "what SQLite returns", so every query here runs on both minisql and
Python's sqlite3 on identical data and the results are compared: values, Python types (3 is not 3.0) and,
when ORDER BY is present, row order. Neither benchmark mode sees these tests.
"""

import ast
import random
import sqlite3
from collections import Counter
from pathlib import Path

import pytest
from minisql import Database, SQLError

SCHEMA = [
    "CREATE TABLE dept (id INTEGER, name TEXT, budget INTEGER)",
    "CREATE TABLE emp (id INTEGER, name TEXT, dept_id INTEGER, salary REAL, bonus INTEGER, manager_id INTEGER)",
    "CREATE TABLE proj (id INTEGER, emp_id INTEGER, title TEXT, hours INTEGER)",
]
DATA = [
    "INSERT INTO dept VALUES (1, 'Engineering', 500000), (2, 'Sales', 200000), (3, 'Support', NULL), "
    "(4, 'Empty', 1000)",
    "INSERT INTO emp VALUES "
    "(1, 'Alice', 1, 120000.0, 10, NULL), (2, 'bob', 1, 95000.5, NULL, 1), (3, 'Carol', 2, 70000.0, 7, 1), "
    "(4, 'dave', 2, 70000.0, -3, 3), (5, 'Eve', NULL, 50000.0, 0, 1), (6, 'Frank', 3, NULL, 5, 3), "
    "(7, 'grace', 1, 150000.25, 12, 1), (8, 'Heidi', 3, 45000.0, NULL, 6), (9, 'ivan', 2, 82000.0, 9, 3), "
    "(10, 'Judy', 0, 30000.0, 2, NULL)",
    "INSERT INTO proj VALUES (1, 1, 'Compiler', 120), (2, 1, 'Parser', 40), (3, 2, 'Parser', 60), "
    "(4, 3, 'Deals', NULL), (5, 7, 'Compiler', 200), (6, 99, 'Orphan', 10), (7, 9, 'Deals', 35)",
]


def normalize(value):
    if isinstance(value, float):
        return ("float", round(value, 6))
    return (type(value).__name__, value)


def rows(result):
    return [tuple(normalize(v) for v in row) for row in result]


def fresh():
    mine, ref = Database(), sqlite3.connect(":memory:")
    for stmt in SCHEMA + DATA:
        mine.execute(stmt)
        ref.execute(stmt)
    return mine, ref


def check(mine, ref, sql):
    got = rows(mine.execute(sql))
    want = rows(ref.execute(sql).fetchall())
    if "ORDER BY" in sql.upper():
        assert got == want, f"{sql}\n got: {got}\nwant: {want}"
    else:
        assert Counter(got) == Counter(want), f"{sql}\n got: {sorted(got, key=repr)}\nwant: {sorted(want, key=repr)}"


QUERIES = [
    # projection, arithmetic and types
    "SELECT id, name FROM emp ORDER BY id",
    "SELECT * FROM dept ORDER BY id",
    "SELECT id, bonus / 3, bonus % 4, -bonus FROM emp ORDER BY id",
    "SELECT id, salary / 1000, salary * 2 FROM emp ORDER BY id",
    "SELECT id, bonus / 0, salary / 0, bonus % 0 FROM emp ORDER BY id",
    "SELECT id, -7 / 2, 7 / 2, -7 % 3, 7.5 % 2 FROM emp WHERE id = 1",
    "SELECT id, 2 + 3 * 4, (2 + 3) * 4, 10 - 2 - 3 FROM emp WHERE id = 1",
    "SELECT id, name || '-' || dept_id, name || NULL FROM emp ORDER BY id",
    "SELECT id, bonus + 1.5 FROM emp ORDER BY id",
    # WHERE and three-valued logic
    "SELECT id FROM emp WHERE bonus > 5 ORDER BY id",
    "SELECT id FROM emp WHERE NOT bonus > 5 ORDER BY id",
    "SELECT id FROM emp WHERE bonus = NULL",
    "SELECT id FROM emp WHERE bonus IS NULL ORDER BY id",
    "SELECT id FROM emp WHERE bonus IS NOT NULL AND salary IS NOT NULL ORDER BY id",
    "SELECT id FROM emp WHERE bonus > 5 OR salary > 100000 ORDER BY id",
    "SELECT id FROM emp WHERE bonus > 5 AND NOT salary > 100000 ORDER BY id",
    "SELECT id FROM emp WHERE dept_id IN (1, 3) ORDER BY id",
    "SELECT id FROM emp WHERE dept_id NOT IN (1, 3) ORDER BY id",
    "SELECT id FROM emp WHERE dept_id IN (1, NULL) ORDER BY id",
    "SELECT id FROM emp WHERE dept_id NOT IN (1, NULL) ORDER BY id",
    "SELECT id FROM emp WHERE salary BETWEEN 50000 AND 95000.5 ORDER BY id",
    "SELECT id FROM emp WHERE salary NOT BETWEEN 50000 AND 95000.5 ORDER BY id",
    "SELECT id FROM emp WHERE name LIKE 'a%' ORDER BY id",
    "SELECT id FROM emp WHERE name LIKE '%A%' ORDER BY id",
    "SELECT id FROM emp WHERE name LIKE '_o%' ORDER BY id",
    "SELECT id FROM emp WHERE name NOT LIKE '%e%' ORDER BY id",
    "SELECT id FROM emp WHERE id == 3 OR id <> 3 AND id != 4 ORDER BY id",
    "select Id, NAME from EMP where Bonus >= 7 order by ID desc",
    # ORDER BY, LIMIT, DISTINCT
    "SELECT id, bonus FROM emp ORDER BY bonus, id",
    "SELECT id, bonus FROM emp ORDER BY bonus DESC, id",
    "SELECT id, salary FROM emp ORDER BY salary DESC, id DESC",
    "SELECT name AS n, bonus * 2 AS b2 FROM emp ORDER BY b2, n",
    "SELECT id FROM emp ORDER BY salary - bonus, id",
    "SELECT id FROM emp ORDER BY id LIMIT 3",
    "SELECT id FROM emp ORDER BY id LIMIT 3 OFFSET 4",
    "SELECT id FROM emp ORDER BY id DESC LIMIT 100 OFFSET 8",
    "SELECT DISTINCT dept_id FROM emp ORDER BY dept_id",
    "SELECT DISTINCT bonus IS NULL, dept_id FROM emp",
    # aggregates
    "SELECT COUNT(*), COUNT(bonus), COUNT(DISTINCT dept_id), SUM(bonus), AVG(bonus), MIN(bonus), MAX(bonus) FROM emp",
    "SELECT SUM(salary), AVG(salary), MIN(name), MAX(name) FROM emp",
    "SELECT COUNT(*), SUM(bonus), AVG(bonus), MIN(bonus), MAX(bonus) FROM emp WHERE id > 100",
    "SELECT dept_id, COUNT(*), SUM(bonus), AVG(salary) FROM emp GROUP BY dept_id ORDER BY dept_id",
    "SELECT dept_id, COUNT(*) FROM emp GROUP BY dept_id HAVING COUNT(*) > 1 ORDER BY dept_id",
    "SELECT dept_id, MAX(salary) - MIN(salary) AS spread FROM emp GROUP BY dept_id ORDER BY spread DESC, dept_id",
    "SELECT dept_id, SUM(bonus * 2) FROM emp WHERE salary > 40000 GROUP BY dept_id ORDER BY SUM(bonus * 2), dept_id",
    "SELECT bonus IS NULL, COUNT(*) FROM emp GROUP BY bonus IS NULL ORDER BY 1",
    "SELECT COUNT(DISTINCT title), COUNT(title) FROM proj",
    # joins
    "SELECT e.name, d.name FROM emp e JOIN dept d ON e.dept_id = d.id ORDER BY e.id",
    "SELECT e.name, d.name FROM emp AS e INNER JOIN dept AS d ON e.dept_id = d.id WHERE d.budget > 100000 "
    "ORDER BY e.name",
    "SELECT e.id, d.name FROM emp e LEFT JOIN dept d ON e.dept_id = d.id ORDER BY e.id",
    "SELECT d.name, COUNT(e.id) FROM dept d LEFT JOIN emp e ON e.dept_id = d.id GROUP BY d.name ORDER BY d.name",
    "SELECT d.name, SUM(e.bonus), AVG(e.salary) FROM dept d LEFT OUTER JOIN emp e ON e.dept_id = d.id "
    "GROUP BY d.id ORDER BY d.id",
    "SELECT e.name, m.name FROM emp e LEFT JOIN emp m ON e.manager_id = m.id ORDER BY e.id",
    "SELECT e.name, p.title, d.name FROM emp e JOIN proj p ON p.emp_id = e.id JOIN dept d ON d.id = e.dept_id "
    "ORDER BY p.id",
    "SELECT p.title, SUM(p.hours), COUNT(*) FROM proj p LEFT JOIN emp e ON p.emp_id = e.id "
    "GROUP BY p.title HAVING SUM(p.hours) > 50 ORDER BY p.title",
    "SELECT e.id, p.id FROM emp e LEFT JOIN proj p ON p.emp_id = e.id AND p.hours > 50 ORDER BY e.id, p.id",
    "SELECT d.*, e.name FROM dept d JOIN emp e ON e.dept_id = d.id WHERE e.bonus > 8 ORDER BY e.id",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_matches_sqlite(sql):
    mine, ref = fresh()
    check(mine, ref, sql)


MUTATIONS = [
    ("UPDATE emp SET bonus = bonus + 1 WHERE dept_id = 1", "SELECT id, bonus FROM emp ORDER BY id"),
    ("UPDATE emp SET salary = salary * 1.5, bonus = 0 WHERE bonus IS NULL", "SELECT * FROM emp ORDER BY id"),
    ("UPDATE emp SET name = name || '!'", "SELECT name FROM emp ORDER BY id"),
    ("DELETE FROM emp WHERE salary < 60000", "SELECT id FROM emp ORDER BY id"),
    ("DELETE FROM proj", "SELECT COUNT(*), SUM(hours) FROM proj"),
    ("INSERT INTO emp (id, name) VALUES (11, 'Zed')", "SELECT * FROM emp WHERE id > 9 ORDER BY id"),
]


@pytest.mark.parametrize(("statement", "query"), MUTATIONS)
def test_mutations_match_sqlite(statement, query):
    mine, ref = fresh()
    assert mine.execute(statement) == []
    ref.execute(statement)
    check(mine, ref, query)


NUMERIC = ["id", "dept_id", "salary", "bonus", "manager_id"]
LITERALS = {
    "id": [0, 3, 7, 11],
    "dept_id": [0, 1, 2, 3],
    "salary": [45000, 70000.0, 95000.5, 200000],
    "bonus": [-3, 0, 5, 9],
    "manager_id": [1, 3, 6],
}
PATTERNS = ["%a%", "_r%", "%e", "A%", "%", "____"]


def predicate(rng, depth=0):
    if depth < 2 and rng.random() < 0.4:
        op = rng.choice(["AND", "OR"])
        return f"({predicate(rng, depth + 1)} {op} {predicate(rng, depth + 1)})"
    if depth < 2 and rng.random() < 0.1:
        return f"NOT ({predicate(rng, depth + 1)})"
    kind = rng.random()
    col = rng.choice(NUMERIC)
    if kind < 0.45:
        return f"{col} {rng.choice(['=', '!=', '<', '<=', '>', '>='])} {rng.choice(LITERALS[col])}"
    if kind < 0.6:
        return f"{col} IS {rng.choice(['', 'NOT '])}NULL"
    if kind < 0.75:
        items = rng.sample(LITERALS[col], 2) + (["NULL"] if rng.random() < 0.3 else [])
        return f"{col} {rng.choice(['', 'NOT '])}IN ({', '.join(map(str, items))})"
    if kind < 0.85:
        lo, hi = sorted(rng.sample(LITERALS[col], 2))
        return f"{col} {rng.choice(['', 'NOT '])}BETWEEN {lo} AND {hi}"
    return f"name {rng.choice(['', 'NOT '])}LIKE '{rng.choice(PATTERNS)}'"


EXPRESSIONS = [
    "id",
    "name",
    "salary",
    "bonus",
    "dept_id",
    "bonus / 3",
    "bonus % 4",
    "salary / 1000",
    "-bonus",
    "bonus * 2 + 1",
    "name || '#' || id",
    "bonus / dept_id",
    "salary - bonus",
    "dept_id * 1.5",
]


def random_select(rng):
    exprs = rng.sample(EXPRESSIONS, rng.randint(1, 4))
    sql = f"SELECT {', '.join(exprs)} FROM emp WHERE {predicate(rng)}"
    sql += f" ORDER BY {rng.choice(exprs)}{rng.choice(['', ' DESC'])}, id"
    if rng.random() < 0.3:
        sql += f" LIMIT {rng.randint(1, 5)}" + (f" OFFSET {rng.randint(0, 3)}" if rng.random() < 0.5 else "")
    return sql


def random_aggregate(rng):
    key = rng.choice(["dept_id", "manager_id", "bonus IS NULL", "salary > 60000"])
    aggs = rng.sample(
        [
            "COUNT(*)",
            "COUNT(bonus)",
            "SUM(bonus)",
            "AVG(salary)",
            "MIN(name)",
            "MAX(bonus)",
            "SUM(salary) / COUNT(*)",
            "COUNT(DISTINCT dept_id)",
        ],
        3,
    )
    sql = f"SELECT {key}, {', '.join(aggs)} FROM emp WHERE {predicate(rng)} GROUP BY {key}"
    if rng.random() < 0.3:
        sql += " HAVING COUNT(*) > 1"
    return sql + " ORDER BY 1"


@pytest.mark.parametrize("batch", range(10))
def test_random_queries_match_sqlite(batch):
    rng = random.Random(1000 + batch)
    mine, ref = fresh()
    for _ in range(25):
        sql = random_aggregate(rng) if rng.random() < 0.3 else random_select(rng)
        check(mine, ref, sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM missing",
        "SELECT nope FROM emp",
        "SELECT id FROM emp e JOIN dept d ON e.dept_id = d.id",  # ambiguous column
        "SELEC id FROM emp",
        "SELECT id FROM emp WHERE",
    ],
)
def test_errors_raise_sqlerror(sql):
    mine, _ = fresh()
    with pytest.raises(SQLError):
        mine.execute(sql)


def test_implementation_does_not_use_sqlite():
    import minisql

    package = Path(minisql.__file__).resolve().parent
    sources = list(package.rglob("*.py"))
    assert sources
    # Inspect real imports (comments or docstrings that mention SQLite's C functions are fine).
    offenders = []
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in (
                "__import__",
                "import_module",
            ):
                names = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            offenders += [f"{path.name}: {n}" for n in names if n.split(".")[0] in ("sqlite3", "_sqlite3")]
    assert offenders == []
