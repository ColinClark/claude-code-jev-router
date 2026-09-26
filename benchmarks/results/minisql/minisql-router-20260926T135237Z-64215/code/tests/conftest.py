"""Shared fixtures: a differential harness running SQL on minisql and sqlite3."""

from __future__ import annotations

import sqlite3

import pytest

from minisql import Database, SQLError


def typed(rows):
    """Rows with each value tagged by its exact Python type."""
    return [tuple((type(v).__name__, v) for v in row) for row in rows]


def _sort_key(row):
    return repr(row)


class Pair:
    """Runs every statement on both engines and compares the results."""

    def __init__(self) -> None:
        self.db = Database()
        self.conn = sqlite3.connect(":memory:")

    def run(self, *statements: str) -> None:
        for sql in statements:
            expected = self.conn.execute(sql).fetchall()
            got = self.db.execute(sql)
            assert got == [] and expected == [] or typed(got) == typed(expected), sql

    def check(self, sql: str, ordered: bool | None = None):
        expected = self.conn.execute(sql).fetchall()
        got = self.db.execute(sql)
        assert isinstance(got, list)
        assert all(isinstance(r, tuple) for r in got)
        if ordered is None:
            ordered = "ORDER BY" in sql.upper()
        exp_t = typed(expected)
        got_t = typed(got)
        if not ordered:
            exp_t = sorted(exp_t, key=_sort_key)
            got_t = sorted(got_t, key=_sort_key)
        assert got_t == exp_t, f"{sql}\n minisql: {got}\n sqlite:  {expected}"
        return got

    def check_error(self, sql: str) -> None:
        with pytest.raises(sqlite3.Error):
            self.conn.execute(sql).fetchall()
        with pytest.raises(SQLError):
            self.db.execute(sql)

    def check_same(self, sql: str, ordered: bool | None = None):
        """Compare results, or require both engines to fail."""
        try:
            expected = self.conn.execute(sql).fetchall()
        except sqlite3.Error:
            with pytest.raises(SQLError):
                self.db.execute(sql)
            return None
        del expected
        return self.check(sql, ordered)


@pytest.fixture
def pair() -> Pair:
    return Pair()


@pytest.fixture
def db() -> Database:
    return Database()


def _configure_real_text_mode() -> None:
    """Match minisql's REAL->TEXT rendering to the linked SQLite's behaviour."""
    from minisql import values

    conn = sqlite3.connect(":memory:")
    (text,) = conn.execute("SELECT CAST(0.1 + 0.2 AS TEXT)").fetchone()
    values.set_real_text_mode("roundtrip" if text != "0.3" else "classic")


_configure_real_text_mode()
