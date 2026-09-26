import sqlite3

import pytest

from minisql import Database


def _typed(rows):
    return [tuple((type(v).__name__, v) for v in row) for row in rows]


def _unordered_key(row):
    return [(name, repr(v)) for name, v in row]


class Pair:
    """Runs every statement against both minisql and sqlite3 and compares the results."""

    def __init__(self):
        self.db = Database()
        self.ref = sqlite3.connect(":memory:")

    def run(self, sql: str):
        expected = self.ref.execute(sql).fetchall()
        actual = self.db.execute(sql)
        return actual, expected

    def exec(self, *statements: str) -> None:
        for sql in statements:
            actual, expected = self.run(sql)
            assert actual == expected == [], sql

    def check(self, sql: str, ordered: bool | None = None):
        if ordered is None:
            ordered = "ORDER BY" in sql.upper()
        actual, expected = self.run(sql)
        assert isinstance(actual, list)
        assert all(isinstance(r, tuple) for r in actual)
        a, e = _typed(actual), _typed(expected)
        if not ordered:
            a.sort(key=_unordered_key)
            e.sort(key=_unordered_key)
        assert a == e, f"{sql}\n minisql: {actual}\n  sqlite: {expected}"
        return actual


@pytest.fixture
def pair():
    p = Pair()
    yield p
    p.ref.close()


@pytest.fixture
def people(pair):
    pair.exec(
        "CREATE TABLE people (id INTEGER, name TEXT, age INTEGER, city TEXT, score REAL)",
        "INSERT INTO people VALUES (1, 'Alice', 30, 'Paris', 88.5), (2, 'bob', 25, 'London', 92.0),"
        " (3, 'Carol', NULL, 'Paris', NULL), (4, 'dave', 35, NULL, 70.25),"
        " (5, 'Eve', 25, 'Berlin', 92.0), (6, 'frank', 40, 'London', -3.5),"
        " (7, NULL, 30, 'Paris', 0.0), (8, 'Alice', 22, 'berlin', 55.0)",
        "CREATE TABLE orders (id INTEGER, person_id INTEGER, amount REAL, item TEXT, qty INTEGER)",
        "INSERT INTO orders VALUES (1, 1, 10.5, 'apple', 3), (2, 1, 20.0, 'pear', 1),"
        " (3, 2, 5.25, 'apple', 10), (4, 4, NULL, 'plum', NULL), (5, 9, 7.0, 'kiwi', 2),"
        " (6, 5, 12.0, 'apple', 0), (7, NULL, 1.0, 'fig', 5), (8, 2, 3.0, 'Apple', 4)",
        "CREATE TABLE cities (name TEXT, country TEXT, pop INTEGER)",
        "INSERT INTO cities VALUES ('Paris', 'FR', 2100000), ('London', 'UK', 8900000),"
        " ('Berlin', 'DE', 3600000), ('Rome', 'IT', 2800000)",
    )
    return pair
