"""Aggregates, GROUP BY and HAVING compared against SQLite."""

import pytest

QUERIES = [
    "SELECT COUNT(*) FROM emp",
    "SELECT count(*), count(salary), count(dept), count(DISTINCT dept) FROM emp",
    "SELECT SUM(salary), AVG(salary), MIN(salary), MAX(salary) FROM emp",
    "SELECT SUM(age), AVG(age), MIN(age), MAX(age) FROM emp",
    "SELECT MIN(name), MAX(name), MIN(dept), MAX(dept) FROM emp",
    "SELECT SUM(DISTINCT salary), AVG(DISTINCT age), COUNT(DISTINCT salary) FROM emp",
    "SELECT MIN(DISTINCT age), MAX(DISTINCT age) FROM emp",
    "SELECT COUNT(*), SUM(age), AVG(age), MIN(age), MAX(age) FROM emp WHERE 0",
    "SELECT COUNT(salary), SUM(salary), AVG(salary) FROM emp WHERE salary IS NULL",
    "SELECT total(age), total(salary) FROM emp",
    "SELECT total(age) FROM emp WHERE 0",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept",
    "SELECT dept, COUNT(*), SUM(salary), AVG(salary), MIN(age), MAX(age) FROM emp GROUP BY dept",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept ORDER BY dept",
    "SELECT dept, COUNT(*) AS c FROM emp GROUP BY dept ORDER BY c DESC, dept",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept ORDER BY COUNT(*) DESC, dept",
    "SELECT dept, AVG(salary) FROM emp GROUP BY dept ORDER BY AVG(salary), dept",
    "SELECT dept, SUM(age) FROM emp GROUP BY dept HAVING SUM(age) > 80",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept HAVING COUNT(*) >= 2 ORDER BY dept",
    "SELECT dept FROM emp GROUP BY dept HAVING MAX(salary) > 100000",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept HAVING dept LIKE '%s%'",
    "SELECT dept, COUNT(*) AS n FROM emp GROUP BY dept HAVING n > 1",
    "SELECT COUNT(*) FROM emp HAVING COUNT(*) > 5",
    "SELECT COUNT(*) FROM emp HAVING COUNT(*) > 50",
    "SELECT dept, age > 40, COUNT(*) FROM emp GROUP BY dept, age > 40",
    "SELECT dept, COUNT(*) FROM emp GROUP BY 1",
    "SELECT age / 10 AS decade, COUNT(*) FROM emp GROUP BY decade ORDER BY decade",
    "SELECT age / 10, COUNT(*) FROM emp GROUP BY age / 10 ORDER BY 1",
    "SELECT dept, SUM(salary) / COUNT(*) FROM emp GROUP BY dept",
    "SELECT dept, MAX(salary) - MIN(salary) FROM emp GROUP BY dept",
    "SELECT COUNT(*) + 1, SUM(age) * 2 FROM emp",
    "SELECT dept, COUNT(*) FROM emp WHERE age > 30 GROUP BY dept ORDER BY 2 DESC, 1",
    "SELECT dept, COUNT(DISTINCT age) FROM emp GROUP BY dept",
    "SELECT boss, COUNT(*) FROM emp GROUP BY boss ORDER BY boss",
    "SELECT boss, COUNT(*) FROM emp GROUP BY boss ORDER BY boss DESC",
    "SELECT dept, COUNT(*) FROM emp WHERE 0 GROUP BY dept",
    "SELECT MAX(age), name FROM emp",
    "SELECT MIN(salary), name FROM emp",
    "SELECT dept, MAX(salary), name FROM emp GROUP BY dept",
    "SELECT DISTINCT COUNT(*) FROM emp GROUP BY dept",
    "SELECT COUNT(i), SUM(i), AVG(i), SUM(r), AVG(r), MIN(t), MAX(t) FROM nums",
    "SELECT SUM(t), AVG(t), total(t) FROM nums",
    "SELECT t, COUNT(*) FROM nums GROUP BY t",
    "SELECT i % 2, SUM(r) FROM nums GROUP BY i % 2",
    "SELECT COUNT(*) FROM nums WHERE i > 0",
    "SELECT dept, group_concat(name) FROM emp WHERE dept = 'eng' GROUP BY dept",
    "SELECT SUM(salary) > 100000 FROM emp GROUP BY dept HAVING dept IS NOT NULL",
    "SELECT CASE WHEN COUNT(*) > 2 THEN 'big' ELSE 'small' END FROM emp GROUP BY dept",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_aggregate(sample, sql):
    sample.check(sql)


def test_sum_integer_stays_integer_and_real_accumulates(pair):
    p = pair("CREATE TABLE s (i INTEGER, r REAL)")
    p.run("INSERT INTO s VALUES (1, 0.1), (2, 0.2), (3, 0.3), (4, 1e16), (5, 1.0), (6, -1e16)")
    p.check("SELECT SUM(i), SUM(r), AVG(i), AVG(r), SUM(i + r), total(i) FROM s")


def test_sum_integer_overflow_errors(pair):
    from minisql import SQLError

    p = pair("CREATE TABLE s (i INTEGER)")
    p.run("INSERT INTO s VALUES (9223372036854775807), (1)")
    with pytest.raises(SQLError):
        p.mini.execute("SELECT SUM(i) FROM s")
    p.check("SELECT total(i), AVG(i) FROM s")


def test_empty_table_aggregates(pair):
    p = pair("CREATE TABLE e (a INTEGER, b REAL, c TEXT)")
    p.check("SELECT COUNT(*), COUNT(a), SUM(a), AVG(a), MIN(a), MAX(a) FROM e")
    p.check("SELECT SUM(b), AVG(b), MIN(c), MAX(c), COUNT(DISTINCT c) FROM e")
    p.check("SELECT a, COUNT(*) FROM e GROUP BY a")
    p.check("SELECT COUNT(*) FROM e HAVING COUNT(*) = 0")
