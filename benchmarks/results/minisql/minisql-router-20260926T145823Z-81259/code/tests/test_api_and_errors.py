import pytest

from minisql import Database, SQLError


def test_public_api():
    db = Database()
    assert db.execute("CREATE TABLE t (a INTEGER, b REAL, c TEXT)") == []
    assert db.execute("INSERT INTO t VALUES (1, 2, 3)") == []
    assert db.execute("SELECT * FROM t") == [(1, 2.0, "3")]
    assert db.execute("UPDATE t SET a = 5") == []
    assert db.execute("DELETE FROM t WHERE a = 1") == []
    assert db.execute("SELECT a FROM t;") == [(5,)]


def test_databases_are_independent():
    one, two = Database(), Database()
    one.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        two.execute("SELECT * FROM t")


def test_column_types_are_enforced_on_storage():
    db = Database()
    db.execute("CREATE TABLE t (i INTEGER, r REAL, s TEXT)")
    db.execute("INSERT INTO t VALUES (1.0, 1, 1), ('7', '2.5', 2.5), (NULL, NULL, NULL)")
    db.execute("INSERT INTO t (s) VALUES ('x')")
    assert db.execute("SELECT i, r, s FROM t") == [
        (1, 1.0, "1"),
        (7, 2.5, "2.5"),
        (None, None, None),
        (None, None, "x"),
    ]
    assert [type(v) for v in db.execute("SELECT i, r, s FROM t")[0]] == [int, float, str]


def test_string_escape_and_case_insensitivity():
    db = Database()
    db.execute("create TABLE Things (Name text, QTY Integer)")
    db.execute("INSERT INTO things (NAME, qty) VALUES ('it''s', 3)")
    assert db.execute("SELECT THINGS.name, Qty FROM ThInGs") == [("it's", 3)]
    assert db.execute("SELECT t.NAME FROM things AS T") == [("it's",)]


def test_update_uses_old_values():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER, b INTEGER)")
    db.execute("INSERT INTO t VALUES (1, 2)")
    db.execute("UPDATE t SET a = b, b = a")
    assert db.execute("SELECT a, b FROM t") == [(2, 1)]


def test_statement_failure_leaves_table_unchanged():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1), (2, 3)")
    assert db.execute("SELECT * FROM t") == []


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "SELEC * FROM t",
        "SELECT * FROM",
        "SELECT * FROM t WHERE",
        "SELECT a FROM t ORDER",
        "SELECT (a FROM t",
        "SELECT a, FROM t",
        "SELECT 'unterminated FROM t",
        "SELECT a FROM t LIMIT",
        "SELECT a FROM t extra garbage here",
        "SELECT a FROM t; SELECT b FROM t",
        "INSERT INTO t VALUES",
        "INSERT INTO t VALUES (1, 2, 3, 4)",
        "INSERT INTO t (a, b) VALUES (1)",
        "INSERT INTO t (nope) VALUES (1)",
        "INSERT INTO t VALUES (a, 1, 'x')",
        "CREATE TABLE t (a INTEGER)",
        "CREATE TABLE u (a INTEGER, A TEXT)",
        "CREATE TABLE u ()",
        "UPDATE t SET nope = 1",
        "UPDATE t SET a = nope",
        "UPDATE missing SET a = 1",
        "DELETE FROM missing",
        "DELETE FROM t WHERE nope = 1",
        "SELECT * FROM missing",
        "SELECT nope FROM t",
        "SELECT t.nope FROM t",
        "SELECT x.a FROM t",
        "SELECT a FROM t JOIN u ON t.a = u.a",
        "SELECT t.a FROM t JOIN u ON t.a = u.nope",
        "SELECT a FROM t t1 JOIN t t2 ON t1.a = t2.a",
        "SELECT a FROM t WHERE COUNT(*) > 1",
        "SELECT a FROM t GROUP BY COUNT(*)",
        "SELECT SUM(COUNT(a)) FROM t",
        "SELECT nosuchfunc(a) FROM t",
        "SELECT SUM(a, b) FROM t",
        "SELECT COUNT() FROM t",
        "SELECT a FROM t ORDER BY 5",
        "SELECT a FROM t ORDER BY nope",
        "SELECT a FROM t LIMIT 'x'",
        "SELECT u.* FROM t",
        "SELECT a FROM t LEFT JOIN u",
        "SELECT a FROM t WHERE a IN (SELECT a FROM u)",
        "SELECT 1 +",
        "SELECT a FROM t WHERE a = 1 AND",
        "SELECT * FROM t WHERE a BETWEEN 1",
        "SELECT a b c FROM t",
        "SELECT 3abc FROM t",
        "SELECT a ! b FROM t",
    ],
)
def test_errors(sql):
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    db.execute("CREATE TABLE u (a INTEGER, d TEXT)")
    with pytest.raises(SQLError):
        db.execute(sql)


def test_sqlerror_is_exception():
    assert issubclass(SQLError, Exception)


def test_left_join_unmatched_rows_are_null_padded():
    db = Database()
    db.execute("CREATE TABLE l (id INTEGER, v TEXT)")
    db.execute("CREATE TABLE r (id INTEGER, w REAL)")
    db.execute("INSERT INTO l VALUES (1, 'a'), (2, 'b'), (NULL, 'c')")
    db.execute("INSERT INTO r VALUES (1, 1.5), (1, 2.5)")
    rows = db.execute("SELECT l.v, r.w FROM l LEFT JOIN r ON l.id = r.id ORDER BY l.v, r.w")
    assert rows == [("a", 1.5), ("a", 2.5), ("b", None), ("c", None)]
    assert db.execute("SELECT * FROM l LEFT JOIN r ON l.id = r.id WHERE r.id IS NULL") == [
        (2, "b", None, None),
        (None, "c", None, None),
    ]


def test_aggregates_over_empty_input():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    assert db.execute("SELECT COUNT(*), COUNT(a), SUM(a), AVG(a), MIN(a), MAX(a) FROM t") == [
        (0, 0, None, None, None, None)
    ]
    assert db.execute("SELECT a, COUNT(*) FROM t GROUP BY a") == []


def test_drop_table():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("DROP TABLE t")
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM t")
    db.execute("DROP TABLE IF EXISTS t")
    db.execute("CREATE TABLE IF NOT EXISTS t (a INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS t (a INTEGER)")
