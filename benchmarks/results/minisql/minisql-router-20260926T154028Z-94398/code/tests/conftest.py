import sqlite3

import pytest

from minisql import Database, SQLError


class Both:
    """Runs every statement on minisql and sqlite3 and compares the results."""

    def __init__(self):
        self.db = Database()
        self.lite = sqlite3.connect(":memory:")

    def run(self, sql: str) -> None:
        self.db.execute(sql)
        self.lite.execute(sql)

    def check(self, sql: str, ordered: bool | None = None, allow_error: bool = False):
        if allow_error:
            try:
                theirs = self.lite.execute(sql).fetchall()
            except sqlite3.Error:
                with pytest.raises(SQLError):
                    self.db.execute(sql)
                return None
            ours = self.db.execute(sql)
        else:
            ours = self.db.execute(sql)
            theirs = self.lite.execute(sql).fetchall()
        if ordered is None:
            ordered = "ORDER BY" in sql.upper()
        if not ordered:
            ours_c, theirs_c = sorted(ours, key=_row_key), sorted(theirs, key=_row_key)
        else:
            ours_c, theirs_c = ours, theirs
        assert _typed(ours_c) == _typed(theirs_c), f"{sql}\nminisql: {ours}\nsqlite:  {theirs}"
        return ours


def _typed(rows):
    return [tuple((type(v).__name__, v) for v in row) for row in rows]


def _row_key(row):
    return tuple((0, 0) if v is None else (1, v) if not isinstance(v, str) else (2, v) for v in row)


@pytest.fixture
def both():
    return Both()


@pytest.fixture
def db():
    return Database()
