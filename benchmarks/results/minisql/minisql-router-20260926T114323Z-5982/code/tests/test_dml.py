"""INSERT / UPDATE / DELETE / CREATE / DROP behaviour compared against sqlite3."""

from __future__ import annotations

import pytest

from minisql import Database, SQLError

DML_SCENARIOS = [
    (
        ["UPDATE emp SET salary = salary * 1.1 WHERE dept = 'eng'"],
        "SELECT id, salary FROM emp ORDER BY id",
    ),
    (["UPDATE nums SET a = b, b = a"], "SELECT id, a, b FROM nums ORDER BY id"),
    (["UPDATE nums SET a = a + 1, b = a * 10 WHERE a > 0"], "SELECT * FROM nums ORDER BY id"),
    (["UPDATE aff SET i = '42', r = 3, t = 7.5, n = '8.0'"], "SELECT * FROM aff ORDER BY id"),
    (["UPDATE aff SET i = 3.0 WHERE id = 1"], "SELECT i, typeof(i) FROM aff WHERE id = 1"),
    (["UPDATE emp SET dept = NULL"], "SELECT DISTINCT dept FROM emp"),
    (["UPDATE emp SET age = age + 1 WHERE NULL"], "SELECT id, age FROM emp ORDER BY id"),
    (["UPDATE emp SET name = upper(name) WHERE id IN (1, 3)"], "SELECT name FROM emp"),
    (["UPDATE EMP SET Salary = 1 WHERE ID = 2"], "SELECT salary FROM emp WHERE id = 2"),
    (["DELETE FROM emp WHERE age IS NULL"], "SELECT id FROM emp"),
    (["DELETE FROM emp WHERE dept = 'eng' OR salary < 50000"], "SELECT id FROM emp"),
    (["DELETE FROM emp"], "SELECT COUNT(*) FROM emp"),
    (["DELETE FROM emp WHERE NULL"], "SELECT COUNT(*) FROM emp"),
    (["DELETE FROM nums WHERE s = 10"], "SELECT id FROM nums"),
    (
        ["INSERT INTO emp (id, name) VALUES (100, 'Zoe')"],
        "SELECT * FROM emp WHERE id = 100",
    ),
    (
        ["INSERT INTO emp (name, id) VALUES ('Yan', 101), ('Xi', 102)"],
        "SELECT * FROM emp WHERE id > 100",
    ),
    (
        ["INSERT INTO nums VALUES (11, '12', 3.0, 4, 5)"],
        "SELECT a, typeof(a), b, typeof(b), x, typeof(x), s, typeof(s) FROM nums WHERE id = 11",
    ),
    (
        ["INSERT INTO nums VALUES (11, 1e20, -0.0, '1e2', 1.5e300)"],
        "SELECT a, typeof(a), b, typeof(b), x, typeof(x), s FROM nums WHERE id = 11",
    ),
    (
        ["INSERT INTO nums VALUES (11, 9223372036854775807, '9223372036854775808', 0, 0)"],
        "SELECT a, typeof(a), b, typeof(b) FROM nums WHERE id = 11",
    ),
    (
        ["INSERT INTO nums VALUES (11, '1e17', 1e17, '  3.5  ', -7)"],
        "SELECT a, typeof(a), b, typeof(b), x, s FROM nums WHERE id = 11",
    ),
    (
        ["INSERT INTO empty SELECT id, name FROM emp WHERE id < 4"],
        "SELECT * FROM empty",
    ),
    (
        ["INSERT INTO empty (b) SELECT dept FROM emp WHERE id < 4"],
        "SELECT * FROM empty",
    ),
    (
        ["INSERT INTO empty VALUES (1 + 1, 'x' || 'y'), (-5 / 2, NULL)"],
        "SELECT * FROM empty",
    ),
    (
        [
            "CREATE TABLE t2 (a INTEGER, b TEXT)",
            "INSERT INTO t2 VALUES (1, 'x')",
            "DROP TABLE t2",
            "CREATE TABLE t2 (c REAL)",
            "INSERT INTO t2 VALUES (1)",
        ],
        "SELECT * FROM t2",
    ),
    (
        ["CREATE TABLE IF NOT EXISTS emp (x INTEGER)", "DROP TABLE IF EXISTS nothere"],
        "SELECT COUNT(*) FROM emp",
    ),
    (
        [
            "CREATE TABLE typed (a INT, b VARCHAR(10), c DOUBLE, d FLOAT, e NUMERIC, "
            "f DECIMAL(10, 2), g CLOB, h BIGINT, i)",
            "INSERT INTO typed VALUES ('1', 2, '3', 4, '5.0', '6.5', 7, '8', '9')",
        ],
        "SELECT a, typeof(a), b, typeof(b), c, typeof(c), d, typeof(d), e, typeof(e), "
        "f, typeof(f), g, typeof(g), h, typeof(h), i, typeof(i) FROM typed",
    ),
    (
        [
            "UPDATE emp SET mgr = (mgr + 1) * 2 WHERE mgr IS NOT NULL",
            "DELETE FROM emp WHERE mgr > 10",
        ],
        "SELECT id, mgr FROM emp",
    ),
]


@pytest.mark.parametrize(("statements", "query"), DML_SCENARIOS)
def test_dml_scenario(fresh, statements: list[str], query: str) -> None:
    fresh.run_many(statements)
    fresh.check(query)


def test_statements_return_empty_list() -> None:
    db = Database()
    assert db.execute("CREATE TABLE t (a INTEGER)") == []
    assert db.execute("INSERT INTO t VALUES (1), (2)") == []
    assert db.execute("UPDATE t SET a = a + 1") == []
    assert db.execute("DELETE FROM t WHERE a = 2") == []
    assert db.execute("SELECT a FROM t") == [(3,)]
    assert db.execute("DROP TABLE t") == []


def test_rows_are_tuples_and_types_preserved() -> None:
    db = Database()
    db.execute("CREATE TABLE t (i INTEGER, r REAL, s TEXT)")
    db.execute("INSERT INTO t VALUES (3.0, 3, 5)")
    db.execute("INSERT INTO t VALUES ('12', '1.5', 1.5)")
    rows = db.execute("SELECT i, r, s FROM t ORDER BY i")
    assert rows == [(3, 3.0, "5"), (12, 1.5, "1.5")]
    assert [tuple(type(v) for v in r) for r in rows] == [(int, float, str)] * 2


def test_trailing_semicolon_tolerated() -> None:
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER);")
    db.execute("INSERT INTO t VALUES (1);;")
    assert db.execute("SELECT a FROM t;") == [(1,)]


def test_databases_are_independent() -> None:
    a = Database()
    b = Database()
    a.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(SQLError):
        b.execute("SELECT * FROM t")


def test_update_is_atomic_on_error() -> None:
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1), (-9223372036854775808)")
    with pytest.raises(SQLError):
        db.execute("UPDATE t SET a = abs(a)")
    assert sorted(db.execute("SELECT a FROM t")) == [(-9223372036854775808,), (1,)]


def test_insert_is_atomic_on_error() -> None:
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (1), (abs(-9223372036854775808))")
    assert db.execute("SELECT COUNT(*) FROM t") == [(0,)]
