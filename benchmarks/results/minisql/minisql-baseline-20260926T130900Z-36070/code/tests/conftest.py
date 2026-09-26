from __future__ import annotations

import sqlite3

import pytest

from minisql import Database


def _sort_key(row: tuple):
    def cell_key(v):
        if v is None:
            return (0, "")
        if isinstance(v, (int, float)):
            return (1, v)
        return (2, v)

    return tuple(cell_key(v) for v in row)


class DualRunner:
    """Runs SQL against both minisql and real sqlite3, comparing results."""

    def __init__(self):
        self.mini = Database()
        self.sql = sqlite3.connect(":memory:")
        self.sql.execute("PRAGMA foreign_keys = OFF")

    def run(self, sql: str) -> None:
        """Execute a statement (DDL/DML) on both engines; no result comparison."""
        self.mini.execute(sql)
        self.sql.execute(sql)
        self.sql.commit()

    def query(self, sql: str, ordered: bool = False) -> list[tuple]:
        """Execute a SELECT on both engines and assert the results match."""
        mini_rows = self.mini.execute(sql)
        sqlite_rows = self.sql.execute(sql).fetchall()
        if ordered:
            assert mini_rows == sqlite_rows, f"{sql}\nminisql={mini_rows}\nsqlite ={sqlite_rows}"
        else:
            assert sorted(mini_rows, key=_sort_key) == sorted(sqlite_rows, key=_sort_key), (
                f"{sql}\nminisql={mini_rows}\nsqlite ={sqlite_rows}"
            )
        return mini_rows


@pytest.fixture
def db() -> Database:
    return Database()


@pytest.fixture
def dual() -> DualRunner:
    return DualRunner()
