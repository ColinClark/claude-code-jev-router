"""Shared helpers: run the same SQL on minisql and on stdlib sqlite3 and compare."""

from __future__ import annotations

import math
import sqlite3

import pytest

from minisql import Database


def _typed(rows):
    out = []
    for row in rows:
        vals = []
        for v in row:
            if isinstance(v, float) and math.isnan(v):
                vals.append(("nan", None))
            elif isinstance(v, float) and v == 0.0:
                vals.append(("float", 0.0))  # -0.0 == 0.0; normalise for stable sorting
            else:
                vals.append((type(v).__name__, v))
        out.append(tuple(vals))
    return out


def _sort_key(row):
    return repr(row)


class Pair:
    """A minisql database and a sqlite3 database fed identical statements."""

    def __init__(self, *setup: str):
        self.mini = Database()
        self.lite = sqlite3.connect(":memory:")
        for sql in setup:
            self.run(sql)

    def run(self, sql: str) -> None:
        self.lite.execute(sql)
        assert self.mini.execute(sql) == []

    def check(self, sql: str, ordered: bool | None = None) -> list[tuple]:
        """Assert minisql returns the same rows (values and types) as SQLite."""
        expected = [tuple(r) for r in self.lite.execute(sql).fetchall()]
        got = self.mini.execute(sql)
        assert isinstance(got, list)
        assert all(isinstance(r, tuple) for r in got)
        if ordered is None:
            ordered = "ORDER BY" in sql.upper()
        e, g = _typed(expected), _typed(got)
        if not ordered:
            e = sorted(e, key=_sort_key)
            g = sorted(g, key=_sort_key)
        assert g == e, f"\nSQL: {sql}\nminisql: {got}\nsqlite:  {expected}"
        return got


@pytest.fixture
def pair():
    return Pair


SAMPLE_SETUP = (
    "CREATE TABLE emp (id INTEGER, name TEXT, dept TEXT, salary REAL, age INTEGER, boss INTEGER)",
    "INSERT INTO emp VALUES "
    "(1, 'Alice', 'eng', 120000.0, 34, NULL),"
    "(2, 'Bob', 'eng', 95000.5, 45, 1),"
    "(3, 'carol', 'sales', 70000.0, 29, 1),"
    "(4, 'Dave', 'sales', NULL, 51, 3),"
    "(5, 'Eve', NULL, 88000.25, NULL, 1),"
    "(6, 'frank', 'hr', 61000.0, 38, 3),"
    "(7, 'Grace', 'eng', 130000.0, 27, 2),"
    "(8, 'heidi', 'hr', NULL, 44, NULL),"
    "(9, 'Ivan_x', 'ops', 55000.0, 60, 7),"
    "(10, 'Judy%', 'ops', 55000.0, 60, 7)",
    "CREATE TABLE dept (code TEXT, title TEXT, floor INTEGER)",
    "INSERT INTO dept VALUES ('eng', 'Engineering', 3), ('sales', 'Sales', 1),"
    " ('hr', 'Human Resources', 2), ('legal', 'Legal', NULL)",
    "CREATE TABLE nums (i INTEGER, r REAL, t TEXT)",
    "INSERT INTO nums VALUES (1, 1.5, 'a'), (2, -2.25, 'B'), (NULL, NULL, NULL),"
    " (-7, 0.0, 'abc'), (0, 3.0, ''), (7, NULL, 'Abc'), (3, 1e20, 'x_y'), (-3, -0.5, '10')",
)


@pytest.fixture
def sample():
    return Pair(*SAMPLE_SETUP)
