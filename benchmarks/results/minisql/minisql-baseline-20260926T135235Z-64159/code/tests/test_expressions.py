"""Scalar expression semantics, compared value-for-value (and type) against sqlite3."""

import sqlite3

import pytest

from minisql.values import format_real

SETUP = [
    "CREATE TABLE t (i INTEGER, r REAL, s TEXT)",
    "INSERT INTO t VALUES (7, 2.5, 'Abc'), (-7, -0.5, 'abc%'), (0, 0.0, ''), "
    "(NULL, NULL, NULL), (3, 1e20, '12'), (9223372036854775807, 3.0, '3.5x')",
]

# fmt: off
EXPRESSIONS = [
    # literals
    "1", "-1", "1.5", ".5", "1e3", "1E-2", "'x'", "NULL", "9223372036854775807",
    "-9223372036854775808", "9223372036854775808", "0.1 + 0.2",
    # arithmetic
    "i + 1", "i - 1", "i * 2", "i / 2", "i % 3", "i / 0", "i % 0", "r / 0", "r % 0",
    "7 / 2", "-7 / 2", "7 / -2", "7 % 3", "-7 % 3", "7 % -3", "7.0 / 2", "7 / 2.0",
    "5.5 % 2", "-5.5 % 2", "5 % 2.5", "5.0 % 0.5", "i + r", "i * r", "r - i",
    "i + NULL", "NULL * 2", "NULL / 0", "i + s", "s * 2", "s + 0", "'3abc' + 1",
    "'1e2' + 0", "' 12 ' + 0", "'abc' * 1", "i + 9223372036854775807", "-i", "- - i",
    "-s", "-NULL", "+s", "i * 9223372036854775807", "(i + 1) * 2", "i + 1 * 2",
    "1 - 2 - 3", "12 / 3 / 2", "2 * 3 % 4",
    # concatenation
    "s || 'x'", "i || s", "r || ''", "i || NULL", "NULL || 'a'", "1.0 || ''",
    "1e20 || ''", "0.5 || ''", "-0.0 || ''", "i || r || s", "1 + 2 || 3", "'a' || 1 + 2",
    "(0.1 + 0.2) || ''", "100.0 || ''", "1e-5 || ''", "123.456 || ''",
    # comparisons
    "i = 7", "i == 7", "i != 7", "i <> 7", "i < 3", "i <= 3", "i > 3", "i >= 3",
    "i = NULL", "NULL = NULL", "NULL <> 1", "i = r", "i < r", "s = 'abc'", "s < 'b'",
    "s > 'B'", "1 < 'a'", "'a' < 1", "1 = '1'", "i = '7'", "s = 12", "s = '12'",
    "r = '2.5'", "1 = 1.0", "2 > 1 = 1", "i = 7 = 1", "'abc' = 'ABC'", "'' < 'a'",
    "i IS NULL", "i IS NOT NULL", "s IS NULL", "NULL IS NULL", "i IS 7", "i IS NOT 7",
    "NULL IS NOT NULL", "i ISNULL", "i NOTNULL", "i NOT NULL", "i IS r",
    # logic
    "i > 0 AND r > 0", "i > 0 OR r > 0", "NOT i", "NOT r", "NOT s", "NOT NULL",
    "NULL AND 0", "NULL AND 1", "NULL OR 1", "NULL OR 0", "0 AND NULL", "1 OR NULL",
    "NULL AND NULL", "NOT (i > 0)", "NOT i > 0", "i AND s", "s OR 0", "'1x' AND 1",
    "0.5 AND 1", "NOT 0.0", "1 OR 0 AND 0", "(1 OR 0) AND 0", "NOT 1 = 2",
    # IN
    "i IN (7, 3)", "i NOT IN (7, 3)", "i IN (NULL, 7)", "i NOT IN (NULL, 7)",
    "i IN (1, NULL)", "i NOT IN (1, NULL)", "NULL IN (1, 2)", "NULL IN ()", "i IN ()",
    "i NOT IN ()", "s IN ('abc', '12')", "s IN (12)", "i IN ('7')", "i IN (7.0)",
    "i IN (i, r)", "r IN (2.5, 3)",
    # BETWEEN
    "i BETWEEN 0 AND 7", "i NOT BETWEEN 0 AND 7", "i BETWEEN NULL AND 7",
    "i BETWEEN 8 AND NULL", "i NOT BETWEEN 8 AND NULL", "r BETWEEN -1 AND 3",
    "s BETWEEN 'a' AND 'b'", "i BETWEEN 1 AND 2 + 5", "5 BETWEEN 1 AND 10 AND 0",
    "i BETWEEN '0' AND '8'",
    # LIKE
    "s LIKE 'abc'", "s LIKE 'ABC'", "s LIKE 'a%'", "s LIKE '%c'", "s LIKE '_bc'",
    "s LIKE '%'", "s LIKE '_'", "s LIKE ''", "s NOT LIKE 'a%'", "s LIKE NULL",
    "NULL LIKE 'a'", "i LIKE '7'", "i LIKE '-%'", "r LIKE '2.%'", "s LIKE 'abc_'",
    "s LIKE '%\\%'", "'a.c' LIKE 'a_c'", "'abc' LIKE 'a.c'", "'aXc' LIKE 'a[X]c'",
    "'ÄBC' LIKE 'äbc'", "'A\nB' LIKE 'a_b'", "s LIKE '%b%' AND i > 0",
    "s NOT LIKE NULL",
    # CASE / CAST / functions (extras)
    "CASE WHEN i > 0 THEN 'pos' WHEN i < 0 THEN 'neg' ELSE 'zero' END",
    "CASE i WHEN 7 THEN 'seven' WHEN NULL THEN 'null' END",
    "CAST(s AS INTEGER)", "CAST(r AS INTEGER)", "CAST(i AS TEXT)", "CAST(i AS REAL)",
    "CAST(s AS REAL)", "coalesce(i, r, s)", "ifnull(s, 'none')", "abs(i)", "abs(r)",
    "length(s)", "upper(s)", "lower(s)", "nullif(i, 7)", "typeof(i / 2)", "typeof(r)",
    "substr(s, 2)", "substr(s, 1, 2)", "substr(s, -2)", "round(r)", "round(r, 1)",
    "max(i, 1)", "min(i, 1)",
]
# fmt: on


@pytest.fixture
def epair(pair):
    pair.run(*SETUP)
    return pair


# minisql renders REAL as text like SQLite 3.47 ("%!.15g"); newer SQLite releases emit up to
# 17 digits for values that do not round-trip at 15, so skip those cases against them.
LEGACY_REAL_TEXT = sqlite3.connect(":memory:").execute("SELECT (0.1 + 0.2) || ''").fetchone()[0]
FIFTEEN_DIGIT_HOST = LEGACY_REAL_TEXT == "0.3"


@pytest.mark.parametrize("expr", EXPRESSIONS)
def test_expression_over_table(epair, expr):
    if "0.1 + 0.2" in expr and "||" in expr and not FIFTEEN_DIGIT_HOST:
        pytest.skip("host SQLite uses a different REAL-to-text format")
    epair.check(f"SELECT {expr} FROM t", ordered=False)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (0.1 + 0.2, "0.3"),
        (2 / 3, "0.666666666666667"),
        (1.0, "1.0"),
        (-2.5, "-2.5"),
        (100.0, "100.0"),
        (1e15, "1.0e+15"),
        (1e14, "100000000000000.0"),
        (1e20, "1.0e+20"),
        (1e-5, "1.0e-05"),
        (0.0001, "0.0001"),
        (123456789012345.6, "123456789012346.0"),
        (434306.5267350215, "434306.526735022"),
        (1.7976931348623157e308, "1.79769313486232e+308"),
        (5e-324, "4.94065645841247e-324"),
        (-0.0, "0.0"),
        (float("inf"), "Inf"),
    ],
)
def test_real_to_text_matches_sqlite_3_47(value, text):
    assert format_real(value) == text


@pytest.mark.parametrize("expr", EXPRESSIONS)
def test_expression_in_where(epair, expr):
    epair.check(f"SELECT i, r, s FROM t WHERE {expr}", ordered=False)


def test_numeric_types(db):
    assert db.execute("SELECT 7 / 2, 7.0 / 2, 7 % 3, 1 / 0, 2 * 1.5") == [(3, 3.5, 1, None, 3.0)]
    (row,) = db.execute("SELECT 6 / 3, 6.0 / 3")
    assert type(row[0]) is int and type(row[1]) is float
