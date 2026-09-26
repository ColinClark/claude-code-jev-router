"""Shared fixtures: run the same SQL through minisql and sqlite3 and compare."""

from __future__ import annotations

import re
import sqlite3

import pytest

from minisql import Database, SQLError


def _sort_key(row):
    # -0.0 == 0.0 compares equal but reprs differ; normalize so sorting aligns rows.
    return repr(tuple((t, v + 0.0 if t == "float" else v) for t, v in row))


def typed(rows):
    return [tuple((type(v).__name__, v) for v in row) for row in rows]


class Pair:
    """Executes statements against both minisql and sqlite3."""

    def __init__(self):
        self.db = Database()
        self.conn = sqlite3.connect(":memory:")

    def exec(self, *sqls: str) -> None:
        for sql in sqls:
            self.conn.execute(sql)
            assert self.db.execute(sql) == []

    def query(self, sql: str, ordered: bool | None = None):
        if ordered is None:
            ordered = re.search(r"\border\s+by\b", sql, re.I) is not None
        expected = typed(tuple(r) for r in self.conn.execute(sql).fetchall())
        got_raw = self.db.execute(sql)
        assert isinstance(got_raw, list)
        assert all(isinstance(r, tuple) for r in got_raw)
        got = typed(got_raw)
        if not ordered:
            expected = sorted(expected, key=_sort_key)
            got = sorted(got, key=_sort_key)
        assert got == expected, f"\nSQL: {sql}\nminisql: {got}\nsqlite:  {expected}"
        return got_raw

    def both_error(self, sql: str) -> None:
        with pytest.raises(sqlite3.Error):
            self.conn.execute(sql)
        with pytest.raises(SQLError):
            self.db.execute(sql)

    def tables_equal(self, *names: str) -> None:
        for name in names:
            self.query(f"SELECT * FROM {name}")


@pytest.fixture
def pair() -> Pair:
    return Pair()


SAMPLE_SCHEMA = [
    "CREATE TABLE emp (id INTEGER, name TEXT, dept INTEGER, salary REAL, boss INTEGER)",
    "CREATE TABLE dept (id INTEGER, dname TEXT, budget INTEGER)",
    "CREATE TABLE proj (pid INTEGER, emp_id INTEGER, title TEXT, hours REAL)",
    "INSERT INTO emp VALUES (1, 'Alice', 10, 5000.0, NULL), (2, 'bob', 10, 4000, 1),"
    " (3, 'Carol', 20, 6000.5, 1), (4, 'dave', NULL, 3000, 2), (5, 'Eve', 20, NULL, 3),"
    " (6, NULL, 30, 4500, 3), (7, 'alice', 10, 4000, 2)",
    "INSERT INTO dept VALUES (10, 'Eng', 100000), (20, 'Sales', 50000), (30, 'Ops', NULL),"
    " (40, 'Empty', 0)",
    "INSERT INTO proj VALUES (100, 1, 'Apollo', 10.5), (101, 1, 'Gemini', 3),"
    " (102, 3, 'Mercury', NULL), (103, 9, 'Orphan', 1), (104, 2, 'apollo', 7.25)",
]


@pytest.fixture
def sample(pair: Pair) -> Pair:
    pair.exec(*SAMPLE_SCHEMA)
    return pair


def _configure_real_text_mode() -> None:
    """Match minisql's REAL->TEXT rendering to the sqlite3 library used for comparison."""
    from minisql import values

    rendered = sqlite3.connect(":memory:").execute("SELECT 1e15 || ''").fetchone()[0]
    values.REAL_TEXT_MODE = "legacy" if rendered == "1.0e+15" else "roundtrip"


_configure_real_text_mode()
