"""INNER / LEFT / CROSS joins compared against SQLite."""

import pytest

from tests.conftest import Pair

QUERIES = [
    "SELECT e.name, d.title FROM emp e JOIN dept d ON e.dept = d.code",
    "SELECT e.name, d.title FROM emp e INNER JOIN dept d ON e.dept = d.code",
    "SELECT e.name, d.title FROM emp AS e INNER JOIN dept AS d ON d.code = e.dept",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON e.dept = d.code",
    "SELECT e.name, d.title FROM emp e LEFT OUTER JOIN dept d ON e.dept = d.code",
    "SELECT d.code, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.code",
    "SELECT d.code, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.code WHERE e.id IS NULL",
    "SELECT d.code, COUNT(e.id) FROM dept d LEFT JOIN emp e ON e.dept = d.code GROUP BY d.code",
    "SELECT d.code, COUNT(*) FROM dept d LEFT JOIN emp e ON e.dept = d.code GROUP BY d.code",
    "SELECT d.code, SUM(e.salary), AVG(e.age) FROM dept d LEFT JOIN emp e ON e.dept = d.code "
    "GROUP BY d.code ORDER BY d.code",
    "SELECT * FROM emp e JOIN dept d ON e.dept = d.code",
    "SELECT * FROM emp e LEFT JOIN dept d ON e.dept = d.code",
    "SELECT d.*, e.name FROM emp e LEFT JOIN dept d ON e.dept = d.code",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON e.dept = d.code AND d.floor > 1",
    "SELECT e.name, d.title FROM emp e JOIN dept d ON e.dept = d.code AND d.floor > 1",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON e.dept = d.code WHERE d.floor > 1",
    "SELECT e.name, b.name FROM emp e JOIN emp b ON e.boss = b.id",
    "SELECT e.name, b.name FROM emp e LEFT JOIN emp b ON e.boss = b.id ORDER BY e.id",
    "SELECT e.name, b.name, bb.name FROM emp e LEFT JOIN emp b ON e.boss = b.id "
    "LEFT JOIN emp bb ON b.boss = bb.id ORDER BY e.id",
    "SELECT e.name, d.title, b.name FROM emp e JOIN dept d ON e.dept = d.code "
    "LEFT JOIN emp b ON b.id = e.boss",
    "SELECT title, name FROM emp JOIN dept ON dept = code",
    "SELECT emp.name, dept.title FROM emp JOIN dept ON emp.dept = dept.code",
    "SELECT e.name, d.code FROM emp e CROSS JOIN dept d",
    "SELECT e.name, d.code FROM emp e, dept d WHERE e.dept = d.code",
    "SELECT e.name, d.code FROM emp e JOIN dept d",
    "SELECT e.name, d.code FROM emp e LEFT JOIN dept d",
    "SELECT e.name, x.i FROM emp e LEFT JOIN nums x WHERE x.i > 100",
    "SELECT e.name FROM emp e JOIN dept d ON 1 WHERE d.code = 'eng'",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON 0",
    "SELECT e.name, d.floor FROM emp e LEFT JOIN dept d ON e.dept = d.code "
    "ORDER BY d.floor, e.name",
    "SELECT e.name, d.floor FROM emp e LEFT JOIN dept d ON e.dept = d.code "
    "ORDER BY d.floor DESC, e.name",
    "SELECT d.title, COUNT(*) AS n FROM emp e JOIN dept d ON e.dept = d.code "
    "GROUP BY d.title HAVING n > 1 ORDER BY n DESC, d.title",
    "SELECT DISTINCT d.title FROM emp e JOIN dept d ON e.dept = d.code",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON e.dept = d.code "
    "WHERE d.title IS NULL",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON e.dept = d.code "
    "WHERE d.floor IN (1, 2) OR d.floor IS NULL",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_join(sample, sql):
    sample.check(sql)


def test_three_way_left_join_nulls():
    p = Pair(
        "CREATE TABLE a (id INTEGER, v TEXT)",
        "CREATE TABLE b (id INTEGER, a_id INTEGER, w REAL)",
        "CREATE TABLE c (id INTEGER, b_id INTEGER, x TEXT)",
        "INSERT INTO a VALUES (1, 'one'), (2, 'two'), (3, 'three')",
        "INSERT INTO b VALUES (10, 1, 1.5), (11, 1, 2.5), (12, 2, NULL)",
        "INSERT INTO c VALUES (100, 10, 'p'), (101, 12, 'q')",
    )
    p.check(
        "SELECT a.v, b.w, c.x FROM a LEFT JOIN b ON b.a_id = a.id "
        "LEFT JOIN c ON c.b_id = b.id ORDER BY a.id, b.id"
    )
    p.check("SELECT a.v, b.w, c.x FROM a JOIN b ON b.a_id = a.id LEFT JOIN c ON c.b_id = b.id")
    p.check(
        "SELECT a.v, COUNT(b.id), SUM(b.w), COUNT(c.id) FROM a LEFT JOIN b ON b.a_id = a.id "
        "LEFT JOIN c ON c.b_id = b.id GROUP BY a.v ORDER BY a.v"
    )
    p.check("SELECT * FROM a LEFT JOIN b ON b.a_id = a.id LEFT JOIN c ON c.b_id = b.id")
