"""SQLite extensions and quirks beyond the core grammar, compared against sqlite3."""

import pytest

from minisql import SQLError


@pytest.fixture
def g(both):
    both.run(
        "CREATE TABLE g (k INTEGER, a INTEGER, b REAL, c TEXT)",
        """INSERT INTO g VALUES (1, 10, 1.0, 'p'), (2, 20, 5.0, NULL), (1, 30, 3.0, 'q'),
           (2, 40, NULL, 'r'), (1, 50, 2.0, 'o'), (3, 60, NULL, NULL)""",
    )
    return both


@pytest.mark.parametrize(
    "sql",
    [
        # bare columns in aggregate queries
        "SELECT a, COUNT(*) FROM g",
        "SELECT k, a, COUNT(*) FROM g GROUP BY k",
        "SELECT a, MAX(b) FROM g",
        "SELECT a, MIN(b) FROM g",
        "SELECT k, a, MAX(b) FROM g GROUP BY k",
        "SELECT k, a, c, MIN(c) FROM g GROUP BY k",
        "SELECT a, MAX(b), MIN(b) FROM g",
        "SELECT a, MIN(b), MAX(b) FROM g",
        "SELECT k, a, MAX(b) FROM g GROUP BY k HAVING MAX(b) > 0 ORDER BY a",
        "SELECT a, SUM(b) FROM g WHERE a > 15",
        "SELECT a, COUNT(*) FROM g WHERE 0",
        "SELECT a FROM g GROUP BY 1.5",
        # duplicate aggregate expressions share one accumulator
        "SELECT k, MAX(b), max(b) + 1 FROM g GROUP BY k HAVING MAX(b) > 1 ORDER BY MAX(b)",
        # HAVING with aggregates only in HAVING
        "SELECT COUNT(*) FROM g GROUP BY k HAVING SUM(a) > 50",
        "SELECT COUNT(*) FROM g HAVING a > 1",
        # scalar functions
        "SELECT MIN(a, b), MAX(a, b, k), MIN(c, 'q'), MAX(1, NULL) FROM g",
        "SELECT ABS(-a), ABS(b - 3), ABS(NULL), ABS('-2') FROM g",
        "SELECT COALESCE(c, b, 'none'), IFNULL(b, -1), NULLIF(k, 1), NULLIF(c, 'p') FROM g",
        "SELECT LENGTH(c), LENGTH(a), LENGTH(b), UPPER(c), LOWER('ÀbC'), TYPEOF(b) FROM g",
        # double-quoted identifiers fall back to string literals
        'SELECT "a", "no_such_column" FROM g',
        'SELECT a FROM g WHERE c = "p"',
        # postfix NULL tests
        "SELECT a FROM g WHERE b ISNULL",
        "SELECT a FROM g WHERE c NOTNULL",
        "SELECT a, b NOT NULL FROM g",
        # positional ORDER BY / GROUP BY
        "SELECT k, COUNT(*) FROM g GROUP BY 1 ORDER BY 2 DESC, 1",
        "SELECT a FROM g ORDER BY +1",
        # LEFT JOIN without ON, comma join
        "SELECT COUNT(*) FROM g x LEFT JOIN g y",
        "SELECT x.a, y.a FROM g x, g y WHERE x.a = y.a + 10",
        # IS / IS NOT with values
        "SELECT a, c IS 'p', c IS NOT NULL, b IS 5 FROM g",
    ],
)
def test_matches_sqlite(g, sql):
    g.check(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM g HAVING a > 1",
        "SELECT 1 FROM g HAVING COUNT(*) > 2",
        "SELECT a FROM g ORDER BY COUNT(*)",
        "SELECT a FROM g ORDER BY -1",
        "SELECT a FROM g GROUP BY 2",
        "SELECT COUNT(a, b) FROM g",
        "SELECT SUM(*) FROM g",
        "SELECT ABS(1, 2) FROM g",
        "SELECT x.a FROM g x JOIN g x ON 1",
        "SELECT a FROM g WHERE SUM(a) > 1",
        "SELECT a FROM g LIMIT NULL",
        "SELECT a FROM g LIMIT 1.5",
    ],
)
def test_errors_match_sqlite(g, sql):
    import sqlite3

    with pytest.raises(sqlite3.Error):
        g.ref.execute(sql).fetchall()
    with pytest.raises(SQLError):
        g.db.execute(sql)


def test_hash_join_does_not_change_results(both):
    both.run(
        "CREATE TABLE a (id INTEGER, v TEXT)",
        "CREATE TABLE b (aid INTEGER, w REAL)",
        "INSERT INTO a VALUES " + ", ".join(f"({i}, 'v{i % 7}')" for i in range(300)),
        "INSERT INTO b VALUES "
        + ", ".join(f"({i % 350 if i % 11 else 'NULL'}, {i * 0.5})" for i in range(900)),
    )
    both.check(
        "SELECT a.v, COUNT(b.aid), SUM(b.w), MIN(b.w) FROM a LEFT JOIN b ON a.id = b.aid "
        "AND b.w > 10 GROUP BY a.v ORDER BY a.v"
    )
    both.check("SELECT COUNT(*) FROM a JOIN b ON b.aid = a.id + 1 WHERE a.v <> 'v3'")
    both.check("SELECT COUNT(*), SUM(a.id) FROM b LEFT JOIN a ON a.id * 2 = b.aid")
