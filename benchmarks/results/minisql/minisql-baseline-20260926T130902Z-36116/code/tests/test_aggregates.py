from .conftest import assert_matches_sqlite

SETUP = [
    "CREATE TABLE t (id INTEGER, cat TEXT, val INTEGER, r REAL)",
    """INSERT INTO t VALUES
        (1, 'a', 10, 1.5),
        (2, 'a', 20, 2.5),
        (3, 'b', 30, NULL),
        (4, 'b', NULL, 4.5),
        (5, 'c', NULL, NULL)
    """,
]


def test_count_star():
    assert_matches_sqlite(SETUP, "SELECT COUNT(*) FROM t")


def test_count_expr_ignores_null():
    assert_matches_sqlite(SETUP, "SELECT COUNT(val) FROM t")


def test_count_distinct():
    assert_matches_sqlite(SETUP, "SELECT COUNT(DISTINCT cat) FROM t")


def test_sum_avg_min_max():
    assert_matches_sqlite(SETUP, "SELECT SUM(val), AVG(val), MIN(val), MAX(val) FROM t")


def test_aggregates_over_empty_table():
    setup = ["CREATE TABLE t (id INTEGER, val INTEGER)"]
    assert_matches_sqlite(
        setup, "SELECT COUNT(*), COUNT(val), SUM(val), AVG(val), MIN(val), MAX(val) FROM t"
    )


def test_group_by_single_column():
    assert_matches_sqlite(
        SETUP, "SELECT cat, COUNT(*), SUM(val) FROM t GROUP BY cat ORDER BY cat"
    )


def test_group_by_with_having():
    assert_matches_sqlite(
        SETUP,
        "SELECT cat, COUNT(*) AS c FROM t GROUP BY cat HAVING COUNT(*) > 1 ORDER BY cat",
    )


def test_group_by_having_on_sum():
    assert_matches_sqlite(
        SETUP,
        "SELECT cat, SUM(val) AS total FROM t GROUP BY cat HAVING SUM(val) > 15 ORDER BY cat",
    )


def test_group_by_empty_table_yields_no_rows():
    setup = ["CREATE TABLE t (cat TEXT, val INTEGER)"]
    assert_matches_sqlite(setup, "SELECT cat, COUNT(*) FROM t GROUP BY cat")


def test_group_by_order_by_aggregate():
    assert_matches_sqlite(
        SETUP,
        "SELECT cat, SUM(val) AS total FROM t GROUP BY cat ORDER BY total DESC, cat",
    )


def test_group_by_null_groups_together():
    assert_matches_sqlite(
        SETUP, "SELECT val, COUNT(*) FROM t GROUP BY val ORDER BY val"
    )


def test_sum_returns_int_when_all_int():
    setup = [
        "CREATE TABLE t (val INTEGER)",
        "INSERT INTO t VALUES (1), (2), (3)",
    ]
    result = assert_matches_sqlite(setup, "SELECT SUM(val) FROM t")
    assert isinstance(result[0][0], int)


def test_sum_returns_float_when_real_present():
    setup = [
        "CREATE TABLE t (val REAL)",
        "INSERT INTO t VALUES (1), (2), (3)",
    ]
    result = assert_matches_sqlite(setup, "SELECT SUM(val) FROM t")
    assert isinstance(result[0][0], float)


def test_avg_is_float():
    setup = [
        "CREATE TABLE t (val INTEGER)",
        "INSERT INTO t VALUES (1), (2), (4)",
    ]
    result = assert_matches_sqlite(setup, "SELECT AVG(val) FROM t")
    assert isinstance(result[0][0], float)


def test_group_by_multiple_columns():
    setup = [
        "CREATE TABLE t (a INTEGER, b INTEGER, val INTEGER)",
        "INSERT INTO t VALUES (1,1,10), (1,1,20), (1,2,30), (2,1,40)",
    ]
    assert_matches_sqlite(
        setup, "SELECT a, b, SUM(val) FROM t GROUP BY a, b ORDER BY a, b"
    )


def test_group_by_expression():
    setup = [
        "CREATE TABLE t (val INTEGER)",
        "INSERT INTO t VALUES (1), (2), (3), (4), (5), (6)",
    ]
    assert_matches_sqlite(
        setup, "SELECT val % 2, COUNT(*) FROM t GROUP BY val % 2 ORDER BY val % 2"
    )
