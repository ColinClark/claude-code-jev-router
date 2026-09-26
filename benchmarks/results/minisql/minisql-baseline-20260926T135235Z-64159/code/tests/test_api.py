import pytest

from minisql import Database, SQLError


def test_public_api(db):
    assert isinstance(db, Database)
    assert db.execute("CREATE TABLE t (a INTEGER, b TEXT)") == []
    assert db.execute("INSERT INTO t VALUES (1, 'x')") == []
    assert db.execute("SELECT a, b FROM t") == [(1, "x")]
    assert db.execute("UPDATE t SET a = 2") == []
    assert db.execute("DELETE FROM t WHERE a = 5") == []
    assert db.execute("SELECT * FROM t;") == [(2, "x")]


def test_databases_are_independent():
    a, b = Database(), Database()
    a.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(SQLError):
        b.execute("SELECT * FROM t")


def test_insert_column_list_and_omitted_columns(db):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    db.execute("INSERT INTO t (c, a) VALUES (1.5, 1), (2, 2)")
    assert db.execute("SELECT * FROM t ORDER BY a") == [(1, None, 1.5), (2, None, 2.0)]


def test_multi_row_insert(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1), (2), (3)")
    assert db.execute("SELECT count(*) FROM t") == [(3,)]


def test_column_types_are_enforced_by_affinity(db):
    db.execute("CREATE TABLE t (i INTEGER, r REAL, s TEXT)")
    db.execute("INSERT INTO t VALUES (1.0, 2, 3)")
    db.execute("INSERT INTO t VALUES ('12', '2.5', 4.5)")
    rows = db.execute("SELECT i, r, s FROM t")
    assert rows == [(1, 2.0, "3"), (12, 2.5, "4.5")]
    assert [type(v) for v in rows[0]] == [int, float, str]


def test_update_uses_old_values(db):
    db.execute("CREATE TABLE t (a INTEGER, b INTEGER)")
    db.execute("INSERT INTO t VALUES (1, 2)")
    db.execute("UPDATE t SET a = b, b = a")
    assert db.execute("SELECT a, b FROM t") == [(2, 1)]


def test_update_where_and_delete(db):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    db.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'c'), (NULL, 'd')")
    db.execute("UPDATE t SET b = b || '!' WHERE a >= 2")
    assert db.execute("SELECT b FROM t ORDER BY b") == [("a",), ("b!",), ("c!",), ("d",)]
    db.execute("DELETE FROM t WHERE a < 3")
    assert db.execute("SELECT b FROM t ORDER BY b") == [("c!",), ("d",)]
    db.execute("DELETE FROM t")
    assert db.execute("SELECT * FROM t") == []


def test_case_insensitive_keywords_and_identifiers(db):
    db.execute("create table MyTable (MyCol integer)")
    db.execute("INSERT into mytable (mycol) values (7)")
    assert db.execute("SeLeCt MYCOL from MYTABLE m where M.mycol = 7") == [(7,)]


def test_comments_and_quoted_identifiers(db):
    db.execute('CREATE TABLE "order" ("select" INTEGER)  -- reserved words')
    db.execute('INSERT INTO "order" VALUES (1) /* block */')
    assert db.execute('SELECT "select" FROM "order"') == [(1,)]


def test_string_escape(db):
    assert db.execute("SELECT 'it''s'") == [("it's",)]


@pytest.mark.parametrize(
    "sql",
    [
        "SELEC 1",
        "SELECT FROM t",
        "SELECT a FROM",
        "SELECT (1",
        "SELECT 'abc",
        "CREATE TABLE t2 (a INTEGER",
        "INSERT INTO t VALUES (1, 2, 3)",
        "INSERT INTO t (a, a) VALUES (1, 2)",
        "SELECT a FROM t WHERE",
        "SELECT a FROM t ORDER a",
        "SELECT 1; SELECT 2",
        "SELECT a FROM t LIMIT 'x'",
        "SELECT a b c FROM t",
        "",
    ],
)
def test_invalid_sql_raises(db, sql):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    with pytest.raises(SQLError):
        db.execute(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM missing",
        "INSERT INTO missing VALUES (1)",
        "UPDATE missing SET a = 1",
        "DELETE FROM missing",
        "SELECT * FROM t JOIN missing ON 1",
        "SELECT nope FROM t",
        "SELECT t.nope FROM t",
        "SELECT x.a FROM t",
        "SELECT a FROM t WHERE nope = 1",
        "SELECT a FROM t ORDER BY nope",
        "SELECT a FROM t GROUP BY nope",
        "INSERT INTO t (nope) VALUES (1)",
        "UPDATE t SET nope = 1",
        "UPDATE t SET a = nope",
        "DELETE FROM t WHERE nope",
        "SELECT x.* FROM t",
        "INSERT INTO t VALUES (a, 1)",
    ],
)
def test_unknown_names_raise(db, sql):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    db.execute("CREATE TABLE u (a INTEGER, c TEXT)")
    with pytest.raises(SQLError):
        db.execute(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t JOIN u ON t.a = u.a",
        "SELECT * FROM t JOIN u ON a = 1",
        "SELECT b FROM t JOIN u ON t.a = u.a WHERE a > 1",
        "SELECT t.b FROM t JOIN u ON 1 ORDER BY a",
        "SELECT x.a FROM t x JOIN t y ON 1 JOIN u x ON 1",
    ],
)
def test_ambiguous_columns_raise(db, sql):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    db.execute("CREATE TABLE u (a INTEGER, c TEXT)")
    with pytest.raises(SQLError):
        db.execute(sql)


def test_duplicate_table_raises(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("CREATE TABLE T (b TEXT)")


def test_aggregate_misuse_raises(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    for sql in [
        "SELECT a FROM t WHERE count(*) > 1",
        "SELECT sum(count(*)) FROM t",
        "SELECT a FROM t GROUP BY count(*)",
        "SELECT a FROM t HAVING a > 1",
        "SELECT nosuchfunc(a) FROM t",
        "SELECT sum(*) FROM t",
    ]:
        with pytest.raises(SQLError):
            db.execute(sql)


def test_failed_insert_is_atomic(db):
    db.execute("CREATE TABLE t (a INTEGER, b INTEGER)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1, 2), (3)")
    assert db.execute("SELECT * FROM t") == []
