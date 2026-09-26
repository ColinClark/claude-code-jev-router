"""CREATE / INSERT / UPDATE / DELETE behaviour."""

import pytest

from minisql import Database


def test_insert_with_column_list_and_omitted_columns(pair):
    pair.run(
        "CREATE TABLE t (a INTEGER, b TEXT, c REAL)",
        "INSERT INTO t (c, a) VALUES (1, 2), (3.5, NULL)",
        "INSERT INTO t (b) VALUES ('only b')",
        "INSERT INTO t VALUES (-1, 'x', 0)",
    )
    pair.query("SELECT a, b, c FROM t")


def test_insert_expressions(pair):
    pair.run(
        "CREATE TABLE t (a INTEGER, b TEXT)",
        "INSERT INTO t VALUES (1 + 2 * 3, 'a' || 'b'), (-7 / 2, NULL || 'x'), (10 % 4, 1 < 2)",
    )
    pair.query("SELECT a, b FROM t")


def test_update_all_rows(pair):
    pair.run(*_seed(), "UPDATE t SET v = v * 2")
    pair.query("SELECT id, v, s FROM t")


def test_update_with_where_and_multiple_assignments(pair):
    pair.run(*_seed(), "UPDATE t SET v = v + 100, s = s || '!' WHERE id > 2 AND v IS NOT NULL")
    pair.query("SELECT id, v, s FROM t")


def test_update_uses_old_values(pair):
    pair.run(*_seed(), "UPDATE t SET id = v, v = id WHERE v IS NOT NULL")
    pair.query("SELECT id, v, s FROM t")


def test_update_where_null_matches_nothing(pair):
    pair.run(*_seed(), "UPDATE t SET s = 'changed' WHERE v = NULL")
    pair.query("SELECT id, v, s FROM t")


def test_update_to_null(pair):
    pair.run(*_seed(), "UPDATE t SET v = NULL WHERE s LIKE 'B%'")
    pair.query("SELECT id, v, s FROM t")


def test_delete_with_where(pair):
    pair.run(*_seed(), "DELETE FROM t WHERE v < 20 OR v IS NULL")
    pair.query("SELECT id, v, s FROM t")


def test_delete_all(pair):
    pair.run(*_seed(), "DELETE FROM t")
    pair.query("SELECT COUNT(*), SUM(v) FROM t")


def test_delete_where_null_keeps_rows(pair):
    pair.run(*_seed(), "DELETE FROM t WHERE NULL")
    pair.query("SELECT COUNT(*) FROM t")


def test_insert_after_delete(pair):
    pair.run(*_seed(), "DELETE FROM t WHERE id = 1", "INSERT INTO t VALUES (9, 90, 'z')")
    pair.query("SELECT id, v, s FROM t ORDER BY id")


def test_create_if_not_exists_and_drop(pair):
    pair.run(
        "CREATE TABLE t (a INTEGER)",
        "CREATE TABLE IF NOT EXISTS t (b TEXT)",
        "INSERT INTO t VALUES (1)",
    )
    pair.query("SELECT * FROM t")
    pair.run("DROP TABLE t", "DROP TABLE IF EXISTS t", "CREATE TABLE t (b TEXT)")
    pair.query("SELECT * FROM t")


def test_non_select_returns_empty_list():
    db = Database()
    assert db.execute("CREATE TABLE t (a INTEGER)") == []
    assert db.execute("INSERT INTO t VALUES (1)") == []
    assert db.execute("UPDATE t SET a = 2") == []
    assert db.execute("DELETE FROM t;") == []


def test_identifiers_are_case_insensitive(pair):
    pair.run(
        "CREATE TABLE MixedCase (ColA INTEGER, colb TEXT)",
        "insert into mixedcase (COLA, COLB) values (1, 'x')",
        "UPDATE MIXEDCASE SET cola = ColA + 1",
    )
    pair.query('SELECT mixedcase.COLA, "colB", [ColA] FROM MIXEDcase')


def test_comments_and_quoted_identifiers(pair):
    pair.run(
        'CREATE TABLE "my table" ("select" INTEGER, `from` TEXT)',
        "INSERT INTO \"my table\" VALUES (1, 'a') -- trailing comment",
    )
    pair.query('SELECT "select", /* inline */ "from" FROM "my table"')


@pytest.mark.parametrize("sql", ["SELECT 'it''s'", "SELECT '' || ''", "SELECT 'a''''b'"])
def test_string_escapes(pair, sql):
    pair.query(sql)


def _seed():
    return (
        "CREATE TABLE t (id INTEGER, v INTEGER, s TEXT)",
        (
            "INSERT INTO t VALUES (1, 10, 'Alpha'), (2, 20, 'beta'), (3, NULL, 'Beta'), "
            "(4, 40, NULL), (5, 5, 'gamma')"
        ),
    )
