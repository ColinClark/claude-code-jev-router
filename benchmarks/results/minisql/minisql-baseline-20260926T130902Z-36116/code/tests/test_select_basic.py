from .conftest import assert_matches_sqlite

SETUP = [
    "CREATE TABLE t (id INTEGER, name TEXT, score REAL)",
    """INSERT INTO t VALUES
        (1, 'Alice', 90.0),
        (2, 'Bob', NULL),
        (3, 'Carl', 70.5),
        (4, 'Dana', 90.0)
    """,
]


def test_select_star():
    assert_matches_sqlite(SETUP, "SELECT * FROM t ORDER BY id")


def test_select_columns_with_alias():
    assert_matches_sqlite(SETUP, "SELECT name AS n, score AS s FROM t ORDER BY id")


def test_select_expression_alias():
    assert_matches_sqlite(SETUP, "SELECT id, score * 2 AS doubled FROM t ORDER BY id")


def test_where_filters_rows():
    assert_matches_sqlite(SETUP, "SELECT name FROM t WHERE score > 80 ORDER BY name")


def test_where_with_null_excludes_rows():
    assert_matches_sqlite(SETUP, "SELECT name FROM t WHERE score = 90.0 ORDER BY name")


def test_order_by_desc():
    assert_matches_sqlite(SETUP, "SELECT name FROM t ORDER BY score DESC, name ASC")


def test_order_by_nulls_first_by_default_asc():
    assert_matches_sqlite(SETUP, "SELECT name, score FROM t ORDER BY score")


def test_order_by_nulls_last_desc():
    assert_matches_sqlite(SETUP, "SELECT name, score FROM t ORDER BY score DESC")


def test_order_by_alias():
    assert_matches_sqlite(SETUP, "SELECT name, score * 2 AS s2 FROM t ORDER BY s2 DESC")


def test_limit():
    assert_matches_sqlite(SETUP, "SELECT name FROM t ORDER BY id LIMIT 2")


def test_limit_offset():
    assert_matches_sqlite(SETUP, "SELECT name FROM t ORDER BY id LIMIT 2 OFFSET 1")


def test_limit_zero():
    assert_matches_sqlite(SETUP, "SELECT name FROM t ORDER BY id LIMIT 0")


def test_distinct():
    assert_matches_sqlite(SETUP, "SELECT DISTINCT score FROM t ORDER BY score")


def test_distinct_multi_column():
    setup = [
        "CREATE TABLE t (a INTEGER, b INTEGER)",
        "INSERT INTO t VALUES (1,1), (1,1), (1,2), (2,1)",
    ]
    assert_matches_sqlite(setup, "SELECT DISTINCT a, b FROM t ORDER BY a, b")


def test_table_alias():
    assert_matches_sqlite(SETUP, "SELECT t2.name FROM t AS t2 WHERE t2.id = 1")


def test_table_alias_without_as():
    assert_matches_sqlite(SETUP, "SELECT t2.name FROM t t2 WHERE t2.id = 1")
