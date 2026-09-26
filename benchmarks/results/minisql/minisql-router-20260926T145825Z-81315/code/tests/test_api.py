import pytest

from minisql import Database, SQLError


def test_public_api():
    db = Database()
    assert db.execute("CREATE TABLE t (a INTEGER)") == []
    assert db.execute("INSERT INTO t VALUES (1), (2)") == []
    assert db.execute("UPDATE t SET a = a + 1") == []
    assert sorted(db.execute("SELECT a FROM t")) == [(2,), (3,)]
    assert db.execute("DELETE FROM t WHERE a = 2") == []
    assert db.execute("SELECT * FROM t") == [(3,)]


def test_rows_are_tuples_of_python_types():
    db = Database()
    db.execute("CREATE TABLE t (i INTEGER, r REAL, s TEXT)")
    db.execute("INSERT INTO t VALUES (1, 2.5, 'x'), (NULL, NULL, NULL)")
    rows = db.execute("SELECT i, r, s FROM t ORDER BY i")
    assert rows == [(None, None, None), (1, 2.5, "x")]
    assert type(rows[1][0]) is int and type(rows[1][1]) is float and type(rows[1][2]) is str


def test_storage_affinity_matches_declared_type():
    db = Database()
    db.execute("CREATE TABLE t (i INTEGER, r REAL, s TEXT)")
    db.execute("INSERT INTO t VALUES (3.0, 1, 4), ('12', '2.5', 1.5)")
    assert db.execute("SELECT i, r, s FROM t ORDER BY i") == [(3, 1.0, "4"), (12, 2.5, "1.5")]


def test_keywords_and_identifiers_case_insensitive():
    db = Database()
    db.execute("create TABLE MyTable (MyCol integer)")
    db.execute("insert into mytable (MYCOL) values (7)")
    assert db.execute("SeLeCt mycol FROM MYTABLE WhErE MyTable.MYCOL = 7") == [(7,)]


def test_insert_with_column_list_leaves_others_null():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    db.execute("INSERT INTO t (c, a) VALUES (1.5, 1), (2.5, 2)")
    assert db.execute("SELECT a, b, c FROM t ORDER BY a") == [(1, None, 1.5), (2, None, 2.5)]


def test_update_uses_old_values():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER, b INTEGER)")
    db.execute("INSERT INTO t VALUES (1, 2)")
    db.execute("UPDATE t SET a = b, b = a")
    assert db.execute("SELECT a, b FROM t") == [(2, 1)]


def test_tables_are_independent_per_database():
    a, b = Database(), Database()
    a.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(SQLError):
        b.execute("SELECT * FROM t")


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "SELEC 1",
        "SELECT",
        "SELECT * FROM",
        "SELECT a FROM t WHERE",
        "SELECT a b c FROM t",
        "SELECT (a FROM t",
        "SELECT a FROM t ORDER a",
        "SELECT 'unterminated FROM t",
        "SELECT a FROM t; SELECT a FROM t",
        "INSERT INTO t VALUES (1, 2, 3, 4)",
        "INSERT INTO t (a) VALUES (1, 2)",
        "INSERT INTO t (nope) VALUES (1)",
        "CREATE TABLE t (x INTEGER)",
        "CREATE TABLE u (x INTEGER, X TEXT)",
        "SELECT * FROM missing",
        "SELECT nope FROM t",
        "SELECT t.nope FROM t",
        "SELECT zz.a FROM t",
        "SELECT a FROM t JOIN u ON t.a = u.a",
        "SELECT a FROM t AS x JOIN t AS y ON x.a = y.a",
        "SELECT t.a FROM t AS x",
        "UPDATE t SET nope = 1",
        "UPDATE missing SET a = 1",
        "DELETE FROM missing",
        "DELETE FROM t WHERE nope = 1",
        "SELECT a FROM t WHERE count(*) > 1",
        "SELECT count(max(a)) FROM t",
        "SELECT nosuchfunc(a) FROM t",
        "SELECT a FROM t ORDER BY 5",
        "SELECT 1abc",
        "SELECT a FROM t GROUP BY count(*)",
        "SELECT x.* FROM t",
        "SELECT * ",
    ],
)
def test_errors_raise_sqlerror(sql):
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    db.execute("CREATE TABLE u (a INTEGER, d TEXT)")
    with pytest.raises(SQLError):
        db.execute(sql)


def test_errors_on_empty_table_still_detected():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("SELECT b FROM t")
    with pytest.raises(SQLError):
        db.execute("SELECT a FROM t WHERE b = 1")


def test_failed_insert_is_atomic():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1), (2, 3)")
    assert db.execute("SELECT * FROM t") == []


def test_sqlerror_is_exception():
    assert issubclass(SQLError, Exception)
