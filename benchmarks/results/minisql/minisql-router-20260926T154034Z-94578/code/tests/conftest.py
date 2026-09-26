import math
import sqlite3

import pytest

from minisql import Database, SQLError


def typed(rows):
    """Rows with each value tagged by its Python type, so 1 and 1.0 compare unequal."""
    out = []
    for row in rows:
        tagged = []
        for v in row:
            if isinstance(v, float) and math.isnan(v):
                tagged.append(("float", "nan"))
            else:
                tagged.append((type(v).__name__, v))
        out.append(tuple(tagged))
    return out


def unordered(rows):
    return sorted(typed(rows), key=repr)


class Pair:
    """Runs every statement on both minisql and sqlite3 and compares results."""

    def __init__(self):
        self.mini = Database()
        self.lite = sqlite3.connect(":memory:")

    def run(self, sql):
        try:
            expected = self.lite.execute(sql).fetchall()
        except sqlite3.Error:
            # sqlite3 rejects it at parse or run time, so minisql must reject it too.
            with pytest.raises(SQLError):
                self.mini.execute(sql)
            return None, None
        got = self.mini.execute(sql)
        return got, expected

    def exec(self, *statements):
        for sql in statements:
            got, expected = self.run(sql)
            assert got is not None, f"statement failed: {sql}"
            assert got == [] or sql.lstrip().upper().startswith("SELECT")
            assert typed(got) == typed(expected), sql

    def check(self, sql, ordered=None):
        """Compare a query; order matters when ordered is True (default: if ORDER BY present)."""
        if ordered is None:
            ordered = "ORDER BY" in sql.upper()
        got, expected = self.run(sql)
        if got is None:
            return None
        if ordered:
            assert typed(got) == typed(expected), sql
        else:
            assert unordered(got) == unordered(expected), sql
        return got


@pytest.fixture
def pair():
    p = Pair()
    yield p
    p.lite.close()


@pytest.fixture
def db():
    return Database()
