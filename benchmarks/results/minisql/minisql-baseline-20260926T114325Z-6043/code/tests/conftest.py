import sqlite3

import pytest

from minisql import Database


def typed(rows):
    """Tag each value with its type so 1 and 1.0 (or 1 and '1') never compare equal."""
    return [tuple((type(v).__name__, v) for v in row) for row in rows]


def _canonical(value):
    # -0.0 == 0.0, but their reprs differ; normalise so sorting is stable across both.
    return value + 0.0 if isinstance(value, float) else value


def unordered(rows):
    return sorted(typed(rows), key=lambda row: repr([(t, _canonical(v)) for t, v in row]))


class Both:
    """Runs statements against minisql and sqlite3 and compares the results."""

    def __init__(self):
        self.db = Database()
        self.ref = sqlite3.connect(":memory:")

    def run(self, *statements):
        for sql in statements:
            self.db.execute(sql)
            self.ref.execute(sql)

    def check(self, sql, ordered=None):
        if ordered is None:
            ordered = "ORDER BY" in sql.upper()
        ours = self.db.execute(sql)
        theirs = self.ref.execute(sql).fetchall()
        assert all(type(r) is tuple for r in ours)
        if ordered:
            assert typed(ours) == typed(theirs), sql
        else:
            assert unordered(ours) == unordered(theirs), sql
        return ours


@pytest.fixture
def both():
    b = Both()
    yield b
    b.ref.close()


@pytest.fixture
def people(both):
    both.run(
        "CREATE TABLE people (id INTEGER, name TEXT, age INTEGER, city TEXT, score REAL)",
        """INSERT INTO people VALUES
            (1, 'Alice', 30, 'Paris', 88.5),
            (2, 'bob', 25, 'London', 72.0),
            (3, 'Carol', NULL, 'Paris', NULL),
            (4, 'dave', 41, NULL, 91.25),
            (5, 'Eve', 25, 'Berlin', 60.0),
            (6, 'frank', 35, 'London', NULL),
            (7, 'Grace', 30, 'paris', 75.5)""",
        "CREATE TABLE orders (oid INTEGER, pid INTEGER, amount REAL, item TEXT)",
        """INSERT INTO orders VALUES
            (100, 1, 10.5, 'book'),
            (101, 1, 20.0, 'pen'),
            (102, 2, 5.25, 'book'),
            (103, 4, NULL, 'lamp'),
            (104, 9, 7.0, 'cup'),
            (105, NULL, 3.0, 'pen'),
            (106, 2, 12.0, NULL)""",
    )
    return both
