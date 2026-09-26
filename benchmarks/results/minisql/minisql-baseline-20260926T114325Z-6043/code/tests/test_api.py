import pytest

from minisql import Database, SQLError


@pytest.fixture
def db():
    d = Database()
    d.execute("CREATE TABLE t (a INTEGER, b REAL, c TEXT)")
    return d


def test_non_select_statements_return_empty_list(db):
    assert db.execute("INSERT INTO t VALUES (1, 2.0, 'x')") == []
    assert db.execute("UPDATE t SET a = 2") == []
    assert db.execute("DELETE FROM t WHERE a = 5") == []
    assert db.execute("CREATE TABLE u (x INTEGER)") == []


def test_select_returns_list_of_tuples(db):
    db.execute("INSERT INTO t VALUES (1, 2.5, 'x'), (2, NULL, NULL)")
    rows = db.execute("SELECT a, b, c FROM t ORDER BY a")
    assert rows == [(1, 2.5, "x"), (2, None, None)]
    assert all(isinstance(r, tuple) for r in rows)


def test_insert_with_column_list_fills_null(db):
    db.execute("INSERT INTO t (c, a) VALUES ('hi', 7)")
    assert db.execute("SELECT * FROM t") == [(7, None, "hi")]


def test_column_affinity_on_insert(db):
    db.execute("INSERT INTO t VALUES (3, 4, 5)")
    db.execute("INSERT INTO t VALUES ('12', '2.5', 1.5)")
    db.execute("INSERT INTO t VALUES (2.0, 1, 100)")
    rows = db.execute("SELECT a, b, c FROM t ORDER BY a")
    assert rows == [(2, 1.0, "100"), (3, 4.0, "5"), (12, 2.5, "1.5")]
    assert [type(v) for v in rows[0]] == [int, float, str]


def test_keywords_and_identifiers_case_insensitive(db):
    db.execute("insert into T (A, b, C) values (1, 1.5, 'q')")
    assert db.execute("SeLeCt t.A, T.c FrOm t WHERE A = 1") == [(1, "q")]


def test_update_uses_old_values(db):
    db.execute("INSERT INTO t VALUES (1, 10.0, 'x'), (2, 20.0, 'y')")
    db.execute("UPDATE t SET a = a + 10, b = a WHERE c = 'x'")
    assert db.execute("SELECT a, b FROM t ORDER BY a") == [(2, 20.0), (11, 1.0)]


def test_delete(db):
    db.execute("INSERT INTO t VALUES (1, 1.0, 'a'), (2, 2.0, 'b'), (3, NULL, 'c')")
    db.execute("DELETE FROM t WHERE b > 1")
    assert db.execute("SELECT a FROM t ORDER BY a") == [(1,), (3,)]
    db.execute("DELETE FROM t")
    assert db.execute("SELECT * FROM t") == []


def test_trailing_semicolon_and_comments(db):
    db.execute("INSERT INTO t VALUES (1, 1.0, 'a'); -- trailing comment")
    assert db.execute("SELECT /* inline */ a FROM t;") == [(1,)]


def test_string_escape(db):
    db.execute("INSERT INTO t (c) VALUES ('it''s')")
    assert db.execute("SELECT c FROM t") == [("it's",)]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM missing",
        "SELECT nope FROM t",
        "SELECT x.a FROM t",
        "SELEC a FROM t",
        "SELECT a FROM t WHERE",
        "SELECT a FROM t t1 JOIN t t2 ON t1.a = t2.a WHERE a = 1",
        "SELECT a FROM t t1, t t2",
        "INSERT INTO missing VALUES (1)",
        "INSERT INTO t VALUES (1, 2)",
        "INSERT INTO t (a, zz) VALUES (1, 2)",
        "INSERT INTO t VALUES (a, 1, 1)",
        "UPDATE t SET zz = 1",
        "UPDATE missing SET a = 1",
        "DELETE FROM missing",
        "DELETE FROM t WHERE zz = 1",
        "CREATE TABLE t (x INTEGER)",
        "SELECT a FROM t WHERE count(*) > 1",
        "SELECT count(sum(a)) FROM t",
        "SELECT nosuchfunc(a) FROM t",
        "SELECT a FROM t ORDER BY 5",
        "SELECT a FROM t GROUP BY 0",
        "SELECT 'unterminated",
        "SELECT a FROM t; SELECT a FROM t",
        "SELECT t.* FROM t AS x",
        "SELECT *",
        "SELECT a FROM t LIMIT 'x'",
        "",
    ],
)
def test_errors(db, sql):
    with pytest.raises(SQLError):
        db.execute(sql)


def test_alias_hides_table_name(db):
    db.execute("INSERT INTO t VALUES (1, 1.0, 'a')")
    assert db.execute("SELECT x.a FROM t AS x") == [(1,)]
    with pytest.raises(SQLError):
        db.execute("SELECT t.a FROM t AS x")


def test_failed_insert_is_atomic():
    db = Database()
    db.execute("CREATE TABLE k (id INTEGER PRIMARY KEY, v TEXT NOT NULL)")
    db.execute("INSERT INTO k VALUES (1, 'a')")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO k VALUES (2, 'b'), (1, 'dup')")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO k VALUES (3, NULL)")
    assert db.execute("SELECT * FROM k") == [(1, "a")]
    db.execute("INSERT INTO k (v) VALUES ('auto')")
    assert db.execute("SELECT id FROM k WHERE v = 'auto'") == [(2,)]


def test_select_without_from():
    assert Database().execute("SELECT 1 + 2, 'a' || 'b', 7 / 2") == [(3, "ab", 3)]


def test_drop_table(db):
    db.execute("DROP TABLE t")
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM t")
