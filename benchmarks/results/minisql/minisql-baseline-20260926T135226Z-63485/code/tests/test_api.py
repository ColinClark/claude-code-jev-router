"""Public API, statement handling and error reporting."""

import pytest

from minisql import Database, SQLError


def test_public_api_types(db):
    assert db.execute("CREATE TABLE t (a INTEGER, b REAL, c TEXT)") == []
    assert db.execute("INSERT INTO t VALUES (1, 2.5, 'x'), (NULL, NULL, NULL)") == []
    rows = db.execute("SELECT a, b, c FROM t ORDER BY a")
    assert rows == [(None, None, None), (1, 2.5, "x")]
    assert all(isinstance(r, tuple) for r in rows)
    assert type(rows[1][0]) is int and type(rows[1][1]) is float and type(rows[1][2]) is str


def test_non_select_statements_return_empty_list(db):
    assert db.execute("CREATE TABLE t (a INTEGER)") == []
    assert db.execute("INSERT INTO t VALUES (1)") == []
    assert db.execute("UPDATE t SET a = 2") == []
    assert db.execute("DELETE FROM t") == []
    assert db.execute("SELECT * FROM t") == []


def test_insert_with_column_list_leaves_others_null(db):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    db.execute("INSERT INTO t (c, a) VALUES (1.5, 7), (2, 8)")
    assert db.execute("SELECT * FROM t ORDER BY a") == [(7, None, 1.5), (8, None, 2.0)]


def test_column_affinity_on_insert_and_update(db):
    db.execute("CREATE TABLE t (i INTEGER, r REAL, s TEXT)")
    db.execute("INSERT INTO t VALUES ('12', 3, 4.5)")
    db.execute("INSERT INTO t VALUES (2.0, '1e2', 10)")
    assert db.execute("SELECT * FROM t ORDER BY i") == [(2, 100.0, "10"), (12, 3.0, "4.5")]
    db.execute("UPDATE t SET s = i * 2, r = i WHERE i = 2")
    assert db.execute("SELECT * FROM t WHERE i = 2") == [(2, 2.0, "4")]


def test_keywords_and_identifiers_case_insensitive(db):
    db.execute("create table Things (Id integer, Label text)")
    db.execute("INSERT into THINGS (ID, label) values (1, 'a')")
    assert db.execute("SeLeCt things.ID, LABEL FrOm thINGS WHERE id = 1") == [(1, "a")]
    assert db.execute('SELECT "Label" FROM "things"') == [("a",)]


def test_trailing_semicolon_and_comments(db):
    db.execute("CREATE TABLE t (a INTEGER); ")
    db.execute("INSERT INTO t VALUES (1) -- comment")
    assert db.execute("/* hi */ SELECT a FROM t;") == [(1,)]


def test_string_literal_escape(db):
    assert db.execute("SELECT 'it''s', ''''") == [("it's", "'")]


def test_update_uses_old_values(db):
    db.execute("CREATE TABLE t (a INTEGER, b INTEGER)")
    db.execute("INSERT INTO t VALUES (1, 2)")
    db.execute("UPDATE t SET a = b, b = a")
    assert db.execute("SELECT a, b FROM t") == [(2, 1)]


def test_delete_with_and_without_where(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1), (2), (3), (NULL)")
    db.execute("DELETE FROM t WHERE a >= 2")
    assert sorted(db.execute("SELECT a FROM t"), key=repr) == [(1,), (None,)]
    db.execute("DELETE FROM t")
    assert db.execute("SELECT count(*) FROM t") == [(0,)]


def test_databases_are_independent():
    a, b = Database(), Database()
    a.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(SQLError):
        b.execute("SELECT * FROM t")


def test_drop_table(db):
    db.execute("CREATE TABLE t (x INTEGER)")
    db.execute("DROP TABLE t")
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM t")
    db.execute("DROP TABLE IF EXISTS t")


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "SELEC 1",
        "SELECT",
        "SELECT FROM t",
        "SELECT a FROM",
        "SELECT a FROM t WHERE",
        "SELECT (a FROM t",
        "SELECT a FROM t ORDER a",
        "SELECT 'unterminated FROM t",
        "SELECT a FROM t; SELECT a FROM t",
        "INSERT INTO t VALUES",
        "INSERT INTO t VALUES (1, 2",
        "CREATE TABLE u ()",
        "UPDATE t SET WHERE a = 1",
        "DELETE t",
        "SELECT a FROM t LIMIT",
        "SELECT a b c FROM t",
        "SELECT 1 +",
        "SELECT a FROM t GROUP a",
        "SELECT a NOT FROM t",
        "SELECT a FROM t WHERE a BETWEEN 1",
        "SELECT a FROM t JOIN u",
        "SELECT a FROM t @",
        "SELECT 12abc",
    ],
)
def test_syntax_errors_raise_sqlerror(db, sql):
    db.execute("CREATE TABLE t (a INTEGER, b INTEGER)")
    with pytest.raises(SQLError):
        db.execute(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM missing",
        "SELECT nope FROM t",
        "SELECT t.nope FROM t",
        "SELECT u.a FROM t",
        "SELECT t.a FROM t AS x",
        "SELECT a FROM t x JOIN t y ON x.a = y.a",
        "SELECT x.a FROM t x JOIN t x ON 1",
        "SELECT a FROM t JOIN u ON t.a = u.a",
        "SELECT * FROM t WHERE nope = 1",
        "SELECT a FROM t ORDER BY nope",
        "SELECT a FROM t GROUP BY nope",
        "SELECT a FROM t ORDER BY 2",
        "SELECT a FROM t ORDER BY 0",
        "SELECT a FROM t GROUP BY 3",
        "SELECT x.* FROM t",
        "SELECT *",
        "INSERT INTO missing VALUES (1)",
        "INSERT INTO t VALUES (1)",
        "INSERT INTO t VALUES (1, 2, 3)",
        "INSERT INTO t (a, nope) VALUES (1, 2)",
        "INSERT INTO t (a) VALUES (1, 2)",
        "INSERT INTO t VALUES (a, 1)",
        "UPDATE t SET nope = 1",
        "UPDATE t SET a = nope",
        "UPDATE missing SET a = 1",
        "DELETE FROM missing",
        "DELETE FROM t WHERE nope",
        "CREATE TABLE t (x INTEGER)",
        "CREATE TABLE v (x INTEGER, X TEXT)",
        "SELECT a FROM t WHERE count(*) > 1",
        "SELECT a FROM t GROUP BY count(*)",
        "SELECT sum(count(*)) FROM t",
        "SELECT a FROM t HAVING a > 1",
        "SELECT a FROM t ORDER BY sum(a)",
        "SELECT nosuchfunc(a) FROM t",
        "SELECT sum(*) FROM t",
        "SELECT sum(a, b) FROM t",
        "SELECT a FROM t LIMIT 1.5",
        "SELECT a FROM t LIMIT 'x'",
        "INSERT INTO t VALUES (sum(1), 2)",
        "UPDATE t SET a = count(*)",
    ],
)
def test_semantic_errors_raise_sqlerror(both, sql):
    both.run("CREATE TABLE t (a INTEGER, b INTEGER)", "CREATE TABLE u (a INTEGER)")
    both.check_error(sql)


def test_error_messages(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("CREATE TABLE u (a INTEGER)")
    with pytest.raises(SQLError, match="no such table: missing"):
        db.execute("SELECT * FROM missing")
    with pytest.raises(SQLError, match="no such column: b"):
        db.execute("SELECT b FROM t")
    with pytest.raises(SQLError, match="ambiguous column name: a"):
        db.execute("SELECT a FROM t, u")


def test_sqlerror_is_exception():
    assert issubclass(SQLError, Exception)


def test_failed_insert_is_atomic(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1), (nope)")
    assert db.execute("SELECT count(*) FROM t") == [(0,)]


def test_sum_integer_overflow_raises(both):
    both.run(
        "CREATE TABLE t (a INTEGER)",
        "INSERT INTO t VALUES (9223372036854775807), (1)",
    )
    both.check_error("SELECT sum(a) FROM t")
    both.check("SELECT total(a), avg(a) FROM t")


def test_large_join_uses_reasonable_time(db):
    db.execute("CREATE TABLE a (id INTEGER, v TEXT)")
    db.execute("CREATE TABLE b (id INTEGER, w INTEGER)")
    db.execute("INSERT INTO a VALUES " + ", ".join(f"({i}, 'v{i % 7}')" for i in range(3000)))
    db.execute("INSERT INTO b VALUES " + ", ".join(f"({i % 1500}, {i})" for i in range(3000)))
    rows = db.execute(
        "SELECT a.v, count(b.id) FROM a LEFT JOIN b ON a.id = b.id GROUP BY a.v ORDER BY a.v"
    )
    assert sum(n for _, n in rows) == 3000


def test_deeply_nested_expressions(both):
    both.check("SELECT " + " + ".join(["1"] * 900))
    both.check("SELECT " + "(" * 200 + "1" + ")" * 200)
    with pytest.raises(SQLError):
        both.db.execute("SELECT " + "(" * 5000 + "1" + ")" * 5000)
