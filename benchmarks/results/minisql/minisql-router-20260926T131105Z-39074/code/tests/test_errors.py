"""Statements that must fail with SQLError (and also fail in sqlite3)."""

import pytest

from minisql import Database, SQLError

ERRORS = [
    "SELECT nope FROM emp",
    "SELECT * FROM nope",
    "SELECT emp.nope FROM emp",
    "SELECT x.id FROM emp",
    "SELECT id FROM emp JOIN dept ON emp.dept_id = dept.id",
    "SELECT name FROM emp e JOIN dept d ON e.dept_id = d.id",
    "SELECT e.id FROM emp e JOIN dept d ON e.dept_id = d.id WHERE name = 'x'",
    "SELECT id FROM emp e LEFT JOIN emp m ON e.manager_id = m.id",
    "SELECT emp.id FROM emp e",
    "SELECT nope FROM emp WHERE 0",
    "SELECT * FROM emp WHERE nope = 1",
    "SELECT * FROM emp ORDER BY nope",
    "SELECT * FROM emp GROUP BY nope",
    "SELECT COUNT(*) FROM emp HAVING nope > 1",
    "SELECT * FROM emp e JOIN dept d ON e.nope = d.id",
    "SELECT d.* FROM emp",
    "SELECT",
    "SELECT FROM emp",
    "SELECT * FROM",
    "SELECT * FROM emp WHERE",
    "SELECT 1 +",
    "SELECT (1",
    "SELECT 'unterminated",
    "SELECT * FROM emp ORDER",
    "SELECT * FROM emp LIMIT",
    "SELEKT 1",
    "SELECT 1 2",
    "SELECT * FROM emp; SELECT 1",
    "SELECT id FROM emp WHERE COUNT(*) > 1",
    "SELECT id FROM emp GROUP BY COUNT(*)",
    "SELECT SUM(COUNT(*)) FROM emp",
    "SELECT id FROM emp HAVING id > 1",
    "SELECT nosuchfunc(1)",
    "SELECT COUNT(1, 2) FROM emp",
    "SELECT id FROM emp ORDER BY 3",
    "SELECT id FROM emp ORDER BY 0",
    "SELECT id FROM emp LIMIT 'abc'",
    "SELECT id FROM emp LIMIT 1.5",
    "SELECT id FROM emp LIMIT NULL",
    "SELECT *",
    "SELECT id FROM emp WHERE id IN (SELECT id FROM emp) AND nope",
    "CREATE TABLE emp (a INTEGER)",
    "CREATE TABLE t (a INTEGER, a TEXT)",
    "CREATE TABLE t ()",
    "INSERT INTO nope VALUES (1)",
    "INSERT INTO dept VALUES (1, 'x')",
    "INSERT INTO dept VALUES (1, 'x', 2.0, 3)",
    "INSERT INTO dept (id, name) VALUES (1)",
    "INSERT INTO dept (id, nope) VALUES (1, 2)",
    "INSERT INTO dept VALUES (id, 'x', 1.0)",
    "INSERT INTO dept VALUES (1, 'x', 1.0), (2, 'y')",
    "UPDATE nope SET a = 1",
    "UPDATE dept SET nope = 1",
    "UPDATE dept SET name = nope",
    "UPDATE dept SET name = 'x' WHERE nope = 1",
    "DELETE FROM nope",
    "DELETE FROM dept WHERE nope = 1",
    "DROP TABLE nope",
    "SELECT 1 NOT 2",
    "SELECT 1 IN 2",
    "SELECT 1 BETWEEN 2",
]


@pytest.mark.parametrize("sql", ERRORS)
def test_error(company, sql):
    company.error(sql)


def test_failed_insert_does_not_modify_table(company):
    company.error("INSERT INTO dept VALUES (10, 'x', 1.0), (11, 'y')")
    company.query("SELECT COUNT(*) FROM dept")


def test_ambiguous_column_error_on_empty_tables():
    db = Database()
    db.execute("CREATE TABLE a (id INTEGER)")
    db.execute("CREATE TABLE b (id INTEGER)")
    with pytest.raises(SQLError):
        db.execute("SELECT id FROM a JOIN b ON a.id = b.id")


def test_sqlerror_is_exception():
    assert issubclass(SQLError, Exception)
