import sqlite3

import pytest

from minisql import Database


def typed(rows):
    """Rows with each value tagged by its Python type, so 1 and 1.0 differ."""
    return [
        tuple((type(v).__name__, v + 0.0 if isinstance(v, float) else v) for v in row)
        for row in rows
    ]


class Pair:
    """Runs statements on both minisql and sqlite3 and compares the results."""

    def __init__(self):
        self.db = Database()
        self.lite = sqlite3.connect(":memory:")

    def run(self, *statements):
        for sql in statements:
            self.db.execute(sql)
            self.lite.execute(sql)

    def check(self, sql, ordered=None):
        if ordered is None:
            ordered = "ORDER BY" in sql.upper()
        expected = typed(self.lite.execute(sql).fetchall())
        actual = typed(self.db.execute(sql))
        if not ordered:
            expected.sort(key=repr)
            actual.sort(key=repr)
        assert actual == expected, sql
        return actual


@pytest.fixture
def pair():
    return Pair()


@pytest.fixture
def db():
    return Database()
