"""Scalar expression semantics compared against sqlite3."""

import pytest

EXPRESSIONS = [
    # literals
    "1", "-1", "1.5", ".5", "5.", "1e3", "1.5e-3", "'abc'", "'it''s'", "''", "NULL",
    "9223372036854775807", "-9223372036854775808", "9223372036854775808", "0x1F",
    # integer vs real arithmetic
    "7 / 2", "-7 / 2", "7 / -2", "-7 / -2", "7 / 2.0", "7.0 / 2", "6 / 3", "1 / 3.0",
    "7 % 3", "-7 % 3", "7 % -3", "-7 % -3", "7.5 % 2", "5 % 2.5", "-7.9 % 2", "7 % 0.5",
    "7 / 0", "7 % 0", "7.0 / 0", "7 / 0.0", "0 / 0", "7.5 % 0",
    "1 + 2", "1 + 2.0", "3 - 5", "2 * 3", "2 * 3.5", "0.1 + 0.2", "1 - 1.0",
    "9223372036854775807 + 1", "-9223372036854775808 - 1", "9223372036854775807 * 2",
    "-9223372036854775808 / -1", "-9223372036854775808 % -1", "- -9223372036854775808",
    "1e308 * 10", "-1e308 * 10",
    "2 + 3 * 4", "(2 + 3) * 4", "10 - 4 - 3", "100 / 10 / 5", "2 * 3 % 4", "-2 * -3",
    "- (3)", "-(-3)", "- 2.5", "+5", "- 'abc'", "- '3'", "- '3.5'", "-NULL",
    # text in arithmetic
    "'12abc' + 0", "'1.5x' + 1", "' 12 ' + 0", "'1e3' + 0", "'abc' * 2", "'5.' + 0",
    "'-' + 0", "'.5' + 0", "'0x10' + 0", "'10' / '3'", "'10' / '4.0'", "'7' % '3'",
    # NULL propagation
    "NULL + 1", "1 - NULL", "NULL * NULL", "NULL / 0", "5 % NULL", "NULL || 'a'", "-NULL",
    # concatenation
    "'a' || 'b'", "'a' || 1", "1 || 2", "1.5 || 'x'", "1.0 || ''", "100.0 || ''", "1e20 || ''",
    "0.1 || ''", "1e-5 || ''", "1e17 || ''",
    "-0.0 || ''", "'x' || NULL || 'y'", "1 + 2 || 3", "-1 || 2",
    # comparisons
    "1 = 1", "1 = 1.0", "1 == 2", "1 != 2", "1 <> 1", "1 < 2", "2 <= 2", "3 > 2", "2 >= 3",
    "'a' = 'a'", "'a' = 'A'", "'a' < 'b'", "'B' < 'a'", "'abc' < 'abd'", "'' < 'a'",
    "1 < 'a'", "'a' > 99999", "'1' = 1", "1 = '1'", "'10' < '9'", "NULL = NULL", "NULL != 1",
    "1 < NULL", "NULL IS NULL", "1 IS NULL", "NULL IS NOT NULL", "1 IS NOT NULL",
    "1 IS 1", "NULL IS 1", "1 IS NOT 1", "NULL IS NOT NULL", "'a' IS 'a'",
    "1 = 1 = 1", "2 = 2 = 2", "1 < 2 = 1",
    # boolean logic and three-valued logic
    "1 AND 1", "1 AND 0", "0 AND NULL", "NULL AND 0", "1 AND NULL", "NULL AND NULL",
    "1 OR 0", "0 OR 0", "0 OR NULL", "NULL OR 1", "1 OR NULL", "NULL OR NULL",
    "NOT 1", "NOT 0", "NOT NULL", "NOT 'abc'", "NOT '1abc'", "NOT 0.5", "NOT -1",
    "'abc' AND 1", "'1' AND 1", "0.0 OR 0", "NOT 1 = 2", "NOT (1 = 2)", "1 OR 0 AND 0",
    "(1 OR 0) AND 0", "NOT 0 AND 0", "NOT NULL OR 1", "NOT NULL AND 0",
    # IN
    "1 IN (1, 2, 3)", "4 IN (1, 2, 3)", "NULL IN (1, 2)", "1 IN (NULL, 1)", "2 IN (NULL, 1)",
    "2 NOT IN (NULL, 1)", "1 NOT IN (NULL, 1)", "3 NOT IN (1, 2)", "NULL NOT IN (1)",
    "1 IN ()", "NULL IN ()", "NULL NOT IN ()", "'1' IN (1, 2)", "1 IN ('1', 2)", "1.0 IN (1)",
    "'a' IN ('A', 'a')", "1 + 1 IN (2)", "2 IN (1 + 1, 3)",
    # BETWEEN
    "2 BETWEEN 1 AND 3", "0 BETWEEN 1 AND 3", "1 BETWEEN 1 AND 1", "NULL BETWEEN 1 AND 3",
    "2 BETWEEN NULL AND 3", "5 BETWEEN NULL AND 3", "2 BETWEEN 1 AND NULL", "0 BETWEEN 1 AND NULL",
    "2 NOT BETWEEN 1 AND 3", "5 NOT BETWEEN 1 AND 3", "NULL NOT BETWEEN 1 AND 3",
    "5 NOT BETWEEN NULL AND 3", "'b' BETWEEN 'a' AND 'c'", "2.5 BETWEEN 2 AND 3",
    "3 BETWEEN 3 AND 2", "1 BETWEEN 0 AND 2 AND 0", "1 BETWEEN 0 AND 2 = 1",
    # LIKE
    "'abc' LIKE 'abc'", "'abc' LIKE 'ABC'", "'ABC' LIKE 'abc'", "'abc' LIKE 'a%'",
    "'abc' LIKE '%c'", "'abc' LIKE '%b%'", "'abc' LIKE 'a_c'", "'abc' LIKE 'a_'", "'abc' LIKE '%'",
    "'' LIKE '%'", "'' LIKE '_'", "'abc' LIKE '___'", "'abc' NOT LIKE 'a%'", "'abc' NOT LIKE 'x%'",
    "NULL LIKE 'a'", "'a' LIKE NULL", "NULL NOT LIKE 'a'", "123 LIKE '1%'", "1.5 LIKE '1._'",
    "'a.c' LIKE 'a.c'", "'abc' LIKE 'a.c'", "'a*c' LIKE 'a*c'", "'a+b' LIKE 'a+b'",
    "'ä' LIKE 'Ä'", "'É' LIKE 'é'", "'straße' LIKE 'STRASSE'", "'line1\nline2' LIKE 'line1_line2'",
    "'50%' LIKE '50\\%' ESCAPE '\\'", "'50x' LIKE '50\\%' ESCAPE '\\'", "'a_b' LIKE 'a|_b' ESCAPE '|'",
    "'Hello World' LIKE 'hello%WORLD'", "'[a]' LIKE '[a]'", "'x' LIKE 'x%%'",
    # CASE / CAST / scalar functions (extras)
    "CASE WHEN 1 THEN 'y' ELSE 'n' END", "CASE WHEN NULL THEN 'y' ELSE 'n' END",
    "CASE 2 WHEN 1 THEN 'a' WHEN 2 THEN 'b' END", "CASE NULL WHEN NULL THEN 1 ELSE 0 END",
    "CASE 3 WHEN 1 THEN 'a' END", "CAST('12abc' AS INTEGER)", "CAST(3.9 AS INTEGER)",
    "CAST(-3.9 AS INTEGER)", "CAST(5 AS REAL)", "CAST(5 AS TEXT)", "CAST(2.50 AS TEXT)",
    "CAST(NULL AS TEXT)", "CAST('abc' AS REAL)", "CAST('3.0' AS NUMERIC)",
    "abs(-3)", "abs(-3.5)", "abs(NULL)", "abs('-2')", "coalesce(NULL, NULL, 3)", "ifnull(NULL, 'x')",
    "nullif(1, 1)", "nullif(1, 2)", "length('hello')", "length(12.5)", "length(NULL)",
    "upper('abcÄ')", "lower('ABC')", "typeof(1)", "typeof(1.0)", "typeof('a')", "typeof(NULL)",
    "typeof(7 / 2)", "typeof(7 / 2.0)", "typeof('3' + 1)", "max(1, 2, 3)", "min(1, 'a', 2.5)",
    "max(1, NULL)",
]


@pytest.mark.parametrize("expr", EXPRESSIONS)
def test_expression_matches_sqlite(pair, expr):
    pair.check(f"SELECT {expr}")


COLUMN_EXPRESSIONS = [
    "i + r", "i * 2", "i / 2", "i % 3", "r / 2", "t || i", "i || t", "i = 1", "i = '1'",
    "t = 1", "t = '1'", "r = 1", "r = '1.0'", "t < 5", "i < '5'", "t IN (1, 2)", "i IN ('1', 2)",
    "i BETWEEN '0' AND '2'", "t BETWEEN 0 AND 5", "t LIKE '1%'", "i LIKE '1%'", "r LIKE '1.%'",
    "i IS NULL", "t IS NOT NULL", "NOT i", "i AND t", "i OR r", "-i", "-r", "i IS r",
    "i = t", "i < t", "r = t", "t = i", "t || NULL", "i + NULL", "i IN (NULL, 1)",
    "CASE i WHEN '1' THEN 'one' ELSE 'other' END", "i > 1 AND t < 'x'",
]


@pytest.mark.parametrize("expr", COLUMN_EXPRESSIONS)
def test_column_expression_matches_sqlite(pair, expr):
    pair.run(
        "CREATE TABLE v (i INTEGER, r REAL, t TEXT)",
        "INSERT INTO v VALUES (1, 1.0, '1'), (2, 2.5, '2'), (NULL, NULL, NULL), (-3, -0.5, 'abc')",
        "INSERT INTO v VALUES (10, 10.0, '10'), (0, 0.0, ''), (5, 1e20, '1.5')",
    )
    pair.check(f"SELECT i, r, t, {expr} FROM v")


def test_integer_overflow_in_sum_raises(pair):
    from minisql import SQLError

    pair.run("CREATE TABLE big (x INTEGER)", "INSERT INTO big VALUES (9223372036854775807), (1)")
    with pytest.raises(SQLError):
        pair.db.execute("SELECT sum(x) FROM big")
    # total() and avg() never overflow
    pair.check("SELECT total(x), avg(x) FROM big")


def test_real_formatting_matches_sqlite(pair):
    import random

    # minisql renders REAL as text with SQLite's classic "%!.15g" format. Some newer SQLite
    # builds switched to a different algorithm; only compare against a classic-format build.
    if pair.lite.execute("SELECT (1.0 / 3) || ''").fetchone()[0] != "0.333333333333333":
        pytest.skip("this sqlite3 build uses a different REAL-to-TEXT format")

    rng = random.Random(1234)
    values = [0.5, 123.456, 1 / 7, 2 / 3, 1e-4, 1.5e-5, 9.99e16, 1e17 - 16, 123456789012345.6,
              1e15 + 0.3, 5e-324, 1.7976931348623157e308, 4.35, 2.675, 1.005, 100.0, 1e21]
    for _ in range(400):
        kind = rng.randrange(4)
        if kind == 0:
            values.append(rng.uniform(-1e6, 1e6))
        elif kind == 1:
            values.append(rng.random() * 10 ** rng.randint(-10, 25))
        elif kind == 2:
            values.append(round(rng.uniform(-1000, 1000), rng.randint(0, 6)))
        else:
            values.append(float(rng.randint(-(10**18), 10**18)))
    for v in values:
        pair.check(f"SELECT {v!r} || ''")
