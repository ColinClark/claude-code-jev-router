"""Scalar expression semantics compared against sqlite3."""

import pytest

CONSTANT_EXPRS = [
    # literals
    "1", "-1", "+1", "1.5", "-1.5", ".5", "5.", "1e3", "1.5e-3", "'abc'", "'it''s'", "''", "NULL",
    "9223372036854775807", "9223372036854775808", "0x10", "-0x10",
    # arithmetic
    "1 + 2", "1 + 2.0", "1.5 + 2.5", "5 - 7", "5 - 7.5", "3 * 4", "3 * 4.0", "2.5 * 2",
    "7 / 2", "-7 / 2", "7 / -2", "-7 / -2", "7.0 / 2", "7 / 2.0", "1 / 3.0", "2.0 / 3",
    "7 % 3", "-7 % 3", "7 % -3", "-7 % -3", "5.5 % 2", "-5.5 % 2", "7 % 2.5", "5 % 0.5",
    "7.9 % 3.9", "1e300 % 3",
    "1 / 0", "1 % 0", "1.0 / 0", "1 / 0.0", "1.5 % 0", "0 / 0", "NULL / 0",
    "1 + NULL", "NULL - 1", "NULL * NULL", "NULL / 2", "NULL % 2", "-NULL", "+NULL",
    "1 + 2 * 3", "(1 + 2) * 3", "10 - 2 - 3", "2 * 3 % 4", "100 / 10 / 2", "- - 3", "-(-3)",
    "'3' + 4", "'3.5' + 1", "'12abc' + 1", "'abc' + 1", "' 3 ' + 1", "'1e2' + 0", "'.5' * 2",
    "-'abc'", "-'3'", "+'abc'", "'5.' + 0", "'0x10' + 0", "'-3' * 2", "'+4' - 1",
    "0.1 + 0.2", "1e308 * 10", "-(1e308 * 10)", "2.0 * 3", "4.0 - 1", "3.0 / 1",
    "9223372036854775807 + 1", "-9223372036854775807 - 10", "4611686018427387904 * 4",
    "2 & 3", "2 | 5", "1 << 3", "256 >> 4", "~5", "-1 >> 1", "1 << 64", "3.7 & 1",
    # concatenation
    "'a' || 'b'", "1 || 2", "1.0 || ''", "1.5 || 'x'", "'x' || NULL", "NULL || 'x'",
    "1e20 || ''", "1e15 || ''", "1e16 || ''", "1e17 || ''", "0.0001 || ''", "0.00001 || ''",
    "(0.1 + 0.2) || ''", "123456.789 || ''", "-0.0 || ''", "100.0 || ''", "2.5e-7 || ''",
    "1 + 2 || 3", "'1' || '2' + 3", "-1 || 2", "2 * 3 || 4",
    # comparisons
    "1 = 1", "1 = 1.0", "1 == 2", "1 != 2", "1 <> 1", "1 < 2", "2 <= 2", "3 > 2.5", "2 >= 3",
    "'a' < 'b'", "'a' < 'B'", "'abc' = 'ABC'", "'a' < 1", "1 < 'a'", "'10' < 9", "'10' = 10",
    "NULL = NULL", "NULL != 1", "1 < NULL", "NULL >= NULL", "'' < 0", "'' > 0",
    "1 = 1 = 1", "2 > 1 = 1", "1 < 2 < 3", "3 > 2 > 1", "'x' = 'x' = 1",
    # logic
    "1 AND 1", "1 AND 0", "0 AND NULL", "NULL AND 0", "1 AND NULL", "NULL AND NULL",
    "1 OR 0", "0 OR 0", "1 OR NULL", "NULL OR 1", "0 OR NULL", "NULL OR NULL",
    "NOT 1", "NOT 0", "NOT NULL", "NOT 'abc'", "NOT '1x'", "NOT 0.5", "NOT -1",
    "NOT 1 = 2", "NOT 1 AND 0", "1 OR 0 AND 0", "(1 OR 0) AND 0", "NOT NOT 1",
    "0.5 AND 1", "'abc' OR 0", "'1abc' AND 1", "2 AND 3",
    # IS / IS NULL
    "NULL IS NULL", "1 IS NULL", "NULL IS NOT NULL", "1 IS NOT NULL", "1 IS 1", "1 IS 1.0",
    "NULL IS 1", "1 IS NOT 2", "NULL ISNULL", "1 NOTNULL", "1 NOT NULL", "'a' IS 'a'",
    "1 = 2 IS NULL", "NULL = 1 IS NULL",
    # IN
    "1 IN (1, 2, 3)", "4 IN (1, 2, 3)", "4 NOT IN (1, 2, 3)", "1 NOT IN (1, 2)",
    "NULL IN (1, 2)", "NULL NOT IN (1, 2)", "1 IN (NULL, 1)", "3 IN (NULL, 1)",
    "3 NOT IN (NULL, 1)", "1 IN ()", "NULL IN ()", "NULL NOT IN ()", "1.0 IN (1)",
    "'1' IN (1)", "1 IN ('1')", "'a' IN ('A', 'a')", "1 + 1 IN (2)", "2 IN (1 + 1, 3)",
    # BETWEEN
    "2 BETWEEN 1 AND 3", "0 BETWEEN 1 AND 3", "1 BETWEEN 1 AND 1", "2 NOT BETWEEN 1 AND 3",
    "NULL BETWEEN 1 AND 2", "1 BETWEEN NULL AND 2", "3 BETWEEN NULL AND 2",
    "1 BETWEEN 2 AND NULL", "3 NOT BETWEEN NULL AND 2", "1 NOT BETWEEN NULL AND 2",
    "'b' BETWEEN 'a' AND 'c'", "2.5 BETWEEN 2 AND 3", "5 BETWEEN 1 AND 3 = 0",
    "1 BETWEEN 0 AND 2 AND 1", "2 BETWEEN 1 + 0 AND 1 + 2",
    # LIKE
    "'abc' LIKE 'abc'", "'abc' LIKE 'ABC'", "'ABC' LIKE 'a%'", "'abc' LIKE '%c'",
    "'abc' LIKE '%b%'", "'abc' LIKE 'a_c'", "'abc' LIKE 'a_'", "'abc' LIKE '___'",
    "'abc' LIKE '%'", "'' LIKE '%'", "'' LIKE '_'", "'abc' NOT LIKE 'a%'",
    "NULL LIKE 'a'", "'a' LIKE NULL", "NULL NOT LIKE 'a'", "5 LIKE '5'", "5.0 LIKE '5.0'",
    "'a.c' LIKE 'a.c'", "'abc' LIKE 'a.c'", "'a+c' LIKE 'a+c'", "'x%y' LIKE 'x%'",
    "'Ä' LIKE 'ä'", "'line1\nline2' LIKE 'line1%'", "'10%' LIKE '10\\%' ESCAPE '\\'",
    "'100' LIKE '10\\%' ESCAPE '\\'", "'a_b' LIKE 'a\\_b' ESCAPE '\\'",
    "'abc' LIKE 'a%' = 1", "1 + 1 LIKE '2'",
    # CASE / CAST / functions
    "CASE WHEN 1 THEN 'a' ELSE 'b' END", "CASE WHEN NULL THEN 'a' ELSE 'b' END",
    "CASE WHEN 0 THEN 'a' END", "CASE 1 WHEN 1 THEN 'one' WHEN 2 THEN 'two' END",
    "CASE NULL WHEN NULL THEN 'n' ELSE 'x' END", "CASE 2 WHEN 1.0 THEN 'a' WHEN 2.0 THEN 'b' END",
    "CAST('12abc' AS INTEGER)", "CAST(3.9 AS INTEGER)", "CAST(-3.9 AS INTEGER)",
    "CAST('1e2' AS INTEGER)", "CAST('abc' AS REAL)", "CAST('3.0' AS NUMERIC)", "CAST(5 AS TEXT)",
    "CAST(2.50 AS TEXT)", "CAST(NULL AS INTEGER)", "CAST(7 AS REAL)",
    "abs(-3)", "abs(-3.5)", "abs('-3')", "abs(NULL)", "length('hello')", "length(12.0)",
    "length(NULL)", "lower('AbC')", "upper('aBc')", "upper(1.5)", "coalesce(NULL, NULL, 3)",
    "coalesce(NULL, 'x')", "ifnull(NULL, 2)", "ifnull(1, 2)", "nullif(1, 1)", "nullif(1, 2)",
    "nullif(1, 1.0)", "typeof(1)", "typeof(1.0)", "typeof('a')", "typeof(NULL)",
    "typeof(1 = 1)", "typeof(7 / 2)", "typeof(7 / 2.0)", "max(1, 2.5, 2)", "min(3, 'a', 1)",
    "max(1, NULL)", "min('b', 'a')", "TRUE", "FALSE", "TRUE + 1",
    "1 IS TRUE", "2 IS TRUE", "0 IS FALSE", "NULL IS TRUE", "NULL IS NOT TRUE", "NULL IS FALSE",
    "0.5 IS TRUE", "'a' IS NOT TRUE", "'1x' IS TRUE", "2 IS (1 IN ())", "0 IS (1 NOT IN ())",
    "NULL IS NOT FALSE", "TRUE IS 1", "2 = TRUE",
    # case-insensitive keywords
    "not 1 iS nUlL", "1 In (1)", "2 bEtWeEn 1 AnD 3", "'A' lIkE 'a'",
]


@pytest.mark.parametrize("expr", CONSTANT_EXPRS)
def test_constant_expression(pair, expr):
    pair.query(f"SELECT {expr}")


TYPED_TABLE = [
    "CREATE TABLE v (i INTEGER, r REAL, t TEXT, n NUMERIC, b)",
    "INSERT INTO v VALUES (1, 1.0, '1', 1, 1), (2, 2.5, '2.5', '2.5', '2'),"
    " (NULL, NULL, NULL, NULL, NULL), (-3, -3.25, 'abc', 'abc', 'abc'),"
    " (10, 10.0, '10', '10.0', 10.0), (0, 0.0, '', '', ''), (7, 1e20, 'Z', 7.5, 7.5)",
]

COLUMN_EXPRS = [
    "i", "r", "t", "n", "b", "typeof(i)", "typeof(r)", "typeof(t)", "typeof(n)", "typeof(b)",
    "i + r", "i * 2", "i / 2", "i % 3", "r / 2", "r % 2", "t + 1", "t || i", "i || r",
    "-i", "-t", "+t", "i = t", "i = '1'", "r = '1'", "t = 1", "t = 1.0", "t < 5", "i < '5'",
    "i > 'a'", "t > 2", "n = '2.5'", "n = 2.5", "b = 1", "b = '1'", "+i = '1'", "(i) = '1'",
    "i IN ('1', '10')", "t IN (1, 10)", "'1' IN (i)", "i BETWEEN '1' AND '5'",
    "t BETWEEN 1 AND 5", "i IS '1'", "t IS 1", "i IS NULL", "t IS NOT NULL",
    "i = r", "t = r", "i < t", "t LIKE '1%'", "r LIKE '1%'", "i AND r", "t OR 0", "NOT t",
    "i IS i", "CASE i WHEN '1' THEN 'one' ELSE 'other' END", "CASE t WHEN 1 THEN 'x' END",
    "i + NULL", "coalesce(i, r, t)", "abs(t)", "length(r)", "i = r AND t = i",
    "CAST(t AS INTEGER) = i", "CAST(i AS TEXT) = t", "i IN (1, NULL)", "i NOT IN (1, NULL)",
    "max(i, r)", "min(t, i)",
]


@pytest.mark.parametrize("expr", COLUMN_EXPRS)
def test_column_expression(pair, expr):
    pair.exec(*TYPED_TABLE)
    pair.query(f"SELECT {expr} FROM v")
    pair.query(f"SELECT i, r, t FROM v WHERE {expr}")
    pair.query(f"SELECT i, r, t FROM v WHERE NOT ({expr})")


def test_precedence_combinations(pair):
    exprs = [
        "1 + 2 * 3 - 4 / 2 % 3",
        "1 || 2 * 3",
        "2 * 3 || 4 + 1",
        "1 < 2 = 2 > 1",
        "1 = 1 AND 0 = 1 OR 1",
        "NOT 0 = 1 AND 1",
        "NOT 1 IS NULL",
        "1 IS NULL = 0",
        "1 + 1 BETWEEN 1 AND 3 = 1",
        "2 IN (1, 2) = 1",
        "'a' || 'b' LIKE 'AB'",
        "- 2 * - 3",
        "-2 || 3",
        "1 < 2 IN (1)",
        "5 - 3 - 1",
        "2 * 3 % 4 * 5",
        "1 OR 0 AND NULL",
        "NULL OR 1 AND 0",
    ]
    for e in exprs:
        pair.query(f"SELECT {e}")
