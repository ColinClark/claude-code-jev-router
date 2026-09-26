import sqlite3

import pytest

from minisql import Database, SQLError


class Both:
    """Runs every statement against minisql and sqlite3 side by side."""

    def __init__(self):
        self.db = Database()
        self.conn = sqlite3.connect(":memory:")

    def run(self, *stmts: str) -> None:
        for stmt in stmts:
            self.conn.execute(stmt)
            assert self.db.execute(stmt) == []

    def check(self, sql: str, ordered: bool | None = None) -> list[tuple]:
        """Assert minisql returns exactly what sqlite returns (values and Python types)."""
        expected = self.conn.execute(sql).fetchall()
        actual = self.db.execute(sql)
        if ordered is None:
            ordered = "ORDER BY" in sql.upper()
        assert typed(actual, ordered) == typed(expected, ordered), sql
        return actual

    def check_error(self, sql: str) -> None:
        with pytest.raises(sqlite3.Error):
            self.conn.execute(sql).fetchall()
        with pytest.raises(SQLError):
            self.db.execute(sql)


def typed(rows, ordered: bool):
    out = [tuple((type(v).__name__, v) for v in row) for row in rows]
    if not ordered:
        out.sort(key=repr)
    return out


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def both():
    return Both()


@pytest.fixture
def company(both):
    both.run(
        "CREATE TABLE dept (id INTEGER, name TEXT, budget REAL)",
        "CREATE TABLE emp (id INTEGER, name TEXT, dept_id INTEGER, salary REAL, "
        "manager_id INTEGER, title TEXT)",
        "CREATE TABLE project (id INTEGER, emp_id INTEGER, name TEXT, hours INTEGER)",
        "INSERT INTO dept VALUES (1, 'Engineering', 1000000.0), (2, 'Sales', 250000.5), "
        "(3, 'Marketing', NULL), (4, 'Empty', 10.0)",
        "INSERT INTO emp VALUES "
        "(1, 'Alice', 1, 150000.0, NULL, 'CTO'), "
        "(2, 'Bob', 1, 95000.0, 1, 'Engineer'), "
        "(3, 'carol', 1, 105000.5, 1, 'engineer'), "
        "(4, 'Dave', 2, 60000.0, NULL, 'Sales Lead'), "
        "(5, 'Eve', 2, NULL, 4, NULL), "
        "(6, 'Frank', NULL, 45000.0, NULL, 'Intern'), "
        "(7, 'Grace', 3, 70000.0, NULL, 'Marketer'), "
        "(8, 'heidi', 1, 95000.0, 2, 'Engineer')",
        "INSERT INTO project VALUES (1, 2, 'Compiler', 120), (2, 2, 'Database', 80), "
        "(3, 3, 'Database', 40), (4, 4, 'Deals', NULL), (5, 99, 'Orphan', 5), "
        "(6, 8, 'Compiler', 10)",
    )
    return both
