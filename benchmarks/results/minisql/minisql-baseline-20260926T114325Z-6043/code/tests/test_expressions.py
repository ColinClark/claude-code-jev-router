"""Scalar expression semantics, compared against sqlite3."""

import pytest

EXPRESSIONS = [
    # integer vs real arithmetic
    "7 / 2", "-7 / 2", "7 / -2", "7.0 / 2", "7 / 2.0", "1 / 3.0", "6 / 3",
    "7 % 3", "-7 % 3", "7 % -3", "-7 % -3", "5.5 % 2", "-5.5 % 2", "5 % 2.5", "4.0 % 1.5",
    "1 / 0", "1.0 / 0", "1 % 0", "1.5 % 0", "0 / 0", "1 / 0.0",
    "2 + 3", "2 + 3.0", "2 - 3.5", "2 * 3", "2 * 3.0", "0.1 + 0.2", "1e3", ".5 + 1", "1.5e2 * 2",
    "9223372036854775807 + 1", "-9223372036854775807 - 2", "9223372036854775807 * 2",
    "9223372036854775808", "-(-9223372036854775807 - 1)",
    "-5", "- -5", "-(2 + 3)", "-2.5", "+3", "- NULL", "-'3'", "-'abc'",
    # text to number conversions
    "'3' + 4", "'3.0' + 1", "' 3 ' + 1", "'3abc' + 1", "'abc' * 2", "'1e2' + 0", "'.5' + 0",
    # NULL propagation
    "NULL + 1", "1 - NULL", "NULL * NULL", "NULL / 2", "NULL % 2", "NULL || 'a'", "'a' || NULL",
    # concatenation
    "'a' || 'b'", "1 || 2", "1.5 || 'x'", "2.0 || ''", "1e20 || ''", "1.5e-7 || ''",
    "(0.1 + 0.2) || ''", "1e15 || ''", "1e16 || ''", "1e17 || ''", "0.0001 || ''",
    "0.00001 || ''", "-0.0 || ''", "100 || 1.0", "1/3.0 || ''", "3 * 2 || 1",
    # comparisons
    "1 = 1", "1 == 1", "1 = 1.0", "1 != 2", "1 <> 1", "1 < 2", "2 <= 2", "3 > 2", "2 >= 3",
    "'a' < 'b'", "'a' < 'B'", "'abc' = 'ABC'", "'a' > 1", "1 < 'a'", "'1' = 1", "'10' < '9'",
    "NULL = NULL", "NULL != 1", "1 < NULL", "NULL IS NULL", "1 IS NULL", "NULL IS NOT NULL",
    "1 IS NOT NULL", "1 IS 1", "NULL IS 1", "1 IS NOT 2", "2 > 1 = 1", "1 < 2 < 3",
    # logic
    "1 AND 1", "1 AND 0", "1 AND NULL", "0 AND NULL", "NULL AND NULL", "NULL AND 0",
    "1 OR NULL", "0 OR NULL", "NULL OR NULL", "0 OR 0", "NULL OR 1", "NOT 1", "NOT 0",
    "NOT NULL", "NOT 'abc'", "NOT '1x'", "NOT 0.5", "1 OR 0 AND 0", "NOT 1 = 2",
    "NOT NULL IS NULL", "2 AND 3", "0.0 OR 0",
    # IN
    "1 IN (1, 2)", "3 IN (1, 2)", "1 IN (NULL, 1)", "3 IN (NULL, 1)", "NULL IN (1, 2)",
    "NULL IN ()", "1 IN ()", "1 NOT IN ()", "3 NOT IN (1, 2)", "1 NOT IN (1, NULL)",
    "3 NOT IN (1, NULL)", "'1' IN (1)", "1 IN ('1')", "1.0 IN (1)", "2 IN (1 + 1, 5)",
    # BETWEEN
    "2 BETWEEN 1 AND 3", "0 BETWEEN 1 AND 3", "1 BETWEEN 1 AND 1", "2 NOT BETWEEN 1 AND 3",
    "NULL BETWEEN 1 AND 2", "1 BETWEEN NULL AND 2", "5 BETWEEN NULL AND 2",
    "1 BETWEEN 2 AND NULL", "5 NOT BETWEEN NULL AND 2", "'b' BETWEEN 'a' AND 'c'",
    "2 BETWEEN 1 AND 3 AND 0", "1.5 BETWEEN 1 AND 2",
    # LIKE
    "'abc' LIKE 'abc'", "'abc' LIKE 'ABC'", "'ABC' LIKE 'a%'", "'abc' LIKE 'a_c'",
    "'abc' LIKE '_'", "'abc' LIKE '%'", "'' LIKE '%'", "'' LIKE '_'", "'abc' LIKE '%c'",
    "'abc' NOT LIKE '%b%'", "NULL LIKE 'a'", "'a' LIKE NULL", "10 LIKE '1%'", "1.5 LIKE '1._'",
    "'Ä' LIKE 'ä'", "'ä' LIKE 'ä'", "'a.c' LIKE 'a.c'", "'abc' LIKE 'a.c'", "'a*' LIKE 'a*'",
    "'a\nb' LIKE 'a_b'", "'100%' LIKE '100\\%' ESCAPE '\\'", "'1000' LIKE '100\\%' ESCAPE '\\'",
    "'ab' LIKE 'a' || '%'",
    # precedence
    "1 + 2 * 3", "(1 + 2) * 3", "10 - 2 - 3", "2 * 3 % 4", "1 + 2 || 3", "'1' || 2 * 3",
    "- 2 || 3", "1 < 2 = 1", "1 = 1 AND 2 = 2 OR 0", "NOT 0 AND 0", "1 + 1 IN (2)",
    "1 + 1 BETWEEN 1 + 1 AND 3", "2 * 3 || ''",
]  # fmt: skip


@pytest.mark.parametrize("expr", EXPRESSIONS)
def test_scalar_expression(both, expr):
    both.check(f"SELECT {expr}")


COLUMN_EXPRESSIONS = [
    "i = '5'", "i = 5.0", "i < '10'", "t = 5", "t < 10", "t = '5'", "r = '2.5'", "r = 2",
    "i IN ('5', 7)", "t IN (5, 7)", "i BETWEEN '4' AND '6'", "t BETWEEN 4 AND 6",
    "i = t", "i < t", "r = t", "i || t", "i + t", "t * 2", "r / i", "i / r", "i % 3", "r % 2",
    "t LIKE '5%'", "i LIKE '5'", "r LIKE '2.5'", "i IS '5'", "t IS 5",
]  # fmt: skip


@pytest.mark.parametrize("expr", COLUMN_EXPRESSIONS)
def test_column_affinity_in_expressions(both, expr):
    both.run(
        "CREATE TABLE a (i INTEGER, r REAL, t TEXT)",
        "INSERT INTO a VALUES (5, 2.5, '5'), (7, 2.0, '10'), (NULL, NULL, NULL), (0, 0.0, 'x')",
    )
    both.check(f"SELECT i, {expr} FROM a ORDER BY i")
