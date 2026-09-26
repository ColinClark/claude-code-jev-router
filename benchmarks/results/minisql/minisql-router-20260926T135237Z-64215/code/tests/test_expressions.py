"""Differential tests of scalar expression semantics against sqlite3."""

import pytest

LITERAL_EXPRS = [
    # literals
    "1", "-1", "+1", "1.5", "-2.5", "'abc'", "'it''s'", "''", "NULL", "1e3", "1E-2", ".5", "5.",
    "9223372036854775807", "9223372036854775808", "-9223372036854775808", "0x1F",
    # arithmetic
    "1 + 2", "7 - 10", "6 * 7", "7 / 2", "-7 / 2", "7 / -2", "-7 / -2", "7 % 3", "-7 % 2",
    "7 % -2", "-7 % -2", "7.0 / 2", "7 / 2.0", "1 / 0", "1 % 0", "1.0 / 0", "1.5 % 0",
    "0 / 0", "5.5 % 2", "-5.5 % 2", "5.5 % 0.5", "10 % 3.5", "1e19 % 3",
    "9223372036854775807 + 1", "-9223372036854775808 - 1", "9223372036854775807 * 2",
    "-9223372036854775808 / -1", "-9223372036854775808 % -1", "4611686018427387904 * 2",
    "1e308 * 10", "-1e308 * 10", "0.1 + 0.2", "1 + 2 * 3", "(1 + 2) * 3", "2 * 3 % 4",
    "10 - 2 - 3", "100 / 10 / 5", "- - 3", "-(-3)", "- 'abc'", "- '12x'", "+ 'abc'",
    "1 + NULL", "NULL * 2", "-NULL", "NULL / 0",
    # text arithmetic
    "'12abc' + 0", "'abc' + 1", "'1.5x' * 2", "' 12 ' + 0", "'1e3' + 0", "'1.0' + 0",
    "'-' + 0", "'.5' + 0", "'5.' + 0", "'0x10' + 0", "'9223372036854775808' + 0", "'1e' + 0",
    "'3' * '4'", "'10' / '4'", "'10.0' / '4'", "'7' % '3'",
    # concatenation
    "'a' || 'b'", "1 || 2", "1.0 || ''", "2 || 'a'", "0.1 || ''", "1e20 || ''",
    "1.5e-7 || ''", "123456789012345678.0 || ''", "1e16 || ''", "1e17 || ''", "1e-4 || ''",
    "1e-5 || ''", "-0.0 || ''", "(0.1 + 0.2) || ''", "0.1 + 0.2 || ''", "'a' || NULL",
    "NULL || 'a'", "'a' || 1 + 2", "-1 || 2", "1e100 || ''", "-1.5 || 'x'",
    "123.456 || ''", "100.0 || ''", "(1e308 * 10) || ''", "(-1e308 * 10) || ''",
    # comparisons
    "1 = 1", "1 == 1", "1 = 2", "1 != 2", "1 <> 1", "1 < 2", "2 <= 2", "3 > 2", "2 >= 3",
    "1 = 1.0", "1 < 1.5", "'a' < 'b'", "'a' < 'B'", "'abc' = 'ABC'", "1 < 'a'", "'a' > 99999",
    "'5' = 5", "'5' > 5", "5 < '4'", "NULL = NULL", "NULL = 1", "1 != NULL", "NULL < 1",
    "1 = 1 = 1", "2 < 3 < 1", "1 < 2 = 1", "1 = 2 < 3", "3 BETWEEN 1 AND 5 = 1",
    "1 IS 1", "1 IS NULL", "NULL IS NULL", "NULL IS NOT NULL", "1 IS NOT NULL", "1 IS NOT 2",
    "NULL IS 1", "1 IS 1.0", "'a' IS 'a'", "1 ISNULL", "NULL NOTNULL", "NULL NOT NULL",
    # logic
    "1 AND 1", "1 AND 0", "0 AND NULL", "NULL AND 0", "NULL AND 1", "1 AND NULL", "NULL AND NULL",
    "1 OR 0", "0 OR 0", "NULL OR 1", "1 OR NULL", "NULL OR 0", "0 OR NULL", "NULL OR NULL",
    "NOT 1", "NOT 0", "NOT NULL", "NOT 'abc'", "NOT '1abc'", "NOT 0.5", "NOT NOT 5",
    "'abc' AND 1", "'1' AND 1", "0.0 OR 0.5", "NOT 1 = 2", "NOT 1 AND 0", "1 OR 0 AND 0",
    "(1 OR 0) AND 0", "NOT NULL IS NULL",
    # IN
    "1 IN (1, 2)", "3 IN (1, 2)", "NULL IN (1, 2)", "1 IN (2, NULL)", "1 IN (1, NULL)",
    "1 NOT IN (2, NULL)", "1 NOT IN (1, NULL)", "3 NOT IN (1, 2)", "NULL NOT IN (1)",
    "1 IN ()", "NULL IN ()", "NULL NOT IN ()", "'1' IN (1)", "1 IN ('1')", "1.0 IN (1)",
    "'a' IN ('A', 'a')", "1 + 1 IN (2)", "(1 IN (1)) + 1",
    # BETWEEN
    "2 BETWEEN 1 AND 3", "0 BETWEEN 1 AND 3", "1 BETWEEN 1 AND 1", "2 NOT BETWEEN 1 AND 3",
    "NULL BETWEEN 1 AND 3", "2 BETWEEN NULL AND 3", "5 BETWEEN NULL AND 3",
    "2 BETWEEN 1 AND NULL", "0 BETWEEN 1 AND NULL", "2 NOT BETWEEN NULL AND 1",
    "'b' BETWEEN 'a' AND 'c'", "2 BETWEEN 3 AND 1", "1.5 BETWEEN 1 AND 2",
    "1 BETWEEN 0 AND 2 AND 0", "1 + 1 BETWEEN 1 + 0 AND 1 + 1",
    # LIKE
    "'abc' LIKE 'abc'", "'abc' LIKE 'ABC'", "'ABC' LIKE 'a%'", "'abc' LIKE 'a_c'",
    "'abc' LIKE 'a_'", "'abc' LIKE '%'", "'' LIKE '%'", "'' LIKE '_'", "'abc' LIKE '%c'",
    "'abc' LIKE '%b%'", "'abc' NOT LIKE '%b%'", "NULL LIKE 'a'", "'a' LIKE NULL",
    "'ä' LIKE 'Ä'", "'ä' LIKE 'ä'", "5 LIKE 5", "1.0 LIKE '1.0'", "'a.c' LIKE 'a.c'",
    "'abc' LIKE 'a.c'", "'a*c' LIKE 'a*c'", "'line1\nline2' LIKE 'line1%'",
    "'10%' LIKE '10\\%' ESCAPE '\\'", "'100' LIKE '10\\%' ESCAPE '\\'",
    "'a' LIKE 'a' = 1", "'ab' LIKE 'a' || '%'",
    # precedence mix
    "1 + 2 || 3", "2 * 3 || 4", "'1' || '2' * 3", "1 < 2 AND 2 < 3", "1 = 1 OR 1 / 0",
    "1 + 2 = 3 AND NOT 0", "-2 * -3", "- 2 || 3", "1 - -1", "5 - 3 - 1", "2 + 3 * 4 - 5 / 2",
    "1 IS NULL = 0", "1 < 2 IS 1",
    # CASE / CAST / functions (nice-to-haves)
    "CASE WHEN 1 THEN 'a' ELSE 'b' END", "CASE WHEN NULL THEN 'a' ELSE 'b' END",
    "CASE 2 WHEN 1 THEN 'one' WHEN 2 THEN 'two' END", "CASE NULL WHEN NULL THEN 1 ELSE 0 END",
    "CASE WHEN 0 THEN 1 END", "CAST('12' AS INTEGER)", "CAST(12.7 AS INTEGER)",
    "CAST(-12.7 AS INTEGER)", "CAST(3 AS REAL)", "CAST(3 AS TEXT)", "CAST(2.0 AS TEXT)",
    "CAST(NULL AS TEXT)", "CAST('abc' AS INTEGER)", "CAST('1.5' AS REAL)",
    "abs(-5)", "abs(-5.5)", "abs(NULL)", "length('abc')", "length(12)", "upper('abc')",
    "lower('ABC')", "upper('äb')", "coalesce(NULL, NULL, 3)", "coalesce(NULL, NULL)",
    "ifnull(NULL, 'x')", "nullif(1, 1)", "nullif(1, 2)", "typeof(1)", "typeof(1.0)",
    "typeof('a')", "typeof(NULL)", "round(2.5)", "round(-2.5)", "round(1.2345, 2)",
    "round(0.5)", "substr('hello', 2, 3)", "substr('hello', -3)", "substr('hello', 0, 2)",
    "min(3, 1, 2)", "max(3, 'a', 2)", "max(1, NULL)", "instr('hello', 'l')",
    "trim('  x  ')", "replace('aaa', 'a', 'bb')",
]


@pytest.mark.parametrize("expr", LITERAL_EXPRS)
def test_literal_expression(pair, expr):
    pair.check(f"SELECT {expr}")


COLUMN_EXPRS = [
    "i", "r", "t", "n", "i + r", "i * 2", "i / 2", "i % 3", "r / 0", "t || i", "i || t",
    "i = 1", "i = '1'", "i = '1.0'", "r = '2'", "r = 2", "t = 1", "t = '1'", "t > 5",
    "t < 10", "n = 1", "n = '1'", "i < '10'", "i IN ('1', 2)", "t IN (1, 2)", "i IN (t)",
    "i BETWEEN '0' AND '2'", "t BETWEEN 1 AND 3", "i IS NULL", "t IS NOT NULL", "NOT i",
    "i AND r", "i OR t", "t LIKE '1%'", "i LIKE '1%'", "-i", "-t", "i + t", "t * 1",
    "i = r", "i = t", "t = r", "i > t", "CASE i WHEN '1' THEN 'x' ELSE 'y' END",
    "i IS '1'", "t IS 1", "+i = '1'", "i = +'1'", "i IN (+'1')", "coalesce(i, r, t)",
]


@pytest.mark.parametrize("expr", COLUMN_EXPRS)
def test_column_expression(pair, expr):
    pair.run(
        "CREATE TABLE v (id INTEGER, i INTEGER, r REAL, t TEXT, n)",
        "INSERT INTO v VALUES (1, 1, 2.0, '1', 1), (2, NULL, NULL, NULL, NULL), "
        "(3, 10, 2.5, '10', '1'), (4, -3, 0.0, 'abc', 'x'), (5, 0, -1.5, '2.0', 2.5), "
        "(6, 2, 1e20, '', 1.0)",
    )
    pair.check(f"SELECT id, {expr} FROM v ORDER BY id")
    pair.check(f"SELECT id FROM v WHERE {expr} ORDER BY id")


@pytest.mark.parametrize(
    "expr",
    ["5 BETWEEN NOT 0 AND 7", "5 BETWEEN 1 = 1 AND 7", "2 BETWEEN 1 IS 1 AND 3",
     "5 BETWEEN 0 AND 3 OR 1", "-0.0", "-(0.0)", "-(-0.0)", "-'0.0'", "0.0 * -1",
     "1 = 2 != 3", "1 IS NOT 2 = 1", "- 7 % '1e1'"],
)
def test_precedence_edge_cases(pair, expr):
    pair.check(f"SELECT {expr}")


def test_between_rejects_bare_or_in_middle(pair):
    pair.check_error("SELECT 5 BETWEEN 1 OR 0 AND 7")


def test_real_to_text_full_precision(pair):
    from minisql import values

    if values.REAL_TEXT_MODE == "roundtrip":
        pytest.skip(
            "SQLite >= 3.51 renders 17 significant digits with its own decimal conversion "
            "whose last digit can differ from correctly rounded output (known divergence)"
        )
    pair.check("SELECT (1/3.0) || '', (2/3.0) || '', CAST(1e300/7 AS TEXT)")
