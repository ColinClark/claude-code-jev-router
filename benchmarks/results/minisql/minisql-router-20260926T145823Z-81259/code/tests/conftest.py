import sqlite3

import pytest

from minisql import Database

SETUP = [
    "CREATE TABLE emp (id INTEGER, name TEXT, dept TEXT, salary REAL, age INTEGER, boss INTEGER)",
    "CREATE TABLE dept (name TEXT, floor INTEGER, budget REAL)",
    "CREATE TABLE nums (a INTEGER, b INTEGER, x REAL, s TEXT)",
    "CREATE TABLE empty (a INTEGER, b TEXT)",
    """INSERT INTO emp VALUES
        (1, 'Alice', 'eng', 120000.5, 34, NULL),
        (2, 'Bob', 'eng', 95000, 45, 1),
        (3, 'carol', 'sales', 70000.25, 29, 1),
        (4, 'Dave', 'sales', NULL, 51, 3),
        (5, 'Eve', NULL, 50000, NULL, 3),
        (6, 'frank', 'hr', 65000, 38, 1),
        (7, 'Grace', 'eng', 130000, 29, 2),
        (8, 'heidi', 'hr', 65000, 41, 6),
        (9, 'Ivan', 'ops', NULL, NULL, NULL),
        (10, 'Judy_x', 'eng', 88000.75, 23, 2)""",
    """INSERT INTO dept VALUES
        ('eng', 3, 1000000.0), ('sales', 2, 250000.5), ('hr', 1, NULL),
        ('legal', 4, 50000), (NULL, 9, 1)""",
    """INSERT INTO nums VALUES
        (7, 2, 1.5, '10'), (-7, 2, -2.5, 'abc'), (7, -2, 0.0, '3.5'), (-7, -2, 2.0, ''),
        (0, 0, NULL, NULL), (NULL, 3, 3.25, 'A%b'), (5, NULL, -0.5, 'a_b'), (9, 4, 10.0, '1e2'),
        (1, 1, 0.1, 'Hello'), (2, 3, 0.2, 'hello')""",
]


def load(conn_execute):
    for stmt in SETUP:
        conn_execute(stmt)


@pytest.fixture
def db() -> Database:
    database = Database()
    load(database.execute)
    return database


@pytest.fixture
def lite() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    load(conn.execute)
    yield conn
    conn.close()


def typed(rows):
    """Rows with each value tagged by its Python type, so 1 and 1.0 differ."""
    return [tuple((type(v).__name__, v) for v in row) for row in rows]


def assert_same(db: Database, lite: sqlite3.Connection, sql: str, ordered: bool | None = None):
    expected = [tuple(r) for r in lite.execute(sql).fetchall()]
    actual = db.execute(sql)
    assert all(isinstance(r, tuple) for r in actual)
    if ordered is None:
        ordered = "order by" in sql.lower()
    if ordered:
        assert typed(actual) == typed(expected), sql
    else:
        assert sorted(typed(actual), key=_row_key) == sorted(typed(expected), key=_row_key), sql


def _row_key(row):
    # -0.0 == 0.0 but their reprs differ; normalise so sorting is consistent.
    return repr([(t, v + 0.0 if t == "float" else v) for t, v in row])
