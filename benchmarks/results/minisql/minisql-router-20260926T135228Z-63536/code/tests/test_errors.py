"""Error handling: invalid SQL, unknown names, ambiguity and type errors."""

import pytest

from minisql import Database, SQLError

BOTH_ERRORS = [
    # syntax
    "SELEC 1",
    "SELECT",
    "SELECT 1 +",
    "SELECT (1",
    "SELECT 1)",
    "SELECT * FROM",
    "SELECT 'unterminated",
    "SELECT 1 FROM emp WHERE",
    "SELECT id FROM emp ORDER",
    "SELECT id FROM emp GROUP dept",
    "INSERT INTO emp VALUES",
    "INSERT emp VALUES (1)",
    "UPDATE emp SET",
    "DELETE emp",
    "CREATE TABLE",
    "CREATE TABLE x (",
    "SELECT 1 2",
    "SELECT id FROM emp LIMIT",
    "SELECT 1 BETWEEN 2",
    "SELECT 1 IN 2",
    "SELECT a. FROM emp",
    "SELECT @ FROM emp",
    "SELECT 1; SELECT 2",
    # unknown tables / columns
    "SELECT * FROM nope",
    "SELECT nope FROM emp",
    "SELECT emp.nope FROM emp",
    "SELECT x.id FROM emp",
    "SELECT emp.id FROM emp e",
    "SELECT nope.* FROM emp",
    "SELECT id FROM emp WHERE nope = 1",
    "SELECT id FROM emp ORDER BY nope",
    "SELECT id FROM emp GROUP BY nope",
    "SELECT COUNT(*) FROM emp HAVING nope > 1",
    "SELECT e.id FROM emp e JOIN dept d ON d.nope = e.dept",
    "INSERT INTO nope VALUES (1)",
    "INSERT INTO emp (nope) VALUES (1)",
    "UPDATE nope SET a = 1",
    "UPDATE emp SET nope = 1",
    "UPDATE emp SET name = nope",
    "DELETE FROM nope",
    "DELETE FROM emp WHERE nope",
    "DROP TABLE nope",
    "INSERT INTO emp VALUES (id, 1, 1, 1, 1)",
    # ambiguous
    "SELECT id FROM emp JOIN dept ON emp.dept = dept.id",
    "SELECT name FROM emp a JOIN emp b ON a.id = b.boss",
    "SELECT e.id FROM emp e JOIN dept d ON id = 1",
    "SELECT dname FROM emp JOIN dept ON dept = dept.id WHERE id > 1",
    # value counts / duplicates
    "INSERT INTO emp VALUES (1, 'x')",
    "INSERT INTO emp VALUES (1, 'x', 1, 1, 1, 1)",
    "INSERT INTO emp (id, name) VALUES (1)",
    "INSERT INTO emp (id) VALUES (1, 2)",
    "INSERT INTO emp (id) VALUES (1), (2, 3)",
    "CREATE TABLE emp (a INTEGER)",
    "CREATE TABLE z (a INTEGER, A TEXT)",
    # aggregates misuse
    "SELECT id FROM emp WHERE COUNT(*) > 1",
    "SELECT COUNT(SUM(id)) FROM emp",
    "SELECT id FROM emp GROUP BY COUNT(*)",
    "SELECT SUM(id, dept) FROM emp",
    "SELECT SUM(*) FROM emp",
    "SELECT nosuchfunc(1)",
    "SELECT id FROM emp HAVING id > 1",
    "SELECT COUNT(*) AS c FROM emp WHERE c > 1",
    # ordinals
    "SELECT id FROM emp ORDER BY 2",
    "SELECT id FROM emp ORDER BY 0",
    "SELECT id FROM emp GROUP BY 3",
    # misc
    "SELECT *",
    "SELECT id FROM emp LIMIT 1.5",
    "SELECT id FROM emp LIMIT 'x'",
]


@pytest.mark.parametrize("sql", BOTH_ERRORS)
def test_error_matches_sqlite(sample, sql):
    sample.both_error(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE t (a FOO)",
        "CREATE TABLE t (a INTEGER, b BAR BAZ)",
        "CREATE TABLE t (a DATETIME)",
    ],
)
def test_unknown_type_rejected(sql):
    with pytest.raises(SQLError):
        Database().execute(sql)


def test_error_leaves_state_unchanged():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1)")
    for bad in [
        "INSERT INTO t VALUES (1, 2)",
        "UPDATE t SET b = 1",
        "UPDATE t SET a = nope",
        "DELETE FROM t WHERE nope",
    ]:
        with pytest.raises(SQLError):
            db.execute(bad)
    assert db.execute("SELECT a FROM t") == [(1,)]


def test_errors_on_empty_tables_are_still_raised():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("CREATE TABLE u (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("SELECT nope FROM t")
    with pytest.raises(SQLError):
        db.execute("SELECT a FROM t JOIN u ON 1")
    with pytest.raises(SQLError):
        db.execute("UPDATE t SET a = nope")


@pytest.mark.parametrize("sql", ["", "   ", ";", "-- only a comment"])
def test_empty_statement_rejected(sql):
    with pytest.raises(SQLError):
        Database().execute(sql)


def test_non_string_sql_rejected():
    with pytest.raises(SQLError):
        Database().execute(None)  # type: ignore[arg-type]
