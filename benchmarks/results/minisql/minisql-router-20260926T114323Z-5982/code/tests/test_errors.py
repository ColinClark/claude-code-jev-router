"""Invalid statements must raise SQLError (and sqlite3 must reject them too)."""

from __future__ import annotations

import pytest

from minisql import Database, SQLError

BOTH_REJECT = [
    "SELECT * FROM nosuch",
    "SELECT nosuch FROM emp",
    "SELECT e.nosuch FROM emp e",
    "SELECT emp.id FROM emp e",
    "SELECT x.id FROM emp e",
    "SELECT id FROM emp e JOIN emp m ON e.mgr = m.id",
    "SELECT name FROM emp e JOIN emp m ON e.mgr = m.id",
    "SELECT dept FROM emp JOIN dept ON 1 JOIN emp e2 ON 1",
    "SELECT a FROM nums JOIN empty ON 1",
    "SELECT * FROM emp, emp",
    "SELECT e.id FROM emp e JOIN emp e ON 1",
    "CREATE TABLE emp (a INTEGER)",
    "CREATE TABLE Emp (a INTEGER)",
    "CREATE TABLE t (a INTEGER, a TEXT)",
    "INSERT INTO emp VALUES (1)",
    "INSERT INTO emp VALUES (1, 2, 3, 4, 5, 6, 7)",
    "INSERT INTO emp (id) VALUES (1, 2)",
    "INSERT INTO emp (id, name) VALUES (1)",
    "INSERT INTO emp (nosuch) VALUES (1)",
    "INSERT INTO nosuch VALUES (1)",
    "INSERT INTO empty VALUES (1, 2), (3)",
    "INSERT INTO empty VALUES (a, 1)",
    "INSERT INTO empty SELECT id FROM emp",
    "SELECT COUNT(*) FROM emp WHERE COUNT(*) > 1",
    "SELECT id FROM emp WHERE SUM(age) > 1",
    "SELECT SUM(COUNT(*)) FROM emp",
    "SELECT id FROM emp GROUP BY COUNT(*)",
    "SELECT id FROM emp HAVING id > 1",
    "SELECT id FROM emp ORDER BY COUNT(*)",
    "SELECT id FROM emp ORDER BY 0",
    "SELECT id FROM emp ORDER BY 2",
    "SELECT id FROM emp ORDER BY -1",
    "SELECT id, name FROM emp GROUP BY 3",
    "SELECT dept, COUNT(*) AS c FROM emp WHERE c > 1 GROUP BY dept",
    "SELECT e.id FROM emp e JOIN dept d ON COUNT(*) > 0",
    "UPDATE emp SET age = COUNT(*)",
    "DELETE FROM emp WHERE MAX(age) > 1",
    "SELECT",
    "SELECT FROM emp",
    "SELECT id FROM",
    "SELEC 1",
    "SELECT (1, 2)",
    "SELECT 1 +",
    "SELECT 'abc",
    "SELECT * FROM emp WHERE",
    "SELECT * FROM emp WHERE id = = 1",
    "SELECT * FROM emp ORDER",
    "SELECT * FROM emp LIMIT",
    "SELECT DISTINCT FROM emp",
    "SELECT id FROM emp GROUP id",
    "SELECT 12abc",
    "SELECT 1 !",
    "SELECT COUNT(id, name) FROM emp",
    "SELECT SUM(*) FROM emp",
    "SELECT SUM(age, age) FROM emp",
    "SELECT AVG() FROM emp",
    "SELECT MIN() FROM emp",
    "SELECT nosuchfunc(1)",
    "SELECT abs(1, 2)",
    "SELECT coalesce(1)",
    "SELECT 1 LIMIT NULL",
    "SELECT 1 LIMIT 'abc'",
    "SELECT 1 LIMIT 2.5",
    "SELECT 1 LIMIT 1 OFFSET 'x'",
    "SELECT id FROM emp LIMIT id",
    "UPDATE emp SET nosuch = 1",
    "UPDATE nosuch SET a = 1",
    "UPDATE emp SET age = nosuch",
    "UPDATE emp SET age = 1 WHERE nosuch = 1",
    "DELETE FROM nosuch",
    "DELETE FROM emp WHERE nosuch = 1",
    "DROP TABLE nosuch",
    "SELECT *",
    "SELECT x.* FROM emp",
    "SELECT id AS x, SUM(age) AS y FROM emp WHERE y > 1",
    "SELECT SUM(a) FROM big",
    "SELECT abs(-9223372036854775808)",
    "SELECT 'a' LIKE 'b' ESCAPE 'xy'",
    "SELECT COUNT(DISTINCT id, name) FROM emp",
    "SELECT id FROM emp WHERE id IN",
    "SELECT CAST(1) FROM emp",
    "SELECT CASE END",
    "SELECT name FROM emp ORDER BY name COLLATE nosuchcoll",
    "INSERT INTO emp VALUES",
    "CREATE TABLE",
    "CREATE TABLE t ()",
    "UPDATE emp SET",
    "DELETE emp",
]


@pytest.mark.parametrize("sql", BOTH_REJECT)
def test_rejected_like_sqlite(fresh, sql: str) -> None:
    fresh.check_error(sql)


def test_multiple_statements_rejected() -> None:
    db = Database()
    with pytest.raises(SQLError):
        db.execute("SELECT 1; SELECT 2")


@pytest.mark.parametrize(
    "sql",
    [
        # Features outside the supported subset must fail cleanly with SQLError.
        "SELECT (SELECT 1)",
        "SELECT 1 WHERE 1 IN (SELECT 1)",
        "SELECT 1 UNION SELECT 2",
        "SELECT * FROM t1 NATURAL JOIN t2",
        "SELECT * FROM (SELECT 1)",
        "SELECT ?",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "",
        "   ",
        ";",
        "CREATE TABLE p (a INTEGER PRIMARY KEY)",
    ],
)
def test_unsupported_raise_sqlerror(sql: str) -> None:
    db = Database()
    with pytest.raises(SQLError):
        db.execute(sql)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT 1 / 0", [(None,)]),
        ("SELECT 1 % 0", [(None,)]),
        ("SELECT 1.0 / 0", [(None,)]),
        ("SELECT 5 % 0.4", [(None,)]),
        ("SELECT -9223372036854775808 / -1", [(9.223372036854776e18,)]),
        ("SELECT 1e308 * 1e308", [(float("inf"),)]),
        ("SELECT 'abc' * 2", [(0,)]),
        ("SELECT NULL < 'a'", [(None,)]),
        ("SELECT 1 < 'a'", [(1,)]),
        ("SELECT typeof(1 << 100)", [("integer",)]),
    ],
)
def test_no_python_exceptions_leak(sql: str, expected: list[tuple]) -> None:
    assert Database().execute(sql) == expected


def test_sqlerror_messages_are_informative() -> None:
    db = Database()
    db.execute("CREATE TABLE a (x INTEGER)")
    db.execute("CREATE TABLE b (x INTEGER)")
    with pytest.raises(SQLError, match="ambiguous"):
        db.execute("SELECT x FROM a JOIN b ON 1")
    with pytest.raises(SQLError, match="no such column"):
        db.execute("SELECT y FROM a")
    with pytest.raises(SQLError, match="no such table"):
        db.execute("SELECT * FROM c")
    with pytest.raises(SQLError, match="already exists"):
        db.execute("CREATE TABLE A (z TEXT)")


def test_non_string_sql_rejected() -> None:
    with pytest.raises(SQLError):
        Database().execute(None)  # type: ignore[arg-type]
