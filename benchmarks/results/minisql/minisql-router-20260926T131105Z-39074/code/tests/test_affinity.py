"""Column type affinity on INSERT/UPDATE and in comparisons."""

import pytest

STORED_VALUES = [
    "3",
    "3.0",
    "3.5",
    "-2.0",
    "'3'",
    "'3.0'",
    "'3.5'",
    "'abc'",
    "' 4'",
    "'  7  '",
    "'1e2'",
    "'0x10'",
    "1e20",
    "1e18",
    "'9223372036854775808'",
    "'-5'",
    "'+5'",
    "'5e'",
    "'1.'",
    "'.1'",
    "''",
    "NULL",
    "0.1",
    "1e15",
    "12345678901234567.0",
    "'12abc'",
    "-0.0",
    "2.5e-7",
]


@pytest.mark.parametrize("value", STORED_VALUES)
def test_insert_affinity(pair, value):
    pair.run(
        "CREATE TABLE t (i INTEGER, r REAL, s TEXT, n NUMERIC, b)",
        f"INSERT INTO t VALUES ({value}, {value}, {value}, {value}, {value})",
    )
    pair.query("SELECT i, r, s, n, b FROM t")


@pytest.mark.parametrize("value", ["3.0", "'4'", "'x'", "7.25", "NULL", "10 / 4", "'2' || '5'"])
def test_update_affinity(pair, value):
    pair.run(
        "CREATE TABLE t (i INTEGER, r REAL, s TEXT)",
        "INSERT INTO t VALUES (1, 1.0, 'a')",
        f"UPDATE t SET i = {value}, r = {value}, s = {value}",
    )
    pair.query("SELECT i, r, s FROM t")


@pytest.mark.parametrize(
    "type_name",
    [
        "INT",
        "BIGINT",
        "VARCHAR(20)",
        "DOUBLE",
        "FLOAT",
        "DECIMAL(10, 2)",
        "BOOLEAN",
        "CLOB",
        "BLOB",
    ],
)
def test_type_name_affinity(pair, type_name):
    pair.run(
        f"CREATE TABLE t (c {type_name})",
        "INSERT INTO t VALUES ('12'), (3.0), ('4.5'), ('x'), (7)",
    )
    pair.query("SELECT c FROM t")


COMPARISONS = [
    "i = '3'",
    "s = 3",
    "b = 3",
    "i = b",
    "s = i",
    "r = '3'",
    "i BETWEEN '2' AND '4'",
    "s BETWEEN 2 AND 4",
    "i IN ('3')",
    "s IN (3)",
    "b IN (3)",
    "'3' IN (i)",
    "i IN ('3', NULL)",
    "s LIKE 3",
    "i IS '3'",
    "+i = '3'",
    "n = '3'",
    "s > 10",
    "i > '10'",
    "'10' > i",
    "(i) = '3'",
    "i + 0 = '3'",
    "-i = '-3'",
    "i = '3.0'",
    "i = ' 3 '",
    "i = '3x'",
    "r = '3.0'",
    "s = 3.0",
    "s < 30",
    "i < 'abc'",
    "s IS 3",
    "s IS NOT 3",
    "i != '3'",
    "i <> '4'",
    "'3' = s",
    "3 = s",
    "s = b",
    "b = '3'",
    "3 = '3'",
    "s = b + 0",
    "s IN (b)",
    "b IN ('3')",
    "i IN (s)",
    "s IN (i)",
    "i = s || ''",
    "r IN ('10.5', 3)",
]


@pytest.mark.parametrize("condition", COMPARISONS)
def test_comparison_affinity(pair, condition):
    pair.run(
        "CREATE TABLE t (i INTEGER, r REAL, s TEXT, n NUMERIC, b)",
        "INSERT INTO t VALUES (3, 3.0, '3', 3, '3'), (10, 10.5, '10', 10, 10), "
        "(NULL, NULL, NULL, NULL, NULL), (-3, -3.0, 'abc', 'x', 'abc')",
    )
    pair.query(f"SELECT {condition} FROM t")
    pair.query(f"SELECT i, s FROM t WHERE {condition}")


def test_text_column_ordering_is_textual(pair):
    pair.run(
        "CREATE TABLE t (s TEXT, i INTEGER)",
        "INSERT INTO t VALUES (10, '10'), (9, '9'), (100, '100'), ('abc', 'abc')",
    )
    pair.query("SELECT s FROM t ORDER BY s")
    pair.query("SELECT i FROM t ORDER BY i")
    pair.query("SELECT s, i FROM t WHERE s < 5 ORDER BY i")
