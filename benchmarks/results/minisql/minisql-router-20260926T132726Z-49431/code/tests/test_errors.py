"""Invalid SQL, unknown objects and ambiguity raise SQLError (as SQLite errors)."""

import sqlite3

import pytest

from minisql import Database, SQLError
from tests.conftest import SAMPLE_SETUP

BAD_SQL = [
    "SELEC 1",
    "SELECT",
    "SELECT FROM emp",
    "SELECT * FROM",
    "SELECT * FROM nope",
    "SELECT nope FROM emp",
    "SELECT x.id FROM emp",
    "SELECT emp.id FROM emp e",
    "SELECT e.nope FROM emp e",
    "SELECT name FROM emp e JOIN emp f ON e.id = f.boss",
    "SELECT id FROM emp JOIN dept ON 1 JOIN emp x ON 1",
    "SELECT * FROM emp WHERE",
    "SELECT * FROM emp WHERE id =",
    "SELECT * FROM emp ORDER BY",
    "SELECT * FROM emp ORDER BY 99",
    "SELECT id FROM emp ORDER BY 0",
    "SELECT * FROM emp GROUP BY",
    "SELECT (1 + 2",
    "SELECT 1 + 2)",
    "SELECT 'unterminated",
    "SELECT * FROM emp WHERE COUNT(*) > 1",
    "SELECT COUNT(MAX(id)) FROM emp",
    "SELECT id FROM emp GROUP BY COUNT(*)",
    "SELECT id FROM emp HAVING id > 1",
    "SELECT nosuchfn(1)",
    "SELECT sum(1, 2)",
    "SELECT 1 FROM emp LIMIT 'x'",
    "SELECT 1 NOT 2",
    "CREATE TABLE emp (a INTEGER)",
    "CREATE TABLE z (a INTEGER, A TEXT)",
    "CREATE TABLE",
    "INSERT INTO nope VALUES (1)",
    "INSERT INTO dept VALUES (1)",
    "INSERT INTO dept (code, nope) VALUES (1, 2)",
    "INSERT INTO dept (code) VALUES (1, 2)",
    "INSERT INTO dept VALUES",
    "INSERT INTO dept VALUES (nope, 1, 2)",
    "UPDATE nope SET a = 1",
    "UPDATE dept SET nope = 1",
    "UPDATE dept SET code = nope",
    "UPDATE dept SET floor = 1 WHERE nope = 2",
    "DELETE FROM nope",
    "DELETE FROM dept WHERE nope = 1",
    "DROP TABLE nope",
    "SELECT 1; SELECT 2",
    "SELECT 1 2 3",
    "SELECT 12abc",
    "SELECT 1 LIKE",
    "SELECT * FROM emp WHERE id IN 1",
    "SELECT * FROM emp WHERE id BETWEEN 1",
]


@pytest.mark.parametrize("sql", BAD_SQL)
def test_invalid_sql_raises(sql):
    lite = sqlite3.connect(":memory:")
    db = Database()
    for s in SAMPLE_SETUP:
        lite.execute(s)
        db.execute(s)
    # Confirm SQLite also rejects the statement, so the test encodes real SQLite behaviour.
    with pytest.raises((sqlite3.Error, sqlite3.Warning)):
        lite.execute(sql).fetchall()
    with pytest.raises(SQLError):
        db.execute(sql)


def test_ambiguous_column_message():
    db = Database()
    for s in SAMPLE_SETUP:
        db.execute(s)
    with pytest.raises(SQLError, match="ambiguous"):
        db.execute("SELECT id FROM emp a JOIN emp b ON a.id = b.boss")
    # Qualified references are fine.
    assert db.execute("SELECT a.id FROM emp a JOIN emp b ON a.id = b.boss WHERE b.id = 2") == [
        (1,)
    ]


def test_database_still_usable_after_error():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1, 2)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1), (nope)")
    db.execute("INSERT INTO t VALUES (5)")
    assert db.execute("SELECT a FROM t") == [(5,)]
