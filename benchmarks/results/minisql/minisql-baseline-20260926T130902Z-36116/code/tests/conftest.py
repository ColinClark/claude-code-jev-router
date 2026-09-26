from __future__ import annotations

import sqlite3
from collections import Counter

import pytest

from minisql import Database


@pytest.fixture
def db():
    return Database()


def run_minisql(setup: list[str], query: str) -> list[tuple]:
    database = Database()
    for stmt in setup:
        database.execute(stmt)
    return database.execute(query)


def run_sqlite(setup: list[str], query: str) -> list[tuple]:
    conn = sqlite3.connect(":memory:")
    try:
        cur = conn.cursor()
        for stmt in setup:
            cur.execute(stmt)
        cur.execute(query)
        return cur.fetchall()
    finally:
        conn.close()


def assert_matches_sqlite(setup: list[str], query: str, ordered: bool = True) -> list[tuple]:
    mini_result = run_minisql(setup, query)
    sqlite_result = run_sqlite(setup, query)
    if ordered:
        assert mini_result == sqlite_result
    else:
        assert Counter(mini_result) == Counter(sqlite_result)
    return mini_result
