import pytest

from minisql import Database, SQLError


def test_string_literal_escaping(dual):
    dual.run("CREATE TABLE t (s TEXT)")
    dual.run("INSERT INTO t VALUES ('it''s a test')")
    dual.query("SELECT s FROM t")


def test_empty_string_literal(dual):
    dual.run("CREATE TABLE t (s TEXT)")
    dual.run("INSERT INTO t VALUES ('')")
    dual.query("SELECT s FROM t")


def test_in_with_empty_list(dual):
    dual.run("CREATE TABLE t (a INTEGER)")
    dual.run("INSERT INTO t VALUES (1), (2)")
    dual.query("SELECT a FROM t WHERE a IN ()")


def test_not_in_with_empty_list(dual):
    dual.run("CREATE TABLE t (a INTEGER)")
    dual.run("INSERT INTO t VALUES (1), (2)")
    dual.query("SELECT a FROM t WHERE a NOT IN ()")


def test_self_join(dual):
    dual.run("CREATE TABLE emp (id INTEGER, manager_id INTEGER, name TEXT)")
    dual.run(
        "INSERT INTO emp VALUES (1, NULL, 'boss'), (2, 1, 'alice'), (3, 1, 'bob')"
    )
    dual.query(
        "SELECT e.name, m.name FROM emp e LEFT JOIN emp m ON e.manager_id = m.id"
    )


def test_where_uses_column_from_joined_table(dual):
    dual.run("CREATE TABLE a (id INTEGER, val INTEGER)")
    dual.run("CREATE TABLE b (id INTEGER, val INTEGER)")
    dual.run("INSERT INTO a VALUES (1, 10), (2, 20)")
    dual.run("INSERT INTO b VALUES (1, 100), (2, 200)")
    dual.query(
        "SELECT a.val, b.val FROM a JOIN b ON a.id = b.id WHERE b.val > 100"
    )


def test_group_by_expression(dual):
    dual.run("CREATE TABLE t (a INTEGER)")
    dual.run("INSERT INTO t VALUES (1), (2), (3), (4), (5)")
    dual.query("SELECT a % 2, COUNT(*) FROM t GROUP BY a % 2")


def test_like_underscore_and_percent(dual):
    dual.run("CREATE TABLE t (s TEXT)")
    dual.run("INSERT INTO t VALUES ('cat'), ('cats'), ('car'), ('dog')")
    dual.query("SELECT s FROM t WHERE s LIKE 'ca_'")
    dual.query("SELECT s FROM t WHERE s LIKE 'ca%'")
    dual.query("SELECT s FROM t WHERE s LIKE '_a_'")


def test_between_strings(dual):
    dual.run("CREATE TABLE t (s TEXT)")
    dual.run("INSERT INTO t VALUES ('apple'), ('banana'), ('cherry')")
    dual.query("SELECT s FROM t WHERE s BETWEEN 'apple' AND 'banana'")


def test_limit_zero(dual):
    dual.run("CREATE TABLE t (a INTEGER)")
    dual.run("INSERT INTO t VALUES (1), (2), (3)")
    dual.query("SELECT a FROM t LIMIT 0")


def test_limit_larger_than_rows(dual):
    dual.run("CREATE TABLE t (a INTEGER)")
    dual.run("INSERT INTO t VALUES (1), (2)")
    dual.query("SELECT a FROM t ORDER BY a LIMIT 100", ordered=True)


def test_where_false_excludes_all_rows(dual):
    dual.run("CREATE TABLE t (a INTEGER)")
    dual.run("INSERT INTO t VALUES (1), (2)")
    dual.query("SELECT a FROM t WHERE 1 = 0")


def test_where_null_excludes_all_rows(dual):
    dual.run("CREATE TABLE t (a INTEGER)")
    dual.run("INSERT INTO t VALUES (1), (2)")
    dual.query("SELECT a FROM t WHERE NULL")


def test_multiple_statements_share_state(db: Database):
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1)")
    db.execute("INSERT INTO t VALUES (2)")
    assert db.execute("SELECT COUNT(*) FROM t") == [(2,)]


def test_select_returns_tuples_not_lists(db: Database):
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1)")
    result = db.execute("SELECT a FROM t")
    assert isinstance(result, list)
    assert isinstance(result[0], tuple)


def test_semicolon_terminated_statement(db: Database):
    db.execute("CREATE TABLE t (a INTEGER);")
    db.execute("INSERT INTO t VALUES (1);")
    assert db.execute("SELECT a FROM t;") == [(1,)]


def test_error_on_malformed_sql(db: Database):
    with pytest.raises(SQLError):
        db.execute("CREATE TALBE t (a INTEGER)")


def test_error_on_double_from(db: Database):
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM t FROM t")


def test_where_between_and_in_combo(dual):
    dual.run("CREATE TABLE t (a INTEGER)")
    dual.run("INSERT INTO t VALUES (1), (2), (3), (4), (5)")
    dual.query(
        "SELECT a FROM t WHERE a BETWEEN 2 AND 4 AND a NOT IN (3)"
    )


def test_order_by_then_group_by_count_desc(dual):
    dual.run("CREATE TABLE t (k TEXT, v INTEGER)")
    dual.run(
        "INSERT INTO t VALUES ('a', 1), ('a', 2), ('b', 3), ('c', 4), ('c', 5), ('c', 6)"
    )
    dual.query("SELECT k, COUNT(*) c FROM t GROUP BY k ORDER BY c DESC, k", ordered=True)
