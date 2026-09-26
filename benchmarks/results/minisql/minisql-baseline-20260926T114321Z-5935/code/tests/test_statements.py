"""DDL/DML statements, the public API and error handling."""

import sqlite3

import pytest

from minisql import Database, SQLError


def test_public_api(db):
    assert db.execute("CREATE TABLE t (a INTEGER, b TEXT)") == []
    assert db.execute("INSERT INTO t VALUES (1, 'x'), (2, 'y')") == []
    assert db.execute("SELECT a, b FROM t ORDER BY a") == [(1, "x"), (2, "y")]
    assert db.execute("UPDATE t SET b = 'z' WHERE a = 1") == []
    assert db.execute("DELETE FROM t WHERE a = 2") == []
    assert db.execute("SELECT * FROM t") == [(1, "z")]
    assert isinstance(db.execute("SELECT * FROM t")[0], tuple)


def test_databases_are_independent():
    a, b = Database(), Database()
    a.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(SQLError):
        b.execute("SELECT * FROM t")


def test_trailing_semicolon_and_comments(db):
    db.execute("CREATE TABLE t (x INTEGER);")
    db.execute("INSERT INTO t VALUES (1); -- comment")
    assert db.execute("/* hi */ SELECT x FROM t -- trailing\n;") == [(1,)]


def test_case_insensitive_keywords_and_identifiers(pair):
    pair.run("create TABLE MixedCase (Col_A integer, colB Text)")
    pair.run("InSeRt InTo mixedcase (COL_A, COLB) VaLuEs (1, 'a'), (2, 'B')")
    pair.check("SeLeCt col_a, COLB FrOm MIXEDCASE m WhErE M.Col_a >= 1 OrDeR bY COL_A dEsC")
    pair.check("SELECT count(*), SUM(col_a), Max(colb) FROM mixedcase")


def test_insert_with_column_list_fills_nulls(pair):
    pair.run("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    pair.run("INSERT INTO t (c, a) VALUES (1.5, 1), (NULL, 2)")
    pair.run("INSERT INTO t (b) VALUES ('only b')")
    pair.check("SELECT * FROM t")


def test_insert_expressions(pair):
    pair.run("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    pair.run("INSERT INTO t VALUES (1 + 2, 'x' || 'y', 7 / 2), (-5, NULL, -1.5 * 2)")
    pair.check("SELECT * FROM t")


def test_type_affinity_on_insert(pair):
    pair.run("CREATE TABLE t (i INTEGER, r REAL, s TEXT)")
    pair.run(
        "INSERT INTO t VALUES (1, 1, 1), (2.0, 2.5, 2.5), ('3', '3', '3'), ('4.0', '4e1', 100.0)",
        "INSERT INTO t VALUES (NULL, NULL, NULL), ('1e2', '.5', -0.0), (' 7 ', ' 8 ', 1e20)",
    )
    pair.check("SELECT i, typeof(i), r, typeof(r), s, typeof(s) FROM t")


def test_update(pair):
    pair.run(
        "CREATE TABLE t (id INTEGER, v INTEGER, s TEXT)",
        "INSERT INTO t VALUES (1, 10, 'a'), (2, 20, 'b'), (3, NULL, 'c'), (4, 40, NULL)",
    )
    pair.run("UPDATE t SET v = v + 1 WHERE v > 15")
    pair.check("SELECT * FROM t")
    pair.run("UPDATE t SET v = id, id = v")  # all right-hand sides see the old row
    pair.check("SELECT * FROM t")
    pair.run("UPDATE t SET s = s || '!', v = v * 2.5 WHERE s IS NOT NULL")
    pair.check("SELECT id, v, typeof(v), s FROM t")
    pair.run("UPDATE t SET s = 'none' WHERE NULL")
    pair.check("SELECT * FROM t")
    pair.run("UPDATE t SET v = '12'")
    pair.check("SELECT v, typeof(v) FROM t")


def test_delete(pair):
    pair.run(
        "CREATE TABLE t (id INTEGER, v INTEGER)",
        "INSERT INTO t VALUES (1, 10), (2, NULL), (3, 30), (4, 40)",
    )
    pair.run("DELETE FROM t WHERE v > 25")
    pair.check("SELECT * FROM t")
    pair.run("DELETE FROM t WHERE v IS NULL OR NULL")
    pair.check("SELECT * FROM t")
    pair.run("DELETE FROM t")
    pair.check("SELECT * FROM t")
    pair.check("SELECT count(*), sum(v) FROM t")


def test_drop_and_create_if_not_exists(db):
    db.execute("CREATE TABLE t (x INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS t (y TEXT)")
    db.execute("INSERT INTO t VALUES (1)")
    db.execute("DROP TABLE t")
    db.execute("DROP TABLE IF EXISTS t")
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM t")


def test_failed_insert_is_atomic(db):
    db.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1), (2, 3)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1), (nosuch)")
    assert db.execute("SELECT * FROM t") == []


ERRORS = [
    # invalid SQL
    "SELEC 1",
    "SELECT",
    "SELECT * FROM",
    "SELECT 1 +",
    "SELECT (1",
    "SELECT 'unterminated",
    "SELECT 1 2 3",
    "SELECT * FROM emp WHERE",
    "SELECT * FROM emp ORDER",
    "CREATE TABLE",
    "INSERT INTO emp VALUES",
    "SELECT 1; SELECT 2",
    "SELECT @",
    "SELECT 12abc",
    "UPDATE emp SET",
    "DELETE emp",
    # unknown tables and columns
    "SELECT * FROM nosuch",
    "SELECT nosuch FROM emp",
    "SELECT emp.nosuch FROM emp",
    "SELECT x.id FROM emp",
    "SELECT emp.id FROM emp e",
    "SELECT x.* FROM emp",
    "SELECT * FROM emp WHERE nosuch = 1",
    "SELECT * FROM emp ORDER BY nosuch",
    "SELECT dept FROM emp GROUP BY nosuch",
    "INSERT INTO nosuch VALUES (1)",
    "INSERT INTO emp (nosuch) VALUES (1)",
    "UPDATE emp SET nosuch = 1",
    "UPDATE nosuch SET a = 1",
    "DELETE FROM nosuch",
    "SELECT e.id FROM emp e JOIN dept d ON e.dept = d.nosuch",
    "SELECT * FROM emp e JOIN dept d ON e.dept = x.code",
    # ambiguous column names
    "SELECT id FROM emp a JOIN emp b ON a.id = b.boss",
    "SELECT * FROM emp a JOIN emp b ON id = boss",
    "SELECT a.id FROM emp a JOIN emp b ON a.id = b.id WHERE name = 'x'",
    "SELECT a.id FROM emp a JOIN emp b ON a.id = b.id ORDER BY name",
    # wrong arity and misuse
    "INSERT INTO emp VALUES (1, 2)",
    "INSERT INTO emp (id, name) VALUES (1)",
    "SELECT * FROM emp WHERE count(*) > 1",
    "SELECT sum(count(*)) FROM emp",
    "SELECT dept FROM emp GROUP BY count(*)",
    "SELECT count(*) AS c FROM emp WHERE c > 1",
    "SELECT sum(*) FROM emp",
    "SELECT nosuchfunc(1)",
    "SELECT name FROM emp ORDER BY 5",
    "SELECT name FROM emp ORDER BY 0",
    "CREATE TABLE emp (x INTEGER)",
    "CREATE TABLE t (a INTEGER, A TEXT)",
    "SELECT *",
]


@pytest.mark.parametrize("sql", ERRORS)
def test_errors_raise_sqlerror(sample, sql):
    with pytest.raises(SQLError):
        sample.db.execute(sql)
    # sanity check: sqlite rejects these too
    with pytest.raises((sqlite3.Error, sqlite3.Warning)):
        sample.lite.execute(sql).fetchall()


@pytest.mark.parametrize("sql", ["", "   ", ";", "-- only a comment"])
def test_empty_statement_is_an_error(db, sql):
    with pytest.raises(SQLError):
        db.execute(sql)


def test_error_does_not_break_database(sample):
    with pytest.raises(SQLError):
        sample.db.execute("SELECT nosuch FROM emp")
    sample.check("SELECT count(*) FROM emp")


def test_sqlerror_is_exception():
    assert issubclass(SQLError, Exception)


def test_qualified_names_disambiguate(sample):
    sample.check("SELECT a.id, b.id FROM emp a JOIN emp b ON a.boss = b.id ORDER BY a.id")
    sample.check("SELECT a.name FROM emp a JOIN emp b ON a.id = b.id WHERE a.name LIKE 'a%'")


def test_alias_hides_table_name(sample):
    with pytest.raises(SQLError):
        sample.db.execute("SELECT emp.id FROM emp AS e")


def test_string_escapes_and_unicode(pair):
    pair.run("CREATE TABLE t (s TEXT)", "INSERT INTO t VALUES ('it''s'), ('naïve ☃'), ('')")
    pair.check("SELECT s, length(s) FROM t ORDER BY s")
    pair.check("SELECT s FROM t WHERE s LIKE 'NAÏVE%'")
    pair.check("SELECT s FROM t WHERE s LIKE 'na_ve%'")


def test_quoted_identifiers(pair):
    pair.run('CREATE TABLE "my table" ("select" INTEGER, [b c] TEXT)')
    pair.run("INSERT INTO \"my table\" VALUES (1, 'x')")
    pair.check('SELECT "select", [b c] FROM "my table"')
