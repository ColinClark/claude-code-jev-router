"""DDL/DML statements, type affinity and the public API."""

import pytest

from minisql import Database, SQLError


def test_public_api(db):
    assert db.execute("CREATE TABLE t (a INTEGER, b TEXT)") == []
    assert db.execute("INSERT INTO t VALUES (1, 'x'), (2, 'y');") == []
    assert db.execute("SELECT a, b FROM t ORDER BY a") == [(1, "x"), (2, "y")]
    assert db.execute("UPDATE t SET b = 'z' WHERE a = 2") == []
    assert db.execute("DELETE FROM t WHERE a = 1") == []
    assert db.execute("select * from T;") == [(2, "z")]
    assert issubclass(SQLError, Exception)


def test_databases_are_independent():
    a, b = Database(), Database()
    a.execute("CREATE TABLE t (x INTEGER)")
    b.execute("CREATE TABLE t (x INTEGER)")
    a.execute("INSERT INTO t VALUES (1)")
    assert b.execute("SELECT * FROM t") == []


def test_case_insensitive_keywords_and_identifiers(pair):
    pair.run(
        "create table MixedCase (Col1 integer, COL2 text)",
        "InSeRt InTo mixedcase (col1, Col2) VaLuEs (1, 'a'), (2, 'b')",
    )
    pair.check("SeLeCt COL1, col2 FrOm MIXEDCASE WhErE cOl1 > 1")
    pair.check('SELECT "Col1", mixedcase.col2 FROM MixedCase ORDER BY 1')


@pytest.mark.parametrize(
    "value",
    [
        "1", "2.0", "2.5", "-3.0", "'4'", "'4.0'", "'4.5'", "' 7 '", "'1e2'", "'abc'", "''",
        "'0x10'", "NULL", "1e20", "9223372036854775807", "9223372036854775808", "'12abc'",
        "-0.0", "'-5'", "'+5'", "'.5'", "'5.'", "1e-3", "'9223372036854775808'",
    ],
)
def test_insert_affinity(pair, value):
    pair.run(
        "CREATE TABLE t (i INTEGER, r REAL, t TEXT, n NUMERIC, b)",
        f"INSERT INTO t VALUES ({value}, {value}, {value}, {value}, {value})",
    )
    pair.check("SELECT i, r, t, n, b FROM t")
    pair.check("SELECT typeof(i), typeof(r), typeof(t), typeof(n), typeof(b) FROM t")


def test_declared_type_variants(pair):
    pair.run(
        "CREATE TABLE t (a INT, b BIGINT, c VARCHAR(10), d DOUBLE, e FLOAT, f DECIMAL(5,2), "
        "g BOOLEAN, h CHARACTER(3))",
        "INSERT INTO t VALUES ('1', '2.0', 3, '4', 5, '6.0', '7', 8.5)",
    )
    pair.check("SELECT * FROM t")


def test_update_affinity_and_old_row_semantics(pair):
    pair.run(
        "CREATE TABLE t (id INTEGER, a INTEGER, b REAL, c TEXT)",
        "INSERT INTO t VALUES (1, 1, 1.5, 'x'), (2, 2, 2.5, 'y'), (3, NULL, NULL, NULL)",
        "UPDATE t SET a = b * 2, b = a, c = a || c WHERE id <= 2",
    )
    pair.check("SELECT * FROM t ORDER BY id")
    pair.run("UPDATE t SET a = a + 1, c = 5")
    pair.check("SELECT * FROM t ORDER BY id")
    pair.run("UPDATE t SET a = '7.0', b = '8', c = 9.5 WHERE a IS NULL")
    pair.check("SELECT * FROM t ORDER BY id")
    pair.run("UPDATE t SET a = 100 WHERE 0")
    pair.check("SELECT * FROM t ORDER BY id")


def test_update_swap(pair):
    pair.run(
        "CREATE TABLE t (a INTEGER, b INTEGER)",
        "INSERT INTO t VALUES (1, 2), (3, 4)",
        "UPDATE t SET a = b, b = a",
    )
    pair.check("SELECT * FROM t")


def test_delete(pair):
    pair.run(
        "CREATE TABLE t (a INTEGER, b TEXT)",
        "INSERT INTO t VALUES (1, 'a'), (2, NULL), (3, 'c'), (NULL, 'd')",
        "DELETE FROM t WHERE b IS NULL OR a > 2",
    )
    pair.check("SELECT * FROM t")
    pair.run("DELETE FROM t WHERE a = NULL")
    pair.check("SELECT * FROM t")
    pair.run("DELETE FROM t")
    pair.check("SELECT * FROM t")
    pair.check("SELECT COUNT(*) FROM t")


def test_insert_column_list_and_missing_columns(pair):
    pair.run(
        "CREATE TABLE t (a INTEGER, b TEXT, c REAL)",
        "INSERT INTO t (c, a) VALUES (1, 2), (3.5, NULL)",
        "INSERT INTO t (b) VALUES ('only b')",
    )
    pair.check("SELECT * FROM t")


def test_insert_expressions(pair):
    pair.run(
        "CREATE TABLE t (a INTEGER, b TEXT, c REAL)",
        "INSERT INTO t VALUES (1 + 2 * 3, 'a' || 'b', 7 / 2), (-(5), upper('x'), 1 / 0)",
    )
    pair.check("SELECT * FROM t")


def test_insert_select(pair):
    pair.run(
        "CREATE TABLE src (a INTEGER, b TEXT)",
        "INSERT INTO src VALUES (1, '10'), (2, '20'), (3, 'x')",
        "CREATE TABLE dst (x REAL, y INTEGER)",
        "INSERT INTO dst SELECT a, b FROM src WHERE a < 3",
        "INSERT INTO dst (y) SELECT a * 10 FROM src",
    )
    pair.check("SELECT * FROM dst")


def test_trailing_semicolon_and_comments(pair):
    pair.run("CREATE TABLE t (a INTEGER);", "INSERT INTO t VALUES (1); -- trailing comment")
    pair.check("SELECT /* inline */ a FROM t ;")


def test_create_if_not_exists_and_drop(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS t (b TEXT)")
    db.execute("INSERT INTO t VALUES (1)")
    assert db.execute("SELECT * FROM t") == [(1,)]
    db.execute("DROP TABLE t")
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM t")
    db.execute("DROP TABLE IF EXISTS t")


def test_column_constraints_are_accepted(pair):
    pair.run(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL, v REAL DEFAULT 0)",
        "INSERT INTO t VALUES (1, 'a', 2)",
    )
    pair.check("SELECT * FROM t")


def test_failed_insert_is_atomic(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1), (nosuchcol)")
    assert db.execute("SELECT * FROM t") == []


def test_negative_zero(pair):
    pair.run(
        "CREATE TABLE t (id INTEGER, r REAL, b)",
        "INSERT INTO t VALUES (1, 0.0, -0.0), (2, -0.0, 0.0)",
    )
    pair.check("SELECT id, r, b, -r, -b, r * -1 FROM t ORDER BY id")


def test_unicode_text_roundtrip(pair):
    pair.run(
        "CREATE TABLE t (s TEXT)",
        "INSERT INTO t VALUES ('héllo'), ('日本'), ('a''b'), (''), ('Z'), ('a')",
    )
    pair.check("SELECT s FROM t ORDER BY s")
    pair.check("SELECT s, length(s) FROM t WHERE s LIKE '%L%'")
