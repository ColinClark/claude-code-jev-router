"""Scalar expression semantics compared against SQLite."""

import pytest

from tests.conftest import Pair

CONSTANT_EXPRESSIONS = [
    # literals
    "1", "-1", "1.5", "-0.0", "'it''s'", "NULL", "1e3", ".5", "9223372036854775807",
    "-9223372036854775808", "9223372036854775808",
    # arithmetic
    "1 + 2", "1 - 2.5", "2 * 3", "2 * 3.0", "7 / 2", "-7 / 2", "7 / -2", "7.0 / 2",
    "7 / 2.0", "1 / 0", "1.0 / 0", "0 / 0", "7 % 3", "-7 % 3", "7 % -3", "7.5 % 2",
    "-7.5 % 2", "7 % 0", "7 % 0.5", "5 % 2.9", "2 + 3 * 4", "(2 + 3) * 4", "10 - 4 - 3",
    "100 / 10 / 5", "- - 3", "-(2 + 3)", "+5", "1 + NULL", "NULL * 2", "NULL / 0",
    "9223372036854775807 + 1", "-9223372036854775808 - 1", "9223372036854775807 * 2",
    "4611686018427387904 * 2", "(-9223372036854775808) / -1", "0.1 + 0.2", "1e308 * 10",
    "'3' + 4", "'3.5' * 2", "'12abc' + 1", "'abc' + 1", "' 7 ' + 1", "'-2e2' + 0",
    "'' + 1", "5 - '2'", "'10' / '4'", "'10' % 4",
    # concatenation
    "'a' || 'b'", "'a' || 1", "1 || 2", "1.5 || 'x'", "'a' || NULL", "NULL || NULL",
    "(0.1 + 0.2) || ''", "(1.0) || ''", "(1e20) || ''", "(1e-5) || ''", "(100.0 / 3) || ''",
    "(2.0 / 3) || ''", "(1e15) || ''", "(1e16) || ''", "(1e17) || ''", "(123456.789) || ''",
    "3 || 4 + 1", "- 1 || 2",
    # comparisons
    "1 = 1", "1 == 1", "1 = 2", "1 != 2", "1 <> 1", "1 < 2", "2 <= 2", "3 > 2", "2 >= 3",
    "1 = 1.0", "1 < 1.5", "'a' < 'b'", "'a' < 'B'", "'abc' = 'ABC'", "1 < 'a'",
    "'1' = 1", "NULL = NULL", "NULL != 1", "1 < NULL", "NULL IS NULL", "1 IS NULL",
    "NULL IS NOT NULL", "1 IS NOT NULL", "1 IS 1", "1 IS NOT 2", "NULL IS 1",
    "1 < 2 = 1", "1 = 1 = 1", "2 > 1 > 0",
    # logic
    "1 AND 1", "1 AND 0", "0 AND NULL", "NULL AND 0", "1 AND NULL", "NULL AND NULL",
    "1 OR 0", "0 OR 0", "NULL OR 1", "1 OR NULL", "0 OR NULL", "NULL OR NULL",
    "NOT 1", "NOT 0", "NOT NULL", "NOT 2", "NOT 0.5", "NOT 'abc'", "NOT '1'",
    "1 OR 0 AND 0", "(1 OR 0) AND 0", "NOT 1 = 2", "NOT NULL IS NULL", "5 AND 'x'",
    # IN
    "1 IN (1, 2)", "3 IN (1, 2)", "1 IN (NULL, 1)", "3 IN (1, NULL)", "NULL IN (1, 2)",
    "NULL IN ()", "1 IN ()", "1 NOT IN ()", "3 NOT IN (1, 2)", "1 NOT IN (1, 2)",
    "3 NOT IN (1, NULL)", "NULL NOT IN (1)", "1 IN (1.0)", "'a' IN ('A', 'a')",
    "1 + 1 IN (2)",
    # BETWEEN
    "2 BETWEEN 1 AND 3", "0 BETWEEN 1 AND 3", "1 BETWEEN 1 AND 1", "2 NOT BETWEEN 1 AND 3",
    "NULL BETWEEN 1 AND 2", "2 BETWEEN NULL AND 3", "5 BETWEEN NULL AND 3",
    "2 BETWEEN 1 AND NULL", "0 BETWEEN 1 AND NULL", "5 NOT BETWEEN NULL AND 3",
    "'b' BETWEEN 'a' AND 'c'", "2 BETWEEN 1 AND 3 AND 0", "1.5 BETWEEN 1 AND 2",
    # LIKE
    "'abc' LIKE 'abc'", "'abc' LIKE 'ABC'", "'ABC' LIKE 'a%'", "'abc' LIKE '_b_'",
    "'abc' LIKE '_b'", "'abc' LIKE '%'", "'' LIKE '%'", "'' LIKE '_'", "'a%c' LIKE 'a%'",
    "'abc' NOT LIKE 'a%'", "NULL LIKE 'a'", "'a' LIKE NULL", "123 LIKE '1%'",
    "1.5 LIKE '1._'", "'x.y' LIKE 'x_y'", "'x+y' LIKE 'x+y'", "'a\nb' LIKE 'a_b'",
    "'É' LIKE 'é'", "'a[b]' LIKE 'a[b]'", "'10%' LIKE '10\\%' ESCAPE '\\'",
    "'100' LIKE '10\\%' ESCAPE '\\'",
    # CASE / CAST / functions
    "CASE WHEN 1 THEN 'a' ELSE 'b' END", "CASE WHEN NULL THEN 'a' ELSE 'b' END",
    "CASE 2 WHEN 1 THEN 'one' WHEN 2 THEN 'two' END", "CASE NULL WHEN NULL THEN 1 END",
    "CASE WHEN 0 THEN 1 END", "CAST('12abc' AS INTEGER)", "CAST(3.7 AS INTEGER)",
    "CAST(-3.7 AS INTEGER)", "CAST(5 AS REAL)", "CAST(5 AS TEXT)", "CAST(1.5 AS TEXT)",
    "CAST('abc' AS REAL)", "CAST(NULL AS INTEGER)", "CAST('3.0' AS NUMERIC)",
    "abs(-3)", "abs(-3.5)", "abs(NULL)", "length('héllo')", "length(12.5)", "length(NULL)",
    "upper('abcé')", "lower('ABC')", "coalesce(NULL, NULL, 3)", "coalesce(NULL, NULL)",
    "ifnull(NULL, 'x')", "nullif(1, 1)", "nullif(1, 2)", "typeof(1)", "typeof(1.0)",
    "typeof('a')", "typeof(NULL)", "typeof(1 / 2)", "typeof(1 / 2.0)", "min(3, 1, 2)",
    "max(3, 'a', 2)", "max(1, NULL)", "round(2.675, 2)", "round(2.5)", "round(-2.5)",
    "round(0.125, 2)", "round(5)", "round(1234.5678, 1)", "substr('hello', 2, 3)",
    "substr('hello', -3)", "substr('hello', 0, 2)", "substr('hello', 2, -1)",
    "substr('hello', 3)", "trim('  x  ')", "ltrim('xxa', 'x')", "rtrim('a  ')",
    "replace('aXbX', 'X', '-')", "instr('hello', 'll')", "instr('hello', 'z')",
    "TRUE", "FALSE", "1 & 3", "1 | 2", "1 << 3", "-16 >> 2", "~5",
]


@pytest.mark.parametrize("expr", CONSTANT_EXPRESSIONS)
def test_constant_expression(expr):
    Pair().check(f"SELECT {expr}")


COLUMN_EXPRESSIONS = [
    "i", "r", "t", "i + r", "i * 2", "i / 2", "i % 3", "r / 2", "i / 0", "r * i",
    "-i", "-r", "i || t", "r || ''", "t || i", "i = 1", "i > r", "i <> 0", "t < 'b'",
    "t = 'abc'", "t LIKE 'a%'", "t LIKE '_'", "t NOT LIKE '%b%'", "i IS NULL",
    "r IS NOT NULL", "i IN (1, 2, 3)", "i NOT IN (1, NULL)", "i BETWEEN -3 AND 3",
    "r NOT BETWEEN 0 AND 2", "i > 0 AND r > 0", "i > 0 OR r > 0", "NOT (i > 0)",
    "i IS r", "t IS NOT NULL AND i > 0", "t = 10", "t = '10'", "i = '3'", "r = '1.5'",
    "i < '5'", "t > 5", "t IN (10, 'a')", "i IN ('1', '2')", "coalesce(i, r, t)",
    "CASE WHEN i > 0 THEN 'pos' WHEN i < 0 THEN 'neg' ELSE 'zero' END",
    "CASE i WHEN 1 THEN 'one' WHEN '2' THEN 'two' END", "abs(i)", "length(t)", "upper(t)",
    "i + t", "t * 1", "typeof(i)", "typeof(r)", "typeof(t)", "i BETWEEN '0' AND '5'",
    "(i > 0) + (r > 0)", "i || '-' || r",
]


@pytest.mark.parametrize("expr", COLUMN_EXPRESSIONS)
def test_column_expression(sample, expr):
    sample.check(f"SELECT {expr} FROM nums")


@pytest.mark.parametrize("expr", COLUMN_EXPRESSIONS)
def test_column_expression_in_where(sample, expr):
    sample.check(f"SELECT i, r, t FROM nums WHERE {expr}")


def test_keywords_and_identifiers_case_insensitive(sample):
    sample.check("select NAME, Dept from EMP where DEPT = 'eng' order BY Id")
    sample.check("SeLeCt e.NaMe FrOm emp AS E wHeRe E.ID < 3 OrDeR bY e.id DeSc")


def test_quoted_identifiers():
    p = Pair('CREATE TABLE "my table" ("select" INTEGER, [b c] TEXT)')
    p.run("INSERT INTO \"my table\" VALUES (1, 'x')")
    p.check('SELECT "select", [b c] FROM "my table"')
