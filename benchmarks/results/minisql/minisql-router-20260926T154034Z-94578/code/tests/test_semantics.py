"""Targeted checks of SQLite behaviors: types, NULLs, arithmetic, LIKE, ordering, aggregates."""

import pytest

from minisql import Database

from .conftest import typed


def test_public_api():
    db = Database()
    assert db.execute("CREATE TABLE t (a INTEGER, b REAL, c TEXT)") == []
    assert db.execute("INSERT INTO t VALUES (1, 2.5, 'x'), (NULL, NULL, NULL)") == []
    assert db.execute("SELECT * FROM t ORDER BY a") == [(None, None, None), (1, 2.5, "x")]
    assert db.execute("UPDATE t SET a = 2 WHERE a IS NULL") == []
    assert db.execute("DELETE FROM t WHERE a = 1") == []
    assert db.execute("SELECT a, b, c FROM t") == [(2, None, None)]


def test_omitted_columns_are_null(db):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    db.execute("INSERT INTO t (c, a) VALUES (1.5, 1)")
    assert db.execute("SELECT * FROM t") == [(1, None, 1.5)]


def test_databases_are_independent():
    a, b = Database(), Database()
    a.execute("CREATE TABLE t (x INTEGER)")
    b.execute("CREATE TABLE t (x INTEGER)")
    a.execute("INSERT INTO t VALUES (1)")
    assert b.execute("SELECT * FROM t") == []


@pytest.mark.parametrize(
    "value, column_type",
    [
        ("3.0", "INTEGER"),
        ("'12'", "INTEGER"),
        ("' 4 '", "INTEGER"),
        ("'1e3'", "INTEGER"),
        ("2", "REAL"),
        ("'1.5'", "REAL"),
        ("5", "TEXT"),
        ("1.0", "TEXT"),
        ("1e19", "TEXT"),
        ("'abc'", "INTEGER"),
        ("2.5", "INTEGER"),
        ("9223372036854775807.0", "INTEGER"),
    ],
)
def test_storage_affinity(pair, value, column_type):
    pair.exec(f"CREATE TABLE t (c {column_type})", f"INSERT INTO t VALUES ({value})")
    pair.check("SELECT c, typeof(c) FROM t")


def test_update_applies_affinity(pair):
    pair.exec(
        "CREATE TABLE t (i INTEGER, r REAL, s TEXT)",
        "INSERT INTO t VALUES (1, 1.0, 'a')",
        "UPDATE t SET i = 7.0, r = 3, s = 4.5",
    )
    pair.check("SELECT i, r, s FROM t")


@pytest.mark.parametrize(
    "expr",
    [
        "(0.1 + 0.2) || ''",
        "1e15 || ''",
        "1e16 || ''",
        "1e17 || ''",
        "123456789012345.6 || ''",
        "1e-4 || ''",
        "1e-5 || ''",
        "-2.5e30 || ''",
        "100.0 || ''",
        "(1.0 / 3) || ''",
        "-0.0 || ''",
        "1e308 * 10 || ''",
        "LENGTH(1.5)",
        "UPPER(2.0)",
        "2.0 LIKE '2.0'",
    ],
)
def test_real_to_text(pair, expr):
    pair.check(f"SELECT {expr}")


@pytest.mark.parametrize(
    "expr",
    [
        "7 / 2",
        "-7 / 2",
        "7 / -2",
        "7.0 / 2",
        "7 / 0",
        "7.0 / 0",
        "7 / 0.0",
        "7 % 3",
        "-7 % 3",
        "7 % -3",
        "5.5 % 2",
        "-5.5 % 2",
        "5 % 0",
        "5 % 0.5",
        "9223372036854775807 + 1",
        "-9223372036854775808 - 1",
        "-9223372036854775808",
        "-(-9223372036854775808)",
        "9223372036854775808",
        "-9223372036854775808 / -1",
        "4611686018427387904 * 2",
        "'12abc' + 1",
        "'abc' * 3",
        "'1.5x' + 1",
        "'1e2' + 0",
        "NULL + 1",
        "NULL / 0",
        "- NULL",
        "- 'abc'",
        "1 || 2",
        "'a' || NULL",
    ],
)
def test_arithmetic(pair, expr):
    pair.check(f"SELECT {expr}")


@pytest.mark.parametrize(
    "expr",
    [
        "'abc' LIKE 'ABC'",
        "'ABC' LIKE 'a%'",
        "'é' LIKE 'É'",
        "'éa' LIKE '_a'",
        "'a\nb' LIKE 'a_b'",
        "'a.c' LIKE 'a.c'",
        "'abc' LIKE 'a.c'",
        "'a+c' LIKE 'a+c'",
        "'' LIKE '%'",
        "'x' LIKE ''",
        "'[a]' LIKE '[a]'",
        "'100%' LIKE '100%'",
        "'abc' NOT LIKE 'abc'",
        "NULL NOT LIKE 'a'",
    ],
)
def test_like(pair, expr):
    pair.check(f"SELECT {expr}")


def test_null_ordering(pair):
    pair.exec(
        "CREATE TABLE t (a INTEGER, b TEXT)",
        "INSERT INTO t VALUES (3, 'c'), (NULL, 'n'), (1, NULL), (2, 'B'), (NULL, NULL)",
    )
    pair.check("SELECT a FROM t ORDER BY a")
    pair.check("SELECT a FROM t ORDER BY a DESC")
    pair.check("SELECT b FROM t ORDER BY b")
    pair.check("SELECT b FROM t ORDER BY b DESC")
    pair.check("SELECT a, b FROM t ORDER BY a DESC, b ASC")


def test_mixed_type_ordering(pair):
    pair.exec(
        "CREATE TABLE t (v TEXT, w INTEGER)",
        "INSERT INTO t (w) VALUES (1), (NULL), (2), (-5)",
        "INSERT INTO t (v) VALUES ('b'), ('a'), ('B'), ('10'), ('9')",
    )
    pair.check("SELECT v, w FROM t ORDER BY v, w")
    pair.check("SELECT COALESCE(v, w) AS k FROM t ORDER BY k")
    pair.check("SELECT COALESCE(v, w) AS k FROM t ORDER BY k DESC")
    pair.check("SELECT MIN(COALESCE(v, w)), MAX(COALESCE(v, w)) FROM t")


def test_aggregates_on_empty_table(pair):
    pair.exec("CREATE TABLE t (a INTEGER, b REAL)")
    pair.check(
        "SELECT COUNT(*), COUNT(a), COUNT(DISTINCT a), SUM(a), AVG(a), MIN(a), MAX(a), "
        "TOTAL(b), SUM(b) FROM t"
    )
    pair.check("SELECT a, COUNT(*) FROM t GROUP BY a")
    pair.check("SELECT COUNT(*) FROM t HAVING COUNT(*) = 0")


def test_aggregates_all_null(pair):
    pair.exec("CREATE TABLE t (a INTEGER)", "INSERT INTO t VALUES (NULL), (NULL)")
    pair.check("SELECT COUNT(*), COUNT(a), SUM(a), AVG(a), MIN(a), MAX(a), TOTAL(a) FROM t")


def test_sum_types(pair):
    pair.exec(
        "CREATE TABLE t (i INTEGER, r REAL)",
        "INSERT INTO t VALUES (1, 0.1), (2, 0.2), (3, 0.3), (NULL, NULL)",
    )
    pair.check("SELECT SUM(i), AVG(i), SUM(r), AVG(r), SUM(i + r), TOTAL(i) FROM t")


def test_sum_integer_overflow_switches(pair):
    pair.exec(
        "CREATE TABLE t (i INTEGER)",
        "INSERT INTO t VALUES (9223372036854775807), (-10), (1)",
    )
    pair.check("SELECT SUM(i), AVG(i) FROM t")


def test_float_sum_precision(pair):
    pair.exec("CREATE TABLE t (r REAL)")
    values = ", ".join(f"({v})" for v in ["1e16", "1.0", "-1e16", "0.1", "0.7", "1e-3"] * 5)
    pair.exec(f"INSERT INTO t VALUES {values}")
    pair.check("SELECT SUM(r), AVG(r), TOTAL(r) FROM t")


def test_left_join_no_match(pair):
    pair.exec(
        "CREATE TABLE a (id INTEGER, v TEXT)",
        "CREATE TABLE b (id INTEGER, a_id INTEGER, w REAL)",
        "INSERT INTO a VALUES (1, 'x'), (2, 'y'), (3, NULL)",
        "INSERT INTO b VALUES (10, 1, 1.5), (11, 1, NULL)",
    )
    pair.check("SELECT a.id, b.id, b.w FROM a LEFT JOIN b ON b.a_id = a.id ORDER BY a.id, b.id")
    pair.check("SELECT * FROM a LEFT JOIN b ON b.a_id = a.id AND b.w > 1 ORDER BY a.id, b.id")
    pair.check("SELECT a.id FROM a LEFT JOIN b ON b.a_id = a.id WHERE b.w IS NULL ORDER BY a.id")
    pair.check(
        "SELECT a.id, COUNT(b.id), SUM(b.w), AVG(b.w) FROM a LEFT JOIN b ON b.a_id = a.id "
        "GROUP BY a.id ORDER BY a.id"
    )
    pair.check("SELECT * FROM b LEFT JOIN a ON 0 ORDER BY b.id")


def test_left_join_empty_right(pair):
    pair.exec(
        "CREATE TABLE a (id INTEGER)",
        "CREATE TABLE b (id INTEGER)",
        "INSERT INTO a VALUES (1), (2)",
    )
    pair.check("SELECT a.id, b.id FROM a LEFT JOIN b ON a.id = b.id ORDER BY a.id")
    pair.check("SELECT a.id, b.id FROM a JOIN b ON a.id = b.id")


def test_three_way_join_with_aliases(pair):
    pair.exec(
        "CREATE TABLE n (id INTEGER, parent INTEGER, label TEXT)",
        "INSERT INTO n VALUES (1, NULL, 'root'), (2, 1, 'a'), (3, 1, 'b'), (4, 2, 'c')",
    )
    pair.check(
        "SELECT c.label, p.label, g.label FROM n AS c LEFT JOIN n AS p ON c.parent = p.id "
        "LEFT JOIN n g ON p.parent = g.id ORDER BY c.id"
    )


def test_order_by_alias_shadows_column(pair):
    pair.exec(
        "CREATE TABLE t (a INTEGER, b INTEGER)",
        "INSERT INTO t VALUES (1, 30), (2, 20), (3, 10)",
    )
    pair.check("SELECT b AS a FROM t ORDER BY a")
    pair.check("SELECT a, b AS c FROM t ORDER BY c")
    pair.check("SELECT a AS x, b FROM t ORDER BY x + b DESC")
    pair.check("SELECT a * 2 AS dbl FROM t WHERE dbl > 2 ORDER BY dbl")


def test_distinct_treats_nulls_equal(pair):
    pair.exec("CREATE TABLE t (a INTEGER, b TEXT)")
    pair.exec("INSERT INTO t VALUES (NULL, NULL), (NULL, NULL), (1, 'a'), (1, 'a'), (1, 'A')")
    pair.check("SELECT DISTINCT a, b FROM t ORDER BY a, b")
    pair.check("SELECT COUNT(DISTINCT b), COUNT(DISTINCT a) FROM t")


def test_group_by_null_key(pair):
    pair.exec(
        "CREATE TABLE t (g TEXT, v INTEGER)",
        "INSERT INTO t VALUES (NULL, 1), ('x', 2), (NULL, 3), ('X', 4)",
    )
    pair.check("SELECT g, SUM(v), COUNT(*) FROM t GROUP BY g ORDER BY g")


def test_comparison_affinity(pair):
    pair.exec(
        "CREATE TABLE t (i INTEGER, r REAL, s TEXT)",
        "INSERT INTO t VALUES (5, 5.0, '5'), (10, 2.5, '10')",
    )
    for cond in [
        "i = '5'",
        "r = '5'",
        "s = 5",
        "s > 9",
        "i > '9'",
        "s IN (5, 10)",
        "i IN ('5')",
        "i BETWEEN '4' AND '6'",
        "s = i",
        "'5' = 5",
    ]:
        pair.check(f"SELECT i FROM t WHERE {cond} ORDER BY i")


def test_integer_and_real_results_keep_types(db):
    db.execute("CREATE TABLE t (i INTEGER, r REAL)")
    db.execute("INSERT INTO t VALUES (3, 1.0)")
    rows = db.execute("SELECT i / 2, r * 2, i + r, COUNT(*), AVG(i), SUM(i), SUM(r) FROM t")
    assert typed(rows) == typed([(1, 2.0, 4.0, 1, 3.0, 3, 1.0)])


def test_comments_and_quoted_identifiers(pair):
    pair.exec(
        'CREATE TABLE "My Table" ("select" INTEGER, [b] TEXT)',
        "INSERT INTO \"My Table\" VALUES (1, 'x') -- trailing comment",
    )
    pair.check('SELECT /* hi */ "select", `b` FROM "my table";')


def test_limit_offset_without_order(pair):
    pair.exec("CREATE TABLE t (a INTEGER)", "INSERT INTO t VALUES (1), (2), (3)")
    assert len(pair.mini.execute("SELECT a FROM t LIMIT 2")) == 2
    assert pair.mini.execute("SELECT a FROM t LIMIT 0") == []
    assert len(pair.mini.execute("SELECT a FROM t LIMIT 5 OFFSET 1")) == 2


def test_join_on_columns_of_different_affinity(pair):
    pair.exec(
        "CREATE TABLE a (k INTEGER, r REAL)",
        "CREATE TABLE b (k TEXT)",
        "INSERT INTO a VALUES (1, 1.0), (2, 2.5), (NULL, NULL)",
        "INSERT INTO b VALUES ('1'), ('2.5'), ('x'), (NULL), ('01')",
    )
    pair.check("SELECT a.k, b.k FROM a JOIN b ON a.k = b.k ORDER BY 1, 2")
    pair.check("SELECT a.r, b.k FROM a LEFT JOIN b ON b.k = a.r ORDER BY 1, 2")
    pair.check("SELECT a.k, a.r FROM a JOIN a AS c ON a.k = c.r ORDER BY 1")


def test_join_on_equality_plus_extra_condition(pair):
    pair.exec(
        "CREATE TABLE a (id INTEGER, g INTEGER)",
        "CREATE TABLE b (id INTEGER, g INTEGER, v INTEGER)",
        "INSERT INTO a VALUES (1, 1), (2, 1), (3, 2), (4, NULL)",
        "INSERT INTO b VALUES (1, 1, 10), (2, 1, 20), (3, 2, 30), (4, NULL, 40)",
    )
    pair.check(
        "SELECT a.id, b.id FROM a LEFT JOIN b ON a.g = b.g AND b.v > 10 * a.id ORDER BY 1, 2"
    )
    pair.check("SELECT a.id, b.id FROM a JOIN b ON b.v > 15 AND a.g = b.g ORDER BY 1, 2")


def test_group_key_value_for_identical_expression(pair):
    pair.exec(
        "CREATE TABLE t (i INTEGER, s TEXT)",
        "INSERT INTO t VALUES (5, '10'), (1, '2.5'), (3, '7'), (9, '1.5')",
    )
    pair.check("SELECT 'x' * s AS k, s, MAX(i) FROM t GROUP BY k")
    pair.check("SELECT 'x' * s, MAX(i) FROM t GROUP BY 'x' * s")
    pair.check("SELECT 'x' * s + 0, MAX(i) FROM t GROUP BY 'x' * s")
    pair.check("SELECT TYPEOF('x' * s), MIN(i) FROM t GROUP BY 'x' * s")


def test_having_requires_aggregate_query(pair):
    pair.exec("CREATE TABLE t (a INTEGER)", "INSERT INTO t VALUES (1), (2)")
    pair.check("SELECT a FROM t HAVING a > 1")
    pair.check("SELECT a FROM t GROUP BY a HAVING a > 1")


def test_sum_overflow_errors_like_sqlite(pair):
    pair.exec(
        "CREATE TABLE t (i INTEGER, r REAL)",
        "INSERT INTO t VALUES (9223372036854775807, NULL), (1, 1.5)",
    )
    pair.check("SELECT SUM(i) FROM t")
    pair.check("SELECT AVG(i), TOTAL(i) FROM t")
    pair.check("SELECT SUM(i + 0.0) FROM t")


def test_nan_becomes_null(pair):
    pair.check("SELECT (1e308 * 10) - (1e308 * 10), (1e308 * 10) * 0")


def test_larger_dataset(pair):
    pair.exec(
        "CREATE TABLE a (id INTEGER, grp TEXT, x REAL)",
        "CREATE TABLE b (id INTEGER, a_id INTEGER, y INTEGER)",
    )
    rows_a = ", ".join(
        f"({i}, {'NULL' if i % 17 == 0 else repr('g' + str(i % 7))}, {i * 0.37 - 50})"
        for i in range(600)
    )
    rows_b = ", ".join(
        f"({i}, {'NULL' if i % 11 == 0 else (i * 7) % 650}, {(i * 13) % 101 - 50})"
        for i in range(1500)
    )
    pair.exec(f"INSERT INTO a VALUES {rows_a}", f"INSERT INTO b VALUES {rows_b}")
    pair.check(
        "SELECT a.grp, COUNT(b.id), SUM(b.y), AVG(a.x), MIN(b.y), MAX(a.x) FROM a "
        "LEFT JOIN b ON b.a_id = a.id GROUP BY a.grp ORDER BY a.grp"
    )
    pair.check(
        "SELECT a.id, b.id, a.x * b.y FROM a JOIN b ON a.id = b.a_id "
        "WHERE b.y BETWEEN -10 AND 10 ORDER BY a.x * b.y DESC, a.id, b.id LIMIT 25 OFFSET 5"
    )
    pair.check("SELECT DISTINCT y % 7 FROM b ORDER BY 1")
    pair.check("SELECT a_id, COUNT(*) AS n FROM b GROUP BY a_id HAVING n > 2 ORDER BY n DESC, a_id")
