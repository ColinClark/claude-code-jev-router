"""DDL/DML statements, type affinity and the public API."""

import pathlib

import pytest

from minisql import Database, SQLError


def test_public_api_types():
    db = Database()
    assert db.execute("CREATE TABLE t (a INTEGER, b TEXT)") == []
    assert db.execute("INSERT INTO t VALUES (1, 'x'), (2, NULL)") == []
    assert db.execute("UPDATE t SET b = 'y' WHERE a = 2") == []
    rows = db.execute("SELECT a, b FROM t ORDER BY a")
    assert rows == [(1, "x"), (2, "y")]
    assert all(type(r) is tuple for r in rows)
    assert db.execute("DELETE FROM t WHERE a = 1") == []
    assert db.execute("SELECT * FROM t") == [(2, "y")]
    assert issubclass(SQLError, Exception)


def test_comparison_results_are_ints_not_bools():
    db = Database()
    row = db.execute("SELECT 1 = 1, 1 < 0, NOT 0, 1 AND 1, 0 OR 1, 1 IN (1), 'a' LIKE 'A'")[0]
    assert row == (1, 0, 1, 1, 1, 1, 1)
    assert all(type(v) is int for v in row)


def test_databases_are_independent():
    a, b = Database(), Database()
    a.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(SQLError):
        b.execute("SELECT * FROM t")


def test_no_sqlite_in_implementation():
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "minisql"
    for path in src.rglob("*.py"):
        text = path.read_text()
        assert "sqlite3" not in text, path
        assert "import sqlite" not in text, path


AFFINITY_VALUES = [
    "1", "2.0", "2.5", "-3.0", "'12'", "' 7 '", "'2.0'", "'2.5'", "'1e3'", "'abc'", "''",
    "'0x10'", "'12abc'", "1e20", "'1e20'", "NULL", "0.1", "'-4'", "'+5'", "'.5'", "'5.'",
    "9223372036854775807", "'9223372036854775808'", "1.5e-7", "100.0", "-0.0",
]


@pytest.mark.parametrize("value", AFFINITY_VALUES)
def test_insert_affinity(pair, value):
    pair.exec(
        "CREATE TABLE a (i INTEGER, r REAL, t TEXT, n NUMERIC, b)",
        f"INSERT INTO a VALUES ({value}, {value}, {value}, {value}, {value})",
    )
    pair.query("SELECT i, r, t, n, b, typeof(i), typeof(r), typeof(t), typeof(n) FROM a")


@pytest.mark.parametrize("value", AFFINITY_VALUES)
def test_update_affinity(pair, value):
    pair.exec(
        "CREATE TABLE a (i INTEGER, r REAL, t TEXT, n NUMERIC, b)",
        "INSERT INTO a VALUES (0, 0, 0, 0, 0)",
        f"UPDATE a SET i = {value}, r = {value}, t = {value}, n = {value}, b = {value}",
    )
    pair.query("SELECT i, r, t, n, b FROM a")


def test_affinity_from_expressions(pair):
    pair.exec(
        "CREATE TABLE a (i INTEGER, r REAL, t TEXT)",
        "INSERT INTO a VALUES (7 / 2.0, 3 * 2, 1.0 / 4), ('4' || '2', '1' || '.5', 10 / 4)",
    )
    pair.query("SELECT i, r, t FROM a")


def test_insert_column_list_and_defaults(pair):
    pair.exec(
        "CREATE TABLE t (a INTEGER, b TEXT, c REAL DEFAULT 1.5, d INTEGER DEFAULT -1)",
        "INSERT INTO t (b, a) VALUES ('x', 1), ('y', 2)",
        "INSERT INTO t (c) VALUES (3)",
        "INSERT INTO t VALUES (4, 'z', NULL, NULL)",
        "INSERT INTO t (A, B, C, D) VALUES ('5', 5, '5', 5.0)",
    )
    pair.query("SELECT * FROM t")


def test_insert_select(pair):
    pair.exec(
        "CREATE TABLE src (a INTEGER, b TEXT)",
        "CREATE TABLE dst (x TEXT, y INTEGER)",
        "INSERT INTO src VALUES (1, '10'), (2, '20'), (3, 'abc')",
        "INSERT INTO dst SELECT a, b FROM src WHERE a > 1",
        "INSERT INTO dst (y) SELECT a * 100 FROM src",
    )
    pair.query("SELECT * FROM dst")


def test_update_statements(sample):
    sample.exec("UPDATE emp SET salary = salary * 1.1 WHERE dept = 10")
    sample.tables_equal("emp")
    sample.exec("UPDATE emp SET name = upper(name), boss = NULL WHERE boss IS NOT NULL AND id > 4")
    sample.tables_equal("emp")
    sample.exec("UPDATE emp SET id = id + 100, dept = id")  # assignments use old values
    sample.tables_equal("emp")
    sample.exec("UPDATE emp SET salary = '123'")
    sample.tables_equal("emp")
    sample.exec("UPDATE emp SET dept = 1 WHERE NULL")
    sample.tables_equal("emp")
    sample.exec("UPDATE dept SET budget = budget / 3, dname = dname || '-' || id")
    sample.tables_equal("dept")


def test_delete_statements(sample):
    sample.exec("DELETE FROM emp WHERE salary < 4500")
    sample.tables_equal("emp")
    sample.exec("DELETE FROM emp WHERE dept IS NULL OR name LIKE 'e%'")
    sample.tables_equal("emp")
    sample.exec("DELETE FROM emp WHERE NULL")
    sample.tables_equal("emp")
    sample.exec("DELETE FROM proj")
    sample.tables_equal("proj")
    sample.query("SELECT COUNT(*) FROM proj")


def test_create_drop(pair):
    pair.exec(
        "CREATE TABLE t (a INTEGER)",
        "CREATE TABLE IF NOT EXISTS t (b TEXT)",
        "INSERT INTO t VALUES (1)",
        "DROP TABLE t",
        "DROP TABLE IF EXISTS t",
        "CREATE TABLE t (a TEXT, b REAL)",
        "INSERT INTO t VALUES (1, 2)",
    )
    pair.query("SELECT a, b FROM t")


def test_not_null_constraint():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER NOT NULL, b TEXT)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t (b) VALUES ('x')")
    db.execute("INSERT INTO t VALUES (1, 'x')")
    with pytest.raises(SQLError):
        db.execute("UPDATE t SET a = NULL")
    assert db.execute("SELECT * FROM t") == [(1, "x")]


def test_failed_insert_is_atomic():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER NOT NULL)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1), (NULL), (3)")
    assert db.execute("SELECT COUNT(*) FROM t") == [(0,)]


def test_keywords_case_insensitive(pair):
    pair.exec(
        "create table T (A integer, B text)",
        "Insert Into t VALUES (1, 'a'), (2, 'b')",
        "update T set b = 'c' where A = 2",
    )
    pair.query("SeLeCt a, B fRoM t WhErE a >= 1 OrDeR bY A dEsC LiMiT 5 oFfSeT 0")
    pair.query("select Count(*), SUM(a), mAx(b) from t group BY b having COUNT(*) > 0 order by 1")
    pair.exec("delete FROM t where a = 1")
    pair.query("select * from T")
