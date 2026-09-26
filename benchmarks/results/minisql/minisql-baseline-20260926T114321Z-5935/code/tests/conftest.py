"""Shared test helpers: run statements on minisql and sqlite3 side by side."""

from __future__ import annotations

import sqlite3

import pytest

from minisql import Database, SQLError


def _tag(v):
    # -0.0 and 0.0 are the same SQL value; which one SQLite surfaces for a group key
    # depends on its internal row order, so compare them as equal.
    if isinstance(v, float) and v == 0:
        v = 0.0
    return (type(v).__name__, v)


def typed(rows):
    """Rows with each value tagged by its Python type, so 1 and 1.0 differ."""
    return [tuple(_tag(v) for v in row) for row in rows]


class Pair:
    """A minisql database and a sqlite3 database fed identical statements."""

    def __init__(self) -> None:
        self.db = Database()
        self.lite = sqlite3.connect(":memory:")

    def run(self, *statements: str) -> None:
        for sql in statements:
            self.db.execute(sql)
            self.lite.execute(sql)

    def both(self, sql: str):
        return self.db.execute(sql), self.lite.execute(sql).fetchall()

    def check(self, sql: str, ordered: bool | None = None):
        """Assert minisql returns the same rows (values and types) as sqlite3."""
        mine, theirs = self.both(sql)
        if ordered is None:
            ordered = "ORDER BY" in sql.upper()
        a, b = typed(mine), typed(theirs)
        if not ordered:
            a, b = sorted(a, key=repr), sorted(b, key=repr)
        assert a == b, f"{sql}\n minisql: {mine}\n sqlite:  {theirs}"
        return mine


    def check_or_both_fail(self, sql: str) -> None:
        """Like check(), but also accept both engines rejecting the statement."""
        try:
            self.lite.execute(sql).fetchall()
        except sqlite3.Error:
            with pytest.raises(SQLError):
                self.db.execute(sql)
            return
        self.check(sql)


@pytest.fixture
def pair() -> Pair:
    return Pair()


@pytest.fixture
def db() -> Database:
    return Database()


SAMPLE_SCHEMA = [
    "CREATE TABLE emp (id INTEGER, name TEXT, dept TEXT, salary REAL, boss INTEGER, age INTEGER)",
    "CREATE TABLE dept (code TEXT, title TEXT, floor INTEGER)",
    "INSERT INTO emp VALUES (1, 'Alice', 'eng', 120000.0, NULL, 34)",
    "INSERT INTO emp VALUES (2, 'Bob', 'eng', 95000.5, 1, 28), (3, 'Carol', 'ops', 70000, 1, 45)",
    "INSERT INTO emp VALUES (4, 'dave', 'ops', NULL, 3, NULL), (5, 'Eve', NULL, 50000, 3, 23)",
    "INSERT INTO emp VALUES (6, 'frank', 'sales', 65000, 1, 39), (7, 'Grace', 'eng', 130000, 1, 51)",
    "INSERT INTO emp (id, name) VALUES (8, 'Heidi')",
    "INSERT INTO emp VALUES (9, 'ivan', 'sales', 65000, 6, 39), (10, 'Judy', 'eng', 95000.5, 2, 28)",
    "INSERT INTO dept VALUES ('eng', 'Engineering', 3), ('ops', 'Operations', 1)",
    "INSERT INTO dept VALUES ('hr', 'Human Resources', 2), ('sales', 'Sales', NULL)",
]


@pytest.fixture
def sample(pair: Pair) -> Pair:
    pair.run(*SAMPLE_SCHEMA)
    return pair
