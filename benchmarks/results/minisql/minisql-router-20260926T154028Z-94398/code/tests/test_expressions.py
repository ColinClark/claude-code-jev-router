"""Scalar expression semantics compared against sqlite3."""

import pytest

EXPRESSIONS = [
    # literals
    "1", "-1", "1.5", "-0.0", "'abc'", "'it''s'", "NULL", "9223372036854775807",
    "-9223372036854775808", "9223372036854775808", "1e3", ".5", "5.", "1E-2",
    # arithmetic
    "1 + 2", "1 - 2.5", "3 * 4", "3 * 1.0", "7 / 2", "-7 / 2", "7 / -2", "7.0 / 2", "7 / 2.0",
    "1 / 0", "1.0 / 0", "1 / 0.0", "0 / 0", "7 % 3", "-7 % 3", "7 % -3", "-7 % -3", "7 % 0",
    "5.5 % 2", "-5.5 % 2", "5 % 2.5", "3 % 0.5", "7.0 % 0", "2 + 3 * 4", "(2 + 3) * 4",
    "10 - 2 - 3", "100 / 10 / 5", "-(3)", "-(-3)", "- -3", "+5", "-'3'", "-'abc'",
    "9223372036854775807 + 1", "-9223372036854775808 - 1", "9223372036854775807 * 2",
    "-(-9223372036854775808)", "4611686018427387904 * 2", "-9223372036854775808 / -1",
    "'3' + 4", "'3.5' + 1", "'3abc' + 1", "'abc' + 1", "'' + 1", "' 12 ' + 1", "'1e2' + 0",
    "'12.0' + 0", "'.5' + 0", "'5.' + 0", "'-3' * 2", "'0x10' + 0",
    "NULL + 1", "1 - NULL", "NULL * NULL", "NULL / 0", "5 % NULL", "-NULL",
    # concatenation
    "'a' || 'b'", "1 || 2", "1.5 || 'x'", "'x' || NULL", "NULL || NULL", "1.0 || ''",
    "(0.1 + 0.2) || ''", "(1.0 / 3) || ''", "1e20 || ''", "1e-5 || ''", "123456789.123 || ''",
    "1e15 || ''", "1e16 || ''", "-0.0 || ''", "2.5e-300 || ''", "(1e300 * 1e10) || ''",
    "-1 || -2", "1 + 2 || 3", "-2 || 3",
    # comparisons
    "1 = 1", "1 = 1.0", "1 == 2", "1 != 2", "1 <> 1", "1 < 2", "2 <= 2", "3 > 2", "2 >= 3",
    "'a' < 'b'", "'a' < 'B'", "'abc' = 'ABC'", "1 < 'a'", "'a' < 1", "'1' = 1", "'10' > 9",
    "NULL = NULL", "NULL <> 1", "1 < NULL", "NULL IS NULL", "1 IS NULL", "NULL IS NOT NULL",
    "1 IS NOT NULL", "1 IS 1", "NULL IS 1", "1 IS NOT 2", "NULL IS NOT NULL", "1 = 1 = 1",
    "2 > 1 = 1", "1 + 1 = 2",
    # logic
    "1 AND 1", "1 AND 0", "0 AND NULL", "NULL AND 0", "1 AND NULL", "NULL AND NULL",
    "1 OR 0", "0 OR 0", "NULL OR 1", "0 OR NULL", "NULL OR NULL", "NOT 1", "NOT 0",
    "NOT NULL", "NOT 'abc'", "NOT '1'", "NOT 0.5", "1 AND 'x'", "'1x' AND 1",
    "NOT 1 = 2", "NOT 1 AND 0", "1 OR 0 AND 0", "(1 OR 0) AND 0",
    # IN
    "1 IN (1, 2, 3)", "4 IN (1, 2, 3)", "1 IN (NULL, 1)", "4 IN (1, NULL)", "NULL IN (1, 2)",
    "NULL IN ()", "1 IN ()", "1 NOT IN ()", "1 NOT IN (2, 3)", "1 NOT IN (1)",
    "1 NOT IN (2, NULL)", "'a' IN ('A', 'a')", "1 IN ('1')", "1.0 IN (1)", "1 + 1 IN (2)",
    # BETWEEN
    "2 BETWEEN 1 AND 3", "0 BETWEEN 1 AND 3", "1 BETWEEN 1 AND 1", "NULL BETWEEN 1 AND 2",
    "1 BETWEEN NULL AND 2", "0 BETWEEN NULL AND -1", "5 BETWEEN 1 AND NULL",
    "2 NOT BETWEEN 1 AND 3", "0 NOT BETWEEN 1 AND 3", "NULL NOT BETWEEN 1 AND 2",
    "5 NOT BETWEEN 1 AND NULL", "'b' BETWEEN 'a' AND 'c'", "1 BETWEEN 0 AND 2 AND 1",
    # LIKE
    "'abc' LIKE 'abc'", "'abc' LIKE 'ABC'", "'ABC' LIKE 'a%'", "'abc' LIKE 'a_c'",
    "'abc' LIKE 'a_'", "'abc' LIKE '%'", "'' LIKE '%'", "'' LIKE '_'", "'abc' LIKE '%b%'",
    "'abc' LIKE '%d%'", "'a.c' LIKE 'a.c'", "'abc' LIKE 'a.c'", "'a+c' LIKE 'a+c'",
    "'a\nb' LIKE 'a_b'", "'é' LIKE 'É'", "'é' LIKE 'é'", "NULL LIKE 'a'", "'a' LIKE NULL",
    "'abc' NOT LIKE 'a%'", "'abc' NOT LIKE 'b%'", "NULL NOT LIKE 'a'", "123 LIKE '1%'",
    "1.5 LIKE '1.5'", "'[a]' LIKE '[a]'", "'a%' LIKE 'a%'", "'100%' LIKE '1__\\%'",
    # CASE and functions
    "CASE WHEN 1 THEN 'y' ELSE 'n' END", "CASE WHEN NULL THEN 'y' ELSE 'n' END",
    "CASE 1 WHEN 1 THEN 'one' WHEN 2 THEN 'two' END", "CASE 3 WHEN 1 THEN 'one' END",
    "CASE NULL WHEN NULL THEN 'x' ELSE 'y' END",
    "abs(-3)", "abs(-3.5)", "abs(NULL)", "length('abc')", "length(123)", "upper('abc')",
    "lower('ABC')", "coalesce(NULL, 2, 3)", "ifnull(NULL, 'x')", "nullif(1, 1)", "nullif(1, 2)",
    "typeof(1)", "typeof(1.0)", "typeof('a')", "typeof(NULL)", "max(1, 2, 3)", "min(1, 'a')",
    "max(1, NULL)",
]


@pytest.mark.parametrize("expr", EXPRESSIONS)
def test_expression_matches_sqlite(both, expr):
    both.check(f"SELECT {expr}")


COLUMN_EXPRESSIONS = [
    "i = '5'", "i = 5", "i = '5.0'", "i < '10'", "t = 5", "t = '5'", "t < 10", "t > 10",
    "r = 5", "r = '5'", "r = '5.0'", "i = r", "i = t", "t = r", "i IN ('5', 6)", "t IN (5, 6)",
    "r IN ('5')", "i BETWEEN '4' AND '6'", "t BETWEEN 4 AND 6", "i + t", "t || i", "r || ''",
    "i / 2", "r / 2", "i % 3", "t * 1", "i IS '5'", "t IS 5",
    "CASE i WHEN '5' THEN 'hit' ELSE 'miss' END", "CASE t WHEN 5 THEN 'hit' ELSE 'miss' END",
    "-t", "t LIKE '5%'", "n IS NULL", "n = n", "n IN (1)", "i IN (n)",
]


@pytest.mark.parametrize("expr", COLUMN_EXPRESSIONS)
def test_column_affinity_matches_sqlite(both, expr):
    both.run("CREATE TABLE a (i INTEGER, t TEXT, r REAL, n INTEGER)")
    both.run("INSERT INTO a VALUES (5, '5', 5.0, NULL), (10, '10', 10.5, NULL), (-3, 'x', -0.5, 1)")
    both.check(f"SELECT {expr} FROM a")
