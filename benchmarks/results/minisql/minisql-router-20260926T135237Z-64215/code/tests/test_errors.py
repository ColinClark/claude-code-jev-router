"""Error conditions raise SQLError (and fail in sqlite3 as well)."""

import pytest

from minisql import SQLError


@pytest.fixture
def setup(pair):
    pair.run(
        "CREATE TABLE a (id INTEGER, x TEXT)",
        "CREATE TABLE b (id INTEGER, y TEXT)",
        "INSERT INTO a VALUES (1, 'p')",
        "INSERT INTO b VALUES (1, 'q')",
    )
    return pair


@pytest.mark.parametrize(
    "sql",
    [
        # unknown tables / columns
        "SELECT * FROM missing",
        "SELECT nope FROM a",
        "SELECT a.nope FROM a",
        "SELECT zz.id FROM a",
        "SELECT zz.* FROM a",
        "SELECT a.id FROM a AS t",
        "SELECT * FROM a WHERE nope = 1",
        "SELECT * FROM a ORDER BY nope",
        "SELECT id FROM a GROUP BY nope",
        "INSERT INTO missing VALUES (1)",
        "INSERT INTO a (nope) VALUES (1)",
        "UPDATE a SET nope = 1",
        "UPDATE a SET x = nope",
        "UPDATE missing SET x = 1",
        "DELETE FROM missing",
        "DELETE FROM a WHERE nope",
        "SELECT * FROM a JOIN b ON a.id = c.id",
        # ambiguity
        "SELECT id FROM a JOIN b ON a.id = b.id",
        "SELECT * FROM a JOIN b ON id = 1",
        "SELECT * FROM a, b WHERE id = 1",
        # syntax errors
        "SELEC * FROM a",
        "SELECT * FROM",
        "SELECT * FROM a WHERE",
        "SELECT (1 + 2 FROM a",
        "SELECT 1 +",
        "SELECT * FROM a ORDER",
        "SELECT 'unterminated",
        "SELECT * FROM a LIMIT",
        "INSERT INTO a VALUES",
        "CREATE TABLE",
        "SELECT * FROM a b c",
        "SELECT 1 2",
        "SELECT id FROM a; SELECT 1",
        "SELECT x NOT 5 FROM a",
        "SELECT 1 BETWEEN 2",
        "SELECT 1 IN 2",
        "SELECT CASE END",
        "SELECT @ FROM a",
        # aggregates in the wrong place
        "SELECT * FROM a WHERE COUNT(*) > 0",
        "SELECT id FROM a GROUP BY COUNT(*)",
        "SELECT SUM(COUNT(*)) FROM a",
        "UPDATE a SET id = COUNT(*)",
        "SELECT * FROM a JOIN b ON COUNT(*) > 0",
        # value count mismatch
        "INSERT INTO a VALUES (1)",
        "INSERT INTO a VALUES (1, 'x', 3)",
        "INSERT INTO a (id) VALUES (1, 2)",
        "INSERT INTO a VALUES (1, 'x'), (2)",
        # duplicate table / column
        "CREATE TABLE a (z INTEGER)",
        "CREATE TABLE c (z INTEGER, Z TEXT)",
        # misc
        "SELECT *",
        "SELECT id FROM a ORDER BY 2",
        "SELECT id FROM a ORDER BY 0",
        "SELECT id FROM a GROUP BY 5",
        "SELECT id FROM a HAVING id > 0",
        "SELECT nosuchfunc(1)",
        "SELECT COUNT(1, 2) FROM a",
        "SELECT * FROM a LIMIT 'x'",
    ],
)
def test_errors(setup, sql):
    setup.check_error(sql)


def test_error_type_is_sqlerror(db):
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM nowhere")
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("CREATE TABLE T (b INTEGER)")


def test_database_usable_after_error(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1, 2)")
    db.execute("INSERT INTO t VALUES (1)")
    assert db.execute("SELECT a FROM t") == [(1,)]


def test_deeply_nested_expression_does_not_crash(db):
    expr = "(" * 3000 + "1" + ")" * 3000
    try:
        result = db.execute(f"SELECT {expr}")
    except SQLError:
        return
    assert result == [(1,)]


def test_empty_statement_matches_sqlite(pair):
    pair.run("", "  ;", "-- just a comment")
