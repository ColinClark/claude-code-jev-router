"""Shared differential-testing harness: run SQL on minisql and sqlite3 and compare."""

from __future__ import annotations

import re
import sqlite3

import pytest

from minisql import Database, SQLError

_ORDER_BY_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)


def typed(rows: list[tuple]) -> list[tuple]:
    """Rows as tuples of (type name, value) so 1 and 1.0 (or '1') never compare equal."""
    return [tuple((type(v).__name__, v) for v in row) for row in rows]


class Diff:
    """Executes statements against both engines and asserts identical results."""

    def __init__(self) -> None:
        self.db = Database()
        self.sq = sqlite3.connect(":memory:")

    def setup(self, *statements: str) -> None:
        for s in statements:
            self.sq.execute(s)
            self.db.execute(s)

    def run(self, sql: str, ordered: bool | None = None) -> list[tuple]:
        """Run ``sql`` on both engines; ordered compare iff ORDER BY is present."""
        expected = self.sq.execute(sql).fetchall()
        actual = self.db.execute(sql)
        assert isinstance(actual, list)
        assert all(isinstance(r, tuple) for r in actual)
        if ordered is None:
            ordered = bool(_ORDER_BY_RE.search(sql))
        e, a = typed(expected), typed(actual)
        if not ordered:
            e, a = sorted(e, key=repr), sorted(a, key=repr)
        assert a == e, f"\nSQL: {sql}\nminisql: {actual}\nsqlite : {expected}"
        return actual

    def value(self, expr: str) -> object:
        """Evaluate a single scalar expression (SELECT without FROM) on both engines."""
        return self.run(f"SELECT {expr}")[0][0]

    def error(self, sql: str) -> None:
        """Both engines must reject ``sql``."""
        with pytest.raises(sqlite3.Error):
            self.sq.execute(sql).fetchall()
        with pytest.raises(SQLError):
            self.db.execute(sql)


@pytest.fixture
def diff() -> Diff:
    return Diff()


@pytest.fixture
def people(diff: Diff) -> Diff:
    diff.setup(
        "CREATE TABLE people (id INTEGER, name TEXT, age INTEGER, score REAL, dept TEXT)",
        "INSERT INTO people VALUES (1, 'Alice', 30, 88.5, 'eng'), (2, 'Bob', 25, 72.0, 'eng'),"
        " (3, 'Carol', NULL, 91.25, 'ops'), (4, 'dave', 41, NULL, 'ops'),"
        " (5, 'Eve', 25, 60.0, NULL), (6, 'Al', 30, 88.5, 'hr'), (7, NULL, NULL, NULL, NULL)",
        "CREATE TABLE depts (code TEXT, title TEXT, floor INTEGER)",
        "INSERT INTO depts VALUES ('eng', 'Engineering', 3), ('ops', 'Operations', 1),"
        " ('fin', 'Finance', 2)",
        "CREATE TABLE badges (person_id INTEGER, badge TEXT)",
        "INSERT INTO badges VALUES (1, 'gold'), (1, 'silver'), (3, 'gold'), (9, 'none')",
    )
    return diff
