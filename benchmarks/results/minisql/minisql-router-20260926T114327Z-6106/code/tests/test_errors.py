"""Error handling: bad SQL must raise SQLError (and nothing else), matching sqlite3's rejection."""

from __future__ import annotations

import pytest

from minisql import Database, SQLError
from tests.conftest import Diff

SYNTAX_ERRORS = [
    "SELEC 1", "SELECT", "SELECT 1 +", "SELECT (1", "SELECT 1)", "SELECT 1 1 1",
    "SELECT FROM t", "SELECT * FROM", "SELECT * FROM t WHERE", "SELECT * FROM t ORDER",
    "SELECT * FROM t ORDER BY", "SELECT * FROM t GROUP", "SELECT * FROM t LIMIT",
    "SELECT 'unterminated", "SELECT \"unterminated", "SELECT 1 AS", "SELECT * FROM t t2 t3",
    "SELECT * FROM t JOIN", "SELECT * FROM t JOIN u ON",
    "SELECT 1 IN", "SELECT 1 IN (", "SELECT 1 BETWEEN 1", "SELECT 1 BETWEEN 1 AND",
    "SELECT 1 LIKE", "SELECT NOT", "SELECT 1 IS", "SELECT * FROM t WHERE a = = 1", "SELECT 1 $ 2",
    "SELECT 1 == == 2", "SELECT 1,", "SELECT ,1", "SELECT 1; SELECT 2", "SELECT 1 2",
    "CREATE TABLE", "CREATE TABLE t", "CREATE TABLE t ()", "CREATE TABLE t (a INTEGER",
    "CREATE TABLE (a INTEGER)", "CREATE t (a INTEGER)", "INSERT INTO t", "INSERT INTO t VALUES",
    "INSERT INTO t VALUES ()", "INSERT INTO t VALUES (1", "INSERT INTO t (a VALUES (1)",
    "INSERT t VALUES (1)", "INSERT INTO t VALUES (1),", "UPDATE t", "UPDATE t SET",
    "UPDATE t SET a", "UPDATE t SET a =", "UPDATE t SET a = 1 WHERE", "UPDATE SET a = 1",
    "DELETE t", "DELETE FROM", "DELETE FROM t WHERE", "SELECT * FROM t;;",
    "SELECT 1 2 FROM t", "SELECT a.b.c FROM t", "SELECT 1e", "SELECT 1.2.3", "SELECT 1abc",
    "SELECT COUNT(", "SELECT COUNT(*", "SELECT COUNT(DISTINCT)", "SELECT SUM(*) FROM t",
    "SELECT * FROM t WHERE a IN 1", "SELECT * FROM t WHERE a NOT 1",
    "SELECT * FROM t ORDER BY a DESCENDING", "SELECT * FROM t LIMIT 1 OFFSET",
    "SELECT * FROM t WHERE a BETWEEN 1 OR 2", "SELECT 1 FROM t WHERE 1 = ", "SELECT * * FROM t",
    "SELECT t.* .x FROM t", "SELECT * FROM t GROUP BY", "SELECT * FROM t HAVING",
    "SELECT * FROM t WHERE a IS NOT", "SELECT 1 FROM t AS",
]

SEMANTIC_ERRORS = [
    "SELECT * FROM nope", "SELECT nope FROM t", "SELECT t.nope FROM t", "SELECT nope.a FROM t",
    "SELECT * FROM t WHERE nope = 1", "SELECT * FROM t ORDER BY nope",
    "SELECT * FROM t GROUP BY nope",
    "SELECT a FROM t GROUP BY a HAVING nope > 1", "SELECT a FROM t JOIN nope ON 1",
    "SELECT a FROM t JOIN u ON t.a = u.nope", "SELECT a FROM t JOIN u ON nope = 1",
    "SELECT * FROM t x WHERE t.a = 1", "SELECT t.a FROM t x", "SELECT * FROM t WHERE x.a = 1",
    "INSERT INTO nope VALUES (1)", "INSERT INTO t (nope) VALUES (1)", "INSERT INTO t VALUES (1)",
    "INSERT INTO t VALUES (1, 2, 3)", "INSERT INTO t (a) VALUES (1, 2)",
    "INSERT INTO t (a, b) VALUES (1)",
    "INSERT INTO t VALUES (1, 2), (3)", "INSERT INTO t VALUES (a, 1)", "UPDATE nope SET a = 1",
    "UPDATE t SET nope = 1", "UPDATE t SET a = nope", "UPDATE t SET a = 1 WHERE nope = 1",
    "DELETE FROM nope", "DELETE FROM t WHERE nope = 1", "CREATE TABLE t (a INTEGER)",
    "CREATE TABLE T (x INTEGER)", "CREATE TABLE v (a INTEGER, a TEXT)",
    "CREATE TABLE v (a INTEGER, A TEXT)",
    "SELECT a FROM t JOIN u ON t.a = u.a", "SELECT a FROM t, u", "SELECT a FROM t x JOIN t y ON 1",
    "SELECT * FROM t x JOIN t y ON a = 1", "SELECT t.a FROM t JOIN u ON 1 WHERE a = 1",
    "SELECT t.a FROM t JOIN u ON 1 ORDER BY a", "SELECT t.a FROM t JOIN u ON 1 GROUP BY a",
    "SELECT * FROM t WHERE MAX(a) > 1", "SELECT * FROM t JOIN u ON COUNT(*) > 0",
    "SELECT a FROM t ORDER BY 0", "SELECT a FROM t ORDER BY 2",
    "SELECT a FROM t ORDER BY -1 = 1, 3",
    "SELECT a FROM t GROUP BY 0", "SELECT a FROM t GROUP BY 2", "SELECT nope()", "SELECT nope(1)",
    "SELECT COUNT(1, 2)", "SELECT SUM() FROM t", "SELECT AVG(a, b) FROM t", "SELECT MAX() FROM t",
    "SELECT typeof() ", "SELECT typeof(1, 2)", "SELECT abs()", "SELECT length(1, 2)",
    "SELECT * FROM t GROUP BY COUNT(*)", "SELECT * FROM t LIMIT 'x'", "SELECT * FROM t LIMIT 1.5",
    "SELECT * FROM t LIMIT a", "SELECT 1 AS x, x FROM t", "SELECT * FROM t WHERE 1 LIMIT nope",
    "SELECT nope FROM t WHERE 0", "SELECT * FROM t WHERE nope IS NULL", "SELECT u.a FROM t",
    "SELECT * FROM t LEFT JOIN u ON u.nope = 1", "SELECT * FROM t LEFT JOIN nope ON 1",
]


@pytest.fixture
def tables(diff: Diff) -> Diff:
    diff.setup("CREATE TABLE t (a INTEGER, b TEXT)", "INSERT INTO t VALUES (1, 'x')",
               "CREATE TABLE u (a INTEGER, c TEXT)", "INSERT INTO u VALUES (1, 'y')")
    return diff


@pytest.mark.parametrize("sql", SYNTAX_ERRORS)
def test_syntax_errors(tables: Diff, sql: str) -> None:
    tables.error(sql)


@pytest.mark.parametrize("sql", SEMANTIC_ERRORS)
def test_semantic_errors(tables: Diff, sql: str) -> None:
    tables.error(sql)


def test_unsupported_statements_raise_sqlerror() -> None:
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    for sql in ["DROP TABLE t", "SELECT (SELECT 1)", "SELECT * FROM (SELECT 1)",
                "SELECT a FROM t UNION SELECT a FROM t", "ALTER TABLE t ADD COLUMN b",
                "BEGIN", "SELECT CASE WHEN 1 THEN 2 END", "SELECT CAST(1 AS TEXT)",
                "SELECT * FROM t WHERE EXISTS (SELECT 1)", "SELECT x'00'", "SELECT 0x10"]:
        with pytest.raises(SQLError):
            db.execute(sql)


def test_empty_statement_is_rejected() -> None:
    db = Database()
    for sql in ["", ";", "   ", "-- just a comment", "/* c */"]:
        with pytest.raises(SQLError):
            db.execute(sql)


def test_errors_are_sqlerror_and_do_not_corrupt_state() -> None:
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    db.execute("INSERT INTO t VALUES (1, 'x')")
    for bad in ["INSERT INTO t VALUES (2)", "INSERT INTO t VALUES (2, 'y'), (3)",
                "UPDATE t SET nope = 1", "DELETE FROM t WHERE nope = 1", "SELECT nope FROM t",
                "CREATE TABLE t (z INTEGER)"]:
        with pytest.raises(SQLError):
            db.execute(bad)
    assert db.execute("SELECT * FROM t") == [(1, "x")]


def test_ambiguous_column_messages() -> None:
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER, b INTEGER)")
    db.execute("CREATE TABLE u (a INTEGER, c INTEGER)")
    with pytest.raises(SQLError, match="ambiguous"):
        db.execute("SELECT a FROM t JOIN u ON t.a = u.a")
    with pytest.raises(SQLError, match="no such column"):
        db.execute("SELECT z FROM t JOIN u ON t.a = u.a")
    with pytest.raises(SQLError, match="no such table"):
        db.execute("SELECT * FROM v")
    # Non-ambiguous columns are fine even with a join.
    assert db.execute("SELECT b, c FROM t JOIN u ON t.a = u.a") == []


def test_alias_hides_table_name() -> None:
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1)")
    assert db.execute("SELECT x.a FROM t x") == [(1,)]
    with pytest.raises(SQLError):
        db.execute("SELECT t.a FROM t x")
    with pytest.raises(SQLError):
        db.execute("SELECT t.* FROM t x")


def test_only_sqlerror_escapes_for_garbage_input() -> None:
    db = Database()
    for garbage in ["\x00", "SELECT '\\", "SELECT 1e999999", "SELECT ((((((((", ")" * 50,
                    "SELECT " + "1 + " * 200 + "1", "SELECT -" * 100 + "1", "SELECT x'00'"]:
        try:
            db.execute(garbage)
        except SQLError:
            pass
