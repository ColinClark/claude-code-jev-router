import pytest

from .conftest import assert_matches_sqlite

SETUP = [
    "CREATE TABLE t (id INTEGER, a INTEGER, b INTEGER, r REAL, s TEXT, n INTEGER)",
    """INSERT INTO t VALUES
        (1, 5, 2, 3.5, 'Hello', NULL),
        (2, -5, 2, -3.5, 'WORLD', NULL),
        (3, 0, 0, 0.0, '', NULL)
    """,
]


@pytest.mark.parametrize(
    "expr",
    [
        "a + b",
        "a - b",
        "a * b",
        "a / b",
        "a % b",
        "-a",
        "r + a",
        "r / a",
        "a = b",
        "a != b",
        "a <> b",
        "a < b",
        "a <= b",
        "a > b",
        "a >= b",
        "a == b",
        "n IS NULL",
        "n IS NOT NULL",
        "a IS NULL",
        "n = n",
        "a AND b",
        "NOT a",
        "a > 0 AND b > 0",
        "a > 0 OR b > 0",
        "NOT (a > 0)",
        "s || '!'",
        "s || n",
        "a IN (5, -5)",
        "a NOT IN (5, -5)",
        "a BETWEEN -5 AND 5",
        "a NOT BETWEEN -5 AND 5",
        "s LIKE 'hel%'",
        "s LIKE 'HELLO'",
        "s LIKE 'h_llo'",
        "s NOT LIKE 'hel%'",
        "1/0",
        "1.0/0",
        "1%0",
        "5/2",
        "-5/2",
        "5%2",
        "-5%2",
        "-5%-2",
    ],
)
def test_expression_matches_sqlite(expr):
    assert_matches_sqlite(SETUP, f"SELECT {expr} FROM t ORDER BY id")


def test_null_in_with_null_in_list():
    setup = SETUP
    assert_matches_sqlite(setup, "SELECT a IN (n, 5) FROM t ORDER BY id")
    assert_matches_sqlite(setup, "SELECT a IN (n, -100) FROM t ORDER BY id")


def test_where_three_valued_logic():
    assert_matches_sqlite(SETUP, "SELECT id FROM t WHERE n = n ORDER BY id")
    assert_matches_sqlite(SETUP, "SELECT id FROM t WHERE NOT (n = n) ORDER BY id")
    assert_matches_sqlite(SETUP, "SELECT id FROM t WHERE a > 0 OR n IS NULL ORDER BY id")


def test_string_literal_escaping():
    setup = [
        "CREATE TABLE t (id INTEGER, s TEXT)",
        "INSERT INTO t VALUES (1, 'it''s here')",
    ]
    assert_matches_sqlite(setup, "SELECT s FROM t")


def test_like_underscore_and_percent():
    setup = [
        "CREATE TABLE t (id INTEGER, s TEXT)",
        "INSERT INTO t VALUES (1, 'cat'), (2, 'cot'), (3, 'coat'), (4, 'dog')",
    ]
    assert_matches_sqlite(setup, "SELECT s FROM t WHERE s LIKE 'c_t' ORDER BY id")
    assert_matches_sqlite(setup, "SELECT s FROM t WHERE s LIKE 'c%t' ORDER BY id")


def test_case_insensitive_keywords_and_identifiers():
    setup = [
        "create table T (Id INTEGER, Name TEXT)",
        "insert into t values (1, 'a')",
    ]
    assert_matches_sqlite(setup, "SeLeCt ID, NAME from T where ID = 1")
