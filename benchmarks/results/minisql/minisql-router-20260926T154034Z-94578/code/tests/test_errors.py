"""Invalid statements raise SQLError (and sqlite3 rejects them too)."""

import sqlite3

import pytest

from minisql import Database, SQLError

SETUP = [
    "CREATE TABLE a (id INTEGER, x TEXT)",
    "CREATE TABLE b (id INTEGER, y REAL)",
    "INSERT INTO a VALUES (1, 'p')",
]

BAD = [
    "SELEC * FROM a",
    "SELECT * FROM missing",
    "SELECT nope FROM a",
    "SELECT a.nope FROM a",
    "SELECT z.id FROM a",
    "SELECT id FROM a JOIN b ON a.id = b.id",
    "SELECT * FROM a JOIN b ON id = 1",
    "SELECT a.id FROM a AS t",
    "SELECT * FROM a WHERE",
    "SELECT * FROM a WHERE x = 'unterminated",
    "SELECT (1 + 2 FROM a",
    "SELECT 1 +",
    "SELECT * FROM a ORDER BY 3",
    "SELECT id FROM a ORDER BY 0",
    "SELECT * FROM a WHERE COUNT(*) > 1",
    "SELECT SUM(COUNT(*)) FROM a",
    "SELECT id FROM a GROUP BY COUNT(*)",
    "SELECT nosuchfunc(id) FROM a",
    "SELECT SUM(*) FROM a",
    "SELECT SUM(id, id) FROM a",
    "SELECT * FROM a LIMIT 'x'",
    "SELECT * FROM a; SELECT * FROM a",
    "SELECT b.* FROM a",
    "SELECT *",
    "INSERT INTO missing VALUES (1)",
    "INSERT INTO a VALUES (1)",
    "INSERT INTO a VALUES (1, 2, 3)",
    "INSERT INTO a (id, nope) VALUES (1, 2)",
    "INSERT INTO a (id) VALUES (1, 2)",
    "INSERT INTO a VALUES (id, 1)",
    "UPDATE missing SET x = 1",
    "UPDATE a SET nope = 1",
    "UPDATE a SET x = nope",
    "DELETE FROM missing",
    "DELETE FROM a WHERE nope = 1",
    "CREATE TABLE a (id INTEGER)",
    "CREATE TABLE c (id INTEGER, ID TEXT)",
    "CREATE TABLE d ()",
    "",
    "   ;",
    "SELECT 1 FROM a WHERE x @ 1",
    "SELECT 12abc FROM a",
]


@pytest.mark.parametrize("sql", BAD)
def test_invalid_sql_raises(sql):
    lite = sqlite3.connect(":memory:")
    db = Database()
    for s in SETUP:
        lite.execute(s)
        db.execute(s)
    # Sanity check: sqlite3 rejects the statement too.
    with pytest.raises((sqlite3.Error, sqlite3.Warning)):
        lite.execute(sql)
        if not sql.strip() or sql.strip() == ";":
            raise sqlite3.Error("empty statement")
    with pytest.raises(SQLError):
        db.execute(sql)


def test_failed_insert_is_atomic(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1), (2, 3)")
    assert db.execute("SELECT COUNT(*) FROM t") == [(0,)]


def test_failed_update_leaves_rows_unchanged(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1)")
    with pytest.raises(SQLError):
        db.execute("UPDATE t SET a = 2, b = 3")
    assert db.execute("SELECT a FROM t") == [(1,)]


def test_sqlerror_is_exception():
    assert issubclass(SQLError, Exception)


def test_non_string_rejected(db):
    with pytest.raises(SQLError):
        db.execute(None)  # type: ignore[arg-type]
