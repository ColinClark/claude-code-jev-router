import pytest

from minisql import Database, SQLError


def test_create_and_select_empty(db: Database):
    result = db.execute("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    assert result == []
    assert db.execute("SELECT * FROM t") == []


def test_create_table_duplicate_name_errors(db: Database):
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("CREATE TABLE t (a INTEGER)")


def test_insert_returns_empty_list(db: Database):
    db.execute("CREATE TABLE t (a INTEGER)")
    assert db.execute("INSERT INTO t VALUES (1)") == []


def test_insert_positional_all_columns(db: Database):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    db.execute("INSERT INTO t VALUES (1, 'x'), (2, 'y')")
    assert db.execute("SELECT a, b FROM t ORDER BY a") == [(1, "x"), (2, "y")]


def test_insert_with_column_list_and_omitted_columns_null(db: Database):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    db.execute("INSERT INTO t (a) VALUES (1)")
    assert db.execute("SELECT a, b, c FROM t") == [(1, None, None)]


def test_insert_column_order_can_differ_from_table(db: Database):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    db.execute("INSERT INTO t (b, a) VALUES ('x', 1)")
    assert db.execute("SELECT a, b FROM t") == [(1, "x")]


def test_insert_value_count_mismatch_errors(db: Database):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1)")


def test_insert_unknown_column_errors(db: Database):
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t (nope) VALUES (1)")


def test_update_sets_values(db: Database):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    db.execute("INSERT INTO t VALUES (1, 'x'), (2, 'y')")
    result = db.execute("UPDATE t SET b = 'z' WHERE a = 1")
    assert result == []
    assert db.execute("SELECT a, b FROM t ORDER BY a") == [(1, "z"), (2, "y")]


def test_update_without_where_affects_all_rows(db: Database):
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1), (2), (3)")
    db.execute("UPDATE t SET a = a + 10")
    assert db.execute("SELECT a FROM t ORDER BY a") == [(11,), (12,), (13,)]


def test_update_uses_original_row_values_for_all_assignments(db: Database):
    db.execute("CREATE TABLE t (a INTEGER, b INTEGER)")
    db.execute("INSERT INTO t VALUES (1, 2)")
    db.execute("UPDATE t SET a = b, b = a")
    assert db.execute("SELECT a, b FROM t") == [(2, 1)]


def test_update_multiple_columns(db: Database):
    db.execute("CREATE TABLE t (a INTEGER, b INTEGER)")
    db.execute("INSERT INTO t VALUES (1, 1)")
    db.execute("UPDATE t SET a = 10, b = 20 WHERE a = 1")
    assert db.execute("SELECT a, b FROM t") == [(10, 20)]


def test_delete_with_where(db: Database):
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1), (2), (3)")
    result = db.execute("DELETE FROM t WHERE a >= 2")
    assert result == []
    assert db.execute("SELECT a FROM t ORDER BY a") == [(1,)]


def test_delete_without_where_clears_table(db: Database):
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1), (2)")
    db.execute("DELETE FROM t")
    assert db.execute("SELECT * FROM t") == []


def test_case_insensitive_keywords_and_identifiers(db: Database):
    db.execute("create TABLE T (A integer, B text)")
    db.execute("Insert Into t (a, b) VALUES (1, 'x')")
    assert db.execute("SELECT A, b FROM T") == [(1, "x")]


# -- Type affinity / coercion -------------------------------------------------


def _check_affinity(dual, create_sql, insert_sql, select_sql, expected_types):
    """Compare values+Python types from minisql against sqlite3's typeof()."""
    dual.run(create_sql)
    dual.run(insert_sql)
    mini_rows = dual.mini.execute(select_sql)
    sqlite_rows = dual.sql.execute(select_sql).fetchall()
    assert [tuple(v for v in r) for r in mini_rows] == sqlite_rows
    for row in mini_rows:
        for value, expected in zip(row, expected_types):
            assert type(value) is expected, (row, expected_types)


def test_integer_column_keeps_real_when_fractional(dual):
    _check_affinity(
        dual,
        "CREATE TABLE t (a INTEGER)",
        "INSERT INTO t VALUES (1.5)",
        "SELECT a FROM t",
        [float],
    )


def test_integer_column_converts_lossless_real(dual):
    _check_affinity(
        dual,
        "CREATE TABLE t (a INTEGER)",
        "INSERT INTO t VALUES (5.0)",
        "SELECT a FROM t",
        [int],
    )


def test_real_column_converts_integer_to_float(dual):
    _check_affinity(
        dual,
        "CREATE TABLE t (a REAL)",
        "INSERT INTO t VALUES (5)",
        "SELECT a FROM t",
        [float],
    )


def test_text_column_converts_numbers_to_text(dual):
    _check_affinity(
        dual,
        "CREATE TABLE t (a TEXT)",
        "INSERT INTO t VALUES (123)",
        "SELECT a FROM t",
        [str],
    )
    dual2 = type(dual)()
    _check_affinity(
        dual2,
        "CREATE TABLE t (a TEXT)",
        "INSERT INTO t VALUES (1.5)",
        "SELECT a FROM t",
        [str],
    )


def test_integer_column_non_numeric_text_stays_text(dual):
    _check_affinity(
        dual,
        "CREATE TABLE t (a INTEGER)",
        "INSERT INTO t VALUES ('3.2abc')",
        "SELECT a FROM t",
        [str],
    )


def test_integer_column_numeric_text_converts(dual):
    _check_affinity(
        dual,
        "CREATE TABLE t (a INTEGER)",
        "INSERT INTO t VALUES ('42')",
        "SELECT a FROM t",
        [int],
    )


def test_null_stays_null_regardless_of_type(db: Database):
    db.execute("CREATE TABLE t (a INTEGER, b REAL, c TEXT)")
    db.execute("INSERT INTO t VALUES (NULL, NULL, NULL)")
    assert db.execute("SELECT a, b, c FROM t") == [(None, None, None)]
