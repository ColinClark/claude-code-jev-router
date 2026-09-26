from minisql import Database, SQLError

from .conftest import assert_matches_sqlite


def test_create_and_insert_returns_empty_lists():
    db = Database()
    assert db.execute("CREATE TABLE t (id INTEGER, name TEXT)") == []
    assert db.execute("INSERT INTO t VALUES (1, 'a')") == []


def test_insert_multiple_rows():
    setup = [
        "CREATE TABLE t (id INTEGER, name TEXT)",
        "INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'c')",
    ]
    assert_matches_sqlite(setup, "SELECT * FROM t ORDER BY id")


def test_insert_with_explicit_columns_and_omitted_defaults_to_null():
    setup = [
        "CREATE TABLE t (id INTEGER, name TEXT, score REAL)",
        "INSERT INTO t (id, name) VALUES (1, 'a')",
    ]
    assert_matches_sqlite(setup, "SELECT * FROM t")


def test_insert_column_order_independent():
    setup = [
        "CREATE TABLE t (id INTEGER, name TEXT)",
        "INSERT INTO t (name, id) VALUES ('a', 1)",
    ]
    assert_matches_sqlite(setup, "SELECT * FROM t")


def test_update_sets_values():
    setup = [
        "CREATE TABLE t (id INTEGER, score INTEGER)",
        "INSERT INTO t VALUES (1, 10), (2, 20)",
        "UPDATE t SET score = score + 1 WHERE id = 1",
    ]
    assert_matches_sqlite(setup, "SELECT * FROM t ORDER BY id")


def test_update_without_where_affects_all_rows():
    setup = [
        "CREATE TABLE t (id INTEGER, score INTEGER)",
        "INSERT INTO t VALUES (1, 10), (2, 20)",
        "UPDATE t SET score = 0",
    ]
    assert_matches_sqlite(setup, "SELECT * FROM t ORDER BY id")


def test_delete_with_where():
    setup = [
        "CREATE TABLE t (id INTEGER)",
        "INSERT INTO t VALUES (1), (2), (3)",
        "DELETE FROM t WHERE id = 2",
    ]
    assert_matches_sqlite(setup, "SELECT * FROM t ORDER BY id")


def test_delete_without_where_clears_table():
    setup = [
        "CREATE TABLE t (id INTEGER)",
        "INSERT INTO t VALUES (1), (2), (3)",
        "DELETE FROM t",
    ]
    assert_matches_sqlite(setup, "SELECT * FROM t")


def test_update_and_execute_return_empty():
    db = Database()
    db.execute("CREATE TABLE t (id INTEGER)")
    db.execute("INSERT INTO t VALUES (1)")
    assert db.execute("UPDATE t SET id = 2") == []
    assert db.execute("DELETE FROM t") == []


def test_duplicate_table_raises():
    db = Database()
    db.execute("CREATE TABLE t (id INTEGER)")
    try:
        db.execute("CREATE TABLE t (id INTEGER)")
        assert False, "expected SQLError"
    except SQLError:
        pass


def test_insert_into_unknown_table_raises():
    db = Database()
    try:
        db.execute("INSERT INTO nope VALUES (1)")
        assert False, "expected SQLError"
    except SQLError:
        pass


def test_insert_wrong_arity_raises():
    db = Database()
    db.execute("CREATE TABLE t (id INTEGER, name TEXT)")
    try:
        db.execute("INSERT INTO t VALUES (1)")
        assert False, "expected SQLError"
    except SQLError:
        pass
