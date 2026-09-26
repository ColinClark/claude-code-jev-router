"""Differential-testing helpers: run the same SQL on minisql and sqlite3 and compare."""

from __future__ import annotations

import sqlite3

import pytest

from minisql import Database, SQLError


def sort_key(value):
    """Total order for comparing unordered results; ties between 1 and 1.0 broken by type."""
    if value is None:
        return (0, 0, 0)
    if isinstance(value, (int, float)):
        return (1, value, isinstance(value, float))
    return (2, value, 0)


def row_key(row):
    return tuple(sort_key(value) for value in row)


def typed(rows):
    """Make type differences visible: 1 vs 1.0 vs '1' vs True must not compare equal."""
    return [tuple((type(value).__name__, value) for value in row) for row in rows]


class Pair:
    """A minisql database and a sqlite3 database kept in lock-step."""

    def __init__(self) -> None:
        self.mini = Database()
        self.lite = sqlite3.connect(":memory:")

    def run(self, *statements: str) -> None:
        for sql in statements:
            self.lite.execute(sql)
            assert self.mini.execute(sql) == []

    def query(self, sql: str, *, ordered: bool | None = None):
        if ordered is None:
            ordered = "order by" in sql.lower()
        expected = [tuple(row) for row in self.lite.execute(sql).fetchall()]
        actual = self.mini.execute(sql)
        assert isinstance(actual, list)
        assert all(isinstance(row, tuple) for row in actual)
        if not ordered:
            expected.sort(key=row_key)
            actual = sorted(actual, key=row_key)
        assert typed(actual) == typed(expected), sql
        return actual

    def error(self, sql: str) -> None:
        with pytest.raises(sqlite3.Error):
            self.lite.execute(sql).fetchall()
        with pytest.raises(SQLError):
            self.mini.execute(sql)


@pytest.fixture
def pair() -> Pair:
    return Pair()


SCHEMA = [
    "CREATE TABLE dept (id INTEGER, name TEXT, budget REAL)",
    (
        "CREATE TABLE emp (id INTEGER, name TEXT, dept_id INTEGER, salary REAL, "
        "manager_id INTEGER, note TEXT)"
    ),
    "CREATE TABLE proj (id INTEGER, emp_id INTEGER, title TEXT, hours INTEGER)",
    (
        "INSERT INTO dept VALUES (1, 'Engineering', 1000000.0), (2, 'Sales', 250000.5), "
        "(3, 'marketing', NULL), (4, 'Empty', 10.0)"
    ),
    (
        "INSERT INTO emp VALUES "
        "(1, 'Alice', 1, 150000.0, NULL, 'lead'), "
        "(2, 'bob', 1, 120000.5, 1, NULL), "
        "(3, 'Carol', 2, 90000.0, 1, 'remote'), "
        "(4, 'dave', 2, NULL, 3, '42'), "
        "(5, 'Eve', NULL, 70000.25, 3, 'Remote'), "
        "(6, 'Frank', 3, 70000.25, NULL, ''), "
        "(7, 'grace', 1, 99999.75, 2, '7'), "
        "(8, 'Heidi', 9, 50000.0, 2, NULL)"
    ),
    (
        "INSERT INTO proj VALUES "
        "(1, 1, 'Apollo', 120), (2, 1, 'Zephyr', 30), (3, 2, 'Apollo', 45), "
        "(4, 3, 'Mercury', NULL), (5, 7, 'Gemini', 80), (6, 99, 'Orphan', 5), "
        "(7, NULL, 'Nobody', 1)"
    ),
]


@pytest.fixture
def company(pair: Pair) -> Pair:
    pair.run(*SCHEMA)
    return pair
