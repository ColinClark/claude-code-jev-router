"""Differential test harness: run the same SQL on minisql and sqlite3 and compare."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence

import pytest

from minisql import Database, SQLError


def typed(rows: Iterable[Sequence[object]]) -> list[tuple]:
    """Tag every value with its type so 1 and 1.0 (or 1 and '1') never compare equal."""
    return [tuple((type(v).__name__, v) for v in row) for row in rows]


def _value_key(v: object) -> tuple:
    if v is None:
        return (0, 0, "")
    if isinstance(v, str):
        return (2, v, "")
    return (1, v, type(v).__name__)


def row_key(row: Sequence[object]) -> tuple:
    return tuple(_value_key(v) for v in row)


def canonical_unordered(rows: Iterable[Sequence[object]]) -> list[tuple]:
    return typed(sorted((tuple(r) for r in rows), key=row_key))


def canonical_ordered_ties(rows: Iterable[Sequence[object]]) -> list[list[tuple]]:
    """For queries ordered by *all* output columns: group rows that SQL considers equal
    (e.g. 1 and 1.0) and sort only inside each group, keeping the group sequence."""
    groups: list[list[tuple]] = []
    prev = None
    for r in rows:
        k = tuple(r)
        if prev is not None and k == prev:  # Python == matches SQL equality for these
            groups[-1].append(k)
        else:
            groups.append([k])
        prev = k
    return [canonical_unordered(g) for g in groups]


class Differential:
    """A pair of databases kept in lock-step."""

    def __init__(self) -> None:
        self.mini = Database()
        self.lite = sqlite3.connect(":memory:")

    def run(self, sql: str) -> None:
        """Execute DDL/DML on both; both must succeed and return nothing."""
        self.lite.execute(sql)
        assert self.mini.execute(sql) == []

    def run_many(self, statements: Iterable[str]) -> None:
        for sql in statements:
            self.run(sql)

    def expected(self, sql: str) -> list[tuple]:
        return self.lite.execute(sql).fetchall()

    def check(self, sql: str, ordered: bool | None = None, ties: bool = False) -> list[tuple]:
        """Assert minisql returns exactly what sqlite3 returns (values and types)."""
        expected = self.expected(sql)
        actual = self.mini.execute(sql)
        assert isinstance(actual, list)
        assert all(isinstance(r, tuple) for r in actual)
        if ordered is None:
            ordered = "ORDER BY" in sql.upper()
        if ordered and ties:
            assert canonical_ordered_ties(actual) == canonical_ordered_ties(expected), sql
        elif ordered:
            assert typed(actual) == typed(expected), sql
        else:
            assert canonical_unordered(actual) == canonical_unordered(expected), sql
        return actual

    def check_error(self, sql: str) -> None:
        """Both engines must reject the statement; minisql with SQLError."""
        with pytest.raises(sqlite3.Error):
            self.lite.execute(sql).fetchall()
        with pytest.raises(SQLError):
            self.mini.execute(sql)

    def close(self) -> None:
        self.lite.close()


SCHEMA = [
    "CREATE TABLE emp (id INTEGER, name TEXT, dept TEXT, salary REAL, age INTEGER, mgr INTEGER)",
    """INSERT INTO emp VALUES
        (1, 'Alice', 'eng', 120000.0, 34, NULL),
        (2, 'bob', 'eng', 95000.5, 28, 1),
        (3, 'Carol', 'sales', 70000, 45, 1),
        (4, 'dave', 'sales', NULL, 38, 3),
        (5, 'Eve', NULL, 50000.25, NULL, 3),
        (6, 'frank', 'hr', 65000, 50, 1),
        (7, 'Grace', 'eng', 130000, 41, 1),
        (8, 'heidi', 'hr', 65000, 29, 6),
        (9, 'Ivan', 'ops', 0.0, 22, 7),
        (10, 'judy', 'eng', 88000.75, 31, 7),
        (11, 'Mallory', 'sales', 70000, 45, 3),
        (12, 'ALICE', 'ops', 42.5, 60, NULL)""",
    "CREATE TABLE dept (code TEXT, title TEXT, budget INTEGER, floor INTEGER)",
    """INSERT INTO dept VALUES
        ('eng', 'Engineering', 1000000, 3),
        ('sales', 'Sales', 500000, 2),
        ('hr', 'Human Resources', NULL, 2),
        ('legal', 'Legal', 250000, NULL),
        ('ops', 'Operations', 300000, 1)""",
    "CREATE TABLE nums (id INTEGER, a INTEGER, b INTEGER, x REAL, s TEXT)",
    """INSERT INTO nums VALUES
        (1, 1, 2, 1.5, '1'),
        (2, -7, 2, -2.5, '10'),
        (3, 7, -2, 0.1, 'abc'),
        (4, 0, 0, 0.0, ''),
        (5, NULL, 3, NULL, NULL),
        (6, 5, NULL, 2.0, '5'),
        (7, -3, -3, -0.5, '-3'),
        (8, 100, 7, 1e20, '1e3'),
        (9, 2, 2, 3.0, ' 2'),
        (10, 13, 4, 1e-5, 'Abc')""",
    "CREATE TABLE empty (a INTEGER, b TEXT)",
    "CREATE TABLE words (w TEXT, n INTEGER)",
    """INSERT INTO words VALUES
        ('apple', 1), ('Apple', 2), ('banana', 3), ('_under', 4), ('100%', 5), ('a_b', 6),
        ('ÉCOLE', 7), ('école', 8), ('', 9), (NULL, 10), ('Zed', 11), ('zed', 12)""",
    "CREATE TABLE mixed (id INTEGER, v)",
    """INSERT INTO mixed VALUES
        (1, 3), (2, 'b'), (3, NULL), (4, 2.5), (5, 'A'), (6, -1), (7, '10'), (8, 0.5),
        (9, 'a'), (10, NULL), (11, 100), (12, '')""",
    "CREATE TABLE big (a INTEGER)",
    "INSERT INTO big VALUES (9223372036854775807), (1)",
    "CREATE TABLE aff (id INTEGER, i INTEGER, r REAL, t TEXT, n NUMERIC, b)",
    """INSERT INTO aff VALUES
        (1, 5, 5, 5, '5', '5'),
        (2, '12', '2.5', 1.5, '3.0', 3.0),
        (3, 3.0, 7, 1e20, ' 7 ', '  8'),
        (4, 'abc', 'x1', 1e15, '1e3', NULL),
        (5, 1e20, 1, 0.1, 2.5, 1),
        (6, '0012', '-0', -0.0, 'abc', 'x'),
        (7, ' 42 ', '1e2', 100, '0x10', 2.0),
        (8, 2.5, NULL, 'text', 7.0, -4)""",
]


def make_populated() -> Differential:
    d = Differential()
    d.run_many(SCHEMA)
    return d


@pytest.fixture(scope="module")
def shared() -> Iterable[Differential]:
    """Read-only populated pair shared across a module."""
    d = make_populated()
    yield d
    d.close()


@pytest.fixture
def fresh() -> Iterable[Differential]:
    """Populated pair for tests that modify data."""
    d = make_populated()
    yield d
    d.close()


@pytest.fixture
def empty_pair() -> Iterable[Differential]:
    d = Differential()
    yield d
    d.close()
