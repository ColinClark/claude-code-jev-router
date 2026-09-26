"""Scalar expression semantics, compared value-by-value (and type-by-type) with sqlite3."""

import pytest

LITERAL_EXPRS = [
    # arithmetic, integer vs real
    "1 + 2", "1 + 2.0", "7 / 2", "-7 / 2", "7 / -2", "7.0 / 2", "7 / 2.0", "1 / 0", "1.0 / 0",
    "0 / 0", "7 % 3", "-7 % 3", "7 % -3", "-7 % -3", "7 % 0", "5.5 % 2", "5.7 % 2.2", "5 % 2.5",
    "-5.5 % 2", "5 % 0.5",
    "-9223372036854775807 % 7.75", "1e19 % 7.0", "-1e19 % 7.0",
    "2 * 3", "2 * 3.5", "10 - 20", "1.5 - 0.5", "3 * -2",
    "9223372036854775807 + 1", "-9223372036854775808 - 1", "9223372036854775807 * 2",
    "-9223372036854775808", "9223372036854775808", "-(-9223372036854775807)",
    "0.1 + 0.2", "1e3", "1.5e-3 * 2", ".5 + 1", "2 + 3 * 4", "(2 + 3) * 4", "10 - 4 - 3",
    "100 / 10 / 5", "2 * 3 % 4", "- - 3", "-(2)", "+5", "-'3'", "-'abc'", "-'2.5x'",
    # NULL propagation
    "NULL + 1", "1 - NULL", "NULL * NULL", "NULL / 0", "5 % NULL", "-NULL", "NULL || 'a'",
    # text/number coercion in arithmetic
    "'12' + 1", "'12abc' + 1", "'abc' + 1", "'1.5' * 2", "'1e3' + 0", "' 5 ' + 1", "'1.0' + 1",
    "'' + 1", "'-3' * 2", "'10' / '4'", "'10' % '4'", "'x' / 1",
    # concatenation
    "'a' || 'b'", "'a' || 1", "1 || 2", "1.5 || 'x'", "100.0 || ''", "1e20 || ''",
    "1.5e-7 || ''", "(0.1 + 0.2) || ''", "(1e14) || ''", "(1.5e15) || ''",
    "(123456789012345.6) || ''", "(1.0 / 3) || ''", "0.0001 || ''",
    "123456789012345678.0 || ''", "-2.5 || ''", "3 || 4.0", "'a' || 1 + 2",
    "1 / 3.0 || ''", "-0.0 || ''", "'x' || -1", "1e300 * 1e300 || ''",
    # comparisons
    "1 = 1", "1 = 1.0", "1 == 2", "1 != 2", "1 <> 1", "1 < 2", "2 <= 2", "3 > 2", "3 >= 4",
    "'a' < 'b'", "'a' < 'B'", "'abc' = 'abc'", "'abc' = 'ABC'", "1 < 'a'", "'1' = 1",
    "'abc' < 5", "2 < '1'", "NULL = NULL", "NULL != 1", "1 < NULL", "NULL >= NULL",
    "1 = 1 = 1", "2 > 1 = 1", "'' < 'a'", "1.5 > 1", "-1 < 0.5",
    # boolean logic, three-valued
    "1 AND 1", "1 AND 0", "0 AND NULL", "NULL AND 0", "1 AND NULL", "NULL AND NULL",
    "1 OR 0", "0 OR 0", "0 OR NULL", "NULL OR 1", "1 OR NULL", "NULL OR NULL",
    "NOT 1", "NOT 0", "NOT NULL", "NOT 'abc'", "NOT '1x'", "NOT 0.5", "2 AND 3", "0.0 OR 0",
    "'a' AND 1", "'1' OR 0", "NOT 1 = 2", "NOT NULL IS NULL", "1 OR 0 AND 0", "(1 OR 0) AND 0",
    # IS / IS NOT / IS NULL
    "NULL IS NULL", "1 IS NULL", "1 IS NOT NULL", "NULL IS NOT NULL", "1 IS 1", "1 IS NOT 2",
    "NULL IS 1", "NULL IS NOT NULL + 1", "'a' IS 'a'",
    # IN
    "1 IN (1, 2, 3)", "4 IN (1, 2, 3)", "4 IN (1, NULL)", "1 IN (1, NULL)", "NULL IN (1, 2)",
    "NULL IN ()", "1 IN ()", "1 NOT IN ()", "4 NOT IN (1, 2)", "1 NOT IN (1, 2)",
    "4 NOT IN (1, NULL)", "NULL NOT IN (1)", "'a' IN ('A', 'a')", "1 IN ('1', 2)",
    "1.0 IN (1)", "2 IN (1 + 1, 3)",
    # BETWEEN
    "2 BETWEEN 1 AND 3", "0 BETWEEN 1 AND 3", "1 BETWEEN 1 AND 1", "2 NOT BETWEEN 1 AND 3",
    "NULL BETWEEN 1 AND 2", "1 BETWEEN NULL AND 2", "5 BETWEEN NULL AND 2",
    "5 NOT BETWEEN NULL AND 2", "1 BETWEEN 2 AND NULL", "'b' BETWEEN 'a' AND 'c'",
    "2.5 BETWEEN 2 AND 3", "1 + 1 BETWEEN 1 AND 3 AND 1",
    # LIKE
    "'abc' LIKE 'abc'", "'abc' LIKE 'ABC'", "'ABC' LIKE 'a%'", "'abc' LIKE 'a_c'",
    "'abc' LIKE '_'", "'abc' LIKE '%'", "'' LIKE '%'", "'' LIKE '_'", "'abc' LIKE '%c'",
    "'abc' LIKE '%b%'", "'abc' LIKE 'b%'", "'abc' NOT LIKE 'a%'", "NULL LIKE 'a'",
    "'a' LIKE NULL", "NULL NOT LIKE 'a'", "5 LIKE 5", "15 LIKE '1%'", "1.5 LIKE '1._'",
    "'Ä' LIKE 'ä'", "'ä' LIKE 'ä'", "'a.c' LIKE 'a.c'", "'abc' LIKE 'a.c'", "'a*c' LIKE 'a*c'",
    "'a\nb' LIKE 'a_b'", "'50%' LIKE '50\\%' ESCAPE '\\'", "'50x' LIKE '50\\%' ESCAPE '\\'",
    "'a[b' LIKE 'a[b'", "'x(y)' LIKE 'x(%'", "'Hello World' LIKE '%o w%'",
    # CASE and functions
    "CASE WHEN 1 THEN 'a' ELSE 'b' END", "CASE WHEN NULL THEN 'a' ELSE 'b' END",
    "CASE 2 WHEN 1 THEN 'one' WHEN 2 THEN 'two' END", "CASE NULL WHEN NULL THEN 1 ELSE 0 END",
    "CASE WHEN 0 THEN 1 END", "coalesce(NULL, NULL, 3)", "ifnull(NULL, 'x')", "nullif(1, 1)",
    "nullif(1, 2)", "abs(-3)", "abs(-2.5)", "abs(NULL)", "length('héllo')", "length(12.5)",
    "upper('aé')", "lower('ABC')", "min(3, 1, 2)", "max(3, NULL)", "typeof(1 / 2.0)",
    # string literals and escapes
    "'it''s'", "''", "'a' = 'a' || ''",
]


@pytest.mark.parametrize("expr", LITERAL_EXPRS)
def test_literal_expression(pair, expr):
    pair.check(f"SELECT {expr}")


COLUMN_EXPRS = [
    "i + r", "i / 2", "i % 3", "r / 0", "s || i", "i = s", "s = 4", "s < 5", "i < s", "r = i",
    "i IN ('1', '2')", "s IN (1, 4)", "i BETWEEN '1' AND '3'", "s BETWEEN 1 AND 5",
    "i = '12'", "r = '2.5'", "s = '4'", "i || ''", "r || ''", "s + 1", "-s", "NOT s",
    "s LIKE '4%'", "i IS NULL", "r IS NOT NULL", "i > 1 AND r > 1", "i > 1 OR r IS NULL",
    "i IS '1'", "s IS 4", "CASE i WHEN '1' THEN 'one' ELSE 'other' END", "i = r", "i < r",
    "i * r", "coalesce(i, r, s)", "typeof(i)", "typeof(r)", "typeof(s)",
]


@pytest.mark.parametrize("expr", COLUMN_EXPRS)
def test_column_expression_with_affinity(pair, expr):
    pair.exec(
        "CREATE TABLE v (i INTEGER, r REAL, s TEXT)",
        "INSERT INTO v VALUES (1, 1.5, '4'), (2, NULL, 'abc'), (NULL, 2.5, NULL), "
        "(12, 12.0, '12'), (-3, -0.5, ''), (0, 0.0, '0'), (3, 3.0, '3.0')",
    )
    pair.check(f"SELECT i, r, s, {expr} FROM v")


@pytest.mark.parametrize(
    "where",
    [
        "i > 1", "i = 1 OR s = 'abc'", "NOT i > 1", "r", "s", "i", "NOT r", "i IN (1, 12)",
        "i NOT IN (1, NULL)", "s LIKE '%'", "s NOT LIKE '1%'", "i BETWEEN 0 AND 3",
        "i NOT BETWEEN 0 AND 3", "r IS NULL", "i + r > 3", "s = 12", "s > 1", "i != 1",
        "i IS NOT 1", "NULL", "1", "0", "'1'", "'abc'",
    ],
)
def test_where_filters(pair, where):
    pair.exec(
        "CREATE TABLE v (i INTEGER, r REAL, s TEXT)",
        "INSERT INTO v VALUES (1, 1.5, '4'), (2, NULL, 'abc'), (NULL, 2.5, NULL), "
        "(12, 12.0, '12'), (-3, -0.5, ''), (0, 0.0, '0'), (3, 3.0, '3.0')",
    )
    pair.check(f"SELECT * FROM v WHERE {where}")
