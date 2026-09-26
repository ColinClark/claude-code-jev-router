"""Shared fixtures: a differential harness running SQL on minisql and sqlite3."""

from __future__ import annotations

import re
import sqlite3

import pytest

from minisql import Database, SQLError


def typed(rows: list[tuple]) -> list[tuple]:
    """Make values type-sensitive: 1, 1.0 and '1' all compare differently."""
    return [tuple((type(v).__name__, v) for v in row) for row in rows]


def _sort_key(row: tuple) -> tuple:
    return tuple((name, repr(v)) for name, v in row)


class Dual:
    """Runs identical SQL against minisql.Database and sqlite3 and compares."""

    def __init__(self) -> None:
        self.mini = Database()
        self.lite = sqlite3.connect(":memory:")

    def run(self, sql: str) -> None:
        """Execute a statement on both engines; both must succeed or both must fail."""
        lite_err = mini_err = None
        try:
            self.lite.execute(sql)
        except sqlite3.Error as exc:
            lite_err = exc
        try:
            self.mini.execute(sql)
        except SQLError as exc:
            mini_err = exc
        assert (lite_err is None) == (mini_err is None), (sql, lite_err, mini_err)

    def script(self, *statements: str) -> None:
        for s in statements:
            self.run(s)

    def query(self, sql: str) -> tuple[list[tuple], list[tuple]]:
        expected = self.lite.execute(sql).fetchall()
        actual = self.mini.execute(sql)
        return expected, actual

    def check(self, sql: str, ordered: bool | None = None) -> list[tuple]:
        """Compare results; exact order iff the query has ORDER BY (or ordered=True)."""
        expected, actual = self.query(sql)
        assert isinstance(actual, list)
        assert all(isinstance(r, tuple) for r in actual), actual
        if ordered is None:
            ordered = re.search(r"\border\s+by\b", sql, re.IGNORECASE) is not None
        exp_t, act_t = typed(expected), typed(actual)
        if not ordered:
            exp_t = sorted(exp_t, key=_sort_key)
            act_t = sorted(act_t, key=_sort_key)
        assert act_t == exp_t, f"\nSQL: {sql}\nsqlite:  {expected}\nminisql: {actual}"
        return actual

    def check_error(self, sql: str) -> None:
        with pytest.raises(sqlite3.Error):
            self.lite.execute(sql).fetchall()
        with pytest.raises(SQLError):
            self.mini.execute(sql)


@pytest.fixture
def dual() -> Dual:
    return Dual()
