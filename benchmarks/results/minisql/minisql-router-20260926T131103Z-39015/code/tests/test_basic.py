"""Unit tests for the public API and specific SQLite behaviors."""

from __future__ import annotations

import pytest

from minisql import Database, SQLError
from tests.conftest import Dual


@pytest.fixture
def db() -> Database:
    d = Database()
    d.execute("CREATE TABLE t (a INTEGER, b REAL, c TEXT)")
    d.execute("INSERT INTO t VALUES (1, 1.5, 'x'), (2, NULL, 'y'), (NULL, 3, NULL)")
    return d


def test_public_api_and_return_values(db: Database) -> None:
    assert db.execute("CREATE TABLE u (x INTEGER)") == []
    assert db.execute("INSERT INTO u VALUES (1)") == []
    assert db.execute("UPDATE u SET x = 2") == []
    assert db.execute("DELETE FROM u WHERE x = 3") == []
    rows = db.execute("SELECT x FROM u;")
    assert rows == [(2,)]
    assert isinstance(rows, list) and isinstance(rows[0], tuple)


def test_trailing_semicolon_and_case_insensitivity(db: Database) -> None:
    assert db.execute("select A, C from T where c = 'x';") == [(1, "x")]
    assert db.execute("SeLeCt count(*) FrOm t") == [(3,)]


def test_output_types(db: Database) -> None:
    assert db.execute("SELECT 5/2, 5/2.0, 1 = 1") == [(2, 2.5, 1)]
    row = db.execute("SELECT -7/2, -7 % 2, 7.5 % 2, 1/0, 1 % 0")[0]
    assert row == (-3, -1, 1.0, None, None)
    assert [type(v) for v in row[:3]] == [int, int, float]


def test_affinity_on_insert() -> None:
    d = Database()
    d.execute("CREATE TABLE a (i INTEGER, r REAL, t TEXT)")
    d.execute("INSERT INTO a VALUES (3.0, 1, 5), ('42', '2.5', 1.5), (3.5, 'x', NULL)")
    rows = d.execute("SELECT i, r, t FROM a")
    assert rows == [(3, 1.0, "5"), (42, 2.5, "1.5"), (3.5, "x", None)]
    assert type(rows[0][0]) is int and type(rows[0][1]) is float and type(rows[0][2]) is str


def test_update_applies_affinity() -> None:
    d = Database()
    d.execute("CREATE TABLE a (i INTEGER, r REAL)")
    d.execute("INSERT INTO a VALUES (1, 1)")
    d.execute("UPDATE a SET i = '7', r = 2")
    assert d.execute("SELECT i, r FROM a") == [(7, 2.0)]


@pytest.mark.parametrize(
    "sql",
    [
        "SELEC 1",
        "SELECT * FROM nope",
        "SELECT nope FROM t",
        "SELECT t.nope FROM t",
        "SELECT a FROM t JOIN t AS t2 ON 1",
        "CREATE TABLE t (x INTEGER)",
        "INSERT INTO t VALUES (1, 2)",
        "INSERT INTO t VALUES (1, 2, 3, 4)",
        "INSERT INTO t (a) VALUES (1, 2)",
        "SELECT frobnicate(a) FROM t",
        "SELECT 1 +",
        "SELECT a FROM t ORDER BY 5",
        "SELECT a FROM t WHERE SUM(a) > 1",
        "SELECT a, b FROM t GROUP BY COUNT(*)",
        "SELECT a FROM t LIMIT 'abc'",
        "SELECT 'unterminated",
        "SELECT a FROM t; SELECT 1",
        "SELECT @",
        "",
    ],
)
def test_errors_raise_sqlerror(db: Database, sql: str) -> None:
    with pytest.raises(SQLError):
        db.execute(sql)


def test_ambiguous_column_resolves_when_qualified(db: Database) -> None:
    db.execute("CREATE TABLE u (a INTEGER, d TEXT)")
    db.execute("INSERT INTO u VALUES (1, 'one')")
    with pytest.raises(SQLError, match="ambiguous"):
        db.execute("SELECT a FROM t JOIN u ON t.a = u.a")
    assert db.execute("SELECT t.a, d FROM t JOIN u ON t.a = u.a") == [(1, "one")]


def test_errors_do_not_mutate_state(db: Database) -> None:
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (9, 9, 'z'), (1, 2)")
    assert db.execute("SELECT COUNT(*) FROM t") == [(3,)]
    with pytest.raises(SQLError):
        db.execute("UPDATE t SET a = nosuch")
    assert db.execute("SELECT a FROM t ORDER BY a") == [(None,), (1,), (2,)]


def test_no_raw_python_exceptions() -> None:
    d = Database()
    for sql in ["SELECT 1/0", "SELECT 1 % 0", "SELECT abs(-9223372036854775808)",
                "SELECT 9223372036854775807 + 1", "SELECT '' || 1e308 * 10",
                "SELECT substr('abc', -10, -10)", "SELECT 1 << 100", "SELECT ~'x'"]:
        try:
            d.execute(sql)
        except SQLError:
            pass
    with pytest.raises(SQLError):
        d.execute(None)  # type: ignore[arg-type]


EXTRA = [
    "SELECT a AS x FROM t WHERE x > 1",
    "SELECT a + 1 AS x FROM t ORDER BY -x",
    "SELECT a AS b, b AS a FROM t ORDER BY a",
    "SELECT c AS k, COUNT(*) FROM t GROUP BY k",
    "SELECT *, a FROM t",
    'SELECT "a", [b], `c` FROM "t"',
    "SELECT a FROM t ORDER BY a LIMIT 1 + 1",
    "SELECT DISTINCT c FROM t ORDER BY a DESC",
    "SELECT a, b, c FROM t ORDER BY b DESC",
    "SELECT a, b, c FROM t ORDER BY b ASC",
    "SELECT a FROM t ORDER BY a DESC NULLS FIRST",
    "SELECT a FROM t ORDER BY a NULLS LAST",
    "SELECT a, b FROM t WHERE a = 1 OR b IS NULL ORDER BY 1",
    "SELECT SUM(a) + a FROM t GROUP BY b ORDER BY 1",
    "SELECT a, COUNT(*) FROM t WHERE 0",
    "SELECT MAX(a), c FROM t",
    "SELECT COUNT(*) AS n FROM t HAVING n > 1",
    "SELECT 1 GROUP BY 1",
    "SELECT a -- comment\n FROM t /* block */ ORDER BY 1",
    "SELECT a, a IN (), a NOT IN () FROM t",
    "SELECT group_concat(c, '-') FROM t",
    "SELECT a FROM t WHERE c LIKE 'X'",
    "SELECT a FROM t WHERE c ISNULL",
    "SELECT a FROM t WHERE c NOTNULL",
    "SELECT a FROM t WHERE c NOT NULL",
    "SELECT CASE WHEN a IS NULL THEN 'none' ELSE a END FROM t",
    "SELECT iif(a > 1, 'big', 'small') FROM t",
]


@pytest.mark.parametrize("sql", EXTRA)
def test_extra_differential(sql: str) -> None:
    d = Dual()
    d.script(
        "CREATE TABLE t (a INTEGER, b REAL, c TEXT)",
        "INSERT INTO t VALUES (1, 1.5, 'x'), (2, NULL, 'y'), (NULL, 3, NULL), (3, 1.5, 'x')",
    )
    d.check(sql)
