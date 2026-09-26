"""SELECT queries (filters, ordering, aggregates, joins, affinity) compared against sqlite3."""

from __future__ import annotations

import pytest

BASIC = [
    "SELECT * FROM emp",
    "SELECT id, name FROM emp WHERE salary > 70000",
    "SELECT * FROM emp WHERE dept IS NULL",
    "SELECT * FROM emp WHERE dept IS NOT NULL AND age > 30",
    "SELECT name FROM emp WHERE age BETWEEN 30 AND 45",
    "SELECT name FROM emp WHERE age NOT BETWEEN 30 AND 45",
    "SELECT name FROM emp WHERE name LIKE 'a%'",
    "SELECT name FROM emp WHERE name NOT LIKE '%e'",
    "SELECT name FROM emp WHERE name LIKE '_a%'",
    "SELECT name FROM emp WHERE dept IN ('eng', 'hr')",
    "SELECT name FROM emp WHERE dept NOT IN ('eng', 'hr')",
    "SELECT name FROM emp WHERE dept NOT IN ('eng', NULL)",
    "SELECT name FROM emp WHERE dept IN ('eng', NULL)",
    "SELECT name FROM emp WHERE NOT (age > 30)",
    "SELECT name FROM emp WHERE salary",
    "SELECT name FROM emp WHERE mgr",
    "SELECT name FROM emp WHERE NULL",
    "SELECT name FROM emp WHERE age / 10 = 4",
    "SELECT name FROM emp WHERE age % 2 = 1 OR salary IS NULL",
    "SELECT id, salary * 2, age + 0.5, name || '-' || dept FROM emp",
    "SELECT id, salary / age, age / 7, age % 7, -age FROM emp",
    "SELECT DISTINCT dept FROM emp",
    "SELECT DISTINCT salary FROM emp",
    "SELECT DISTINCT dept, age > 35 FROM emp",
    "SELECT DISTINCT age / 10 FROM emp",
    "SELECT ALL dept FROM emp",
    "SELECT e.name FROM emp AS e WHERE e.id < 4",
    "SELECT e.name FROM emp e WHERE e.id > 8",
    "SELECT EMP.NAME FROM Emp WHERE Id = 1",
    "SeLeCt NaMe FrOm EmP wHeRe Id = 2",
    "SELECT id AS x FROM emp WHERE x > 10",
    "SELECT name n FROM emp",
    "SELECT name AS 'label' FROM emp",
    "SELECT 1 FROM emp",
    "SELECT emp.* FROM emp WHERE id = 3",
    "SELECT *, id FROM emp WHERE id < 3",
    "SELECT id, * FROM dept, emp WHERE id = 1",
    'SELECT "name" FROM emp WHERE "id" = 4',
    "SELECT [name], `dept` FROM emp WHERE id = 5",
    "SELECT * FROM empty",
    "SELECT COUNT(*) FROM empty WHERE a > 1",
    "SELECT * FROM emp WHERE id = 3;",
    "SELECT * FROM emp WHERE id = 3 ;  ",
    "SELECT name FROM emp WHERE name = 'alice'",
    "SELECT name FROM emp WHERE name > 'a'",
    "SELECT w FROM words WHERE w LIKE 'a%'",
    "SELECT w FROM words WHERE w LIKE '%\\%' ESCAPE '\\'",
    "SELECT w FROM words WHERE w LIKE '\\_%' ESCAPE '\\'",
    "SELECT w FROM words WHERE w LIKE 'é%'",
    "SELECT w FROM words WHERE w LIKE '%e%'",
    "SELECT w FROM words WHERE w LIKE '_'",
    "SELECT w FROM words WHERE w LIKE ''",
    "SELECT n FROM words WHERE w IS NULL",
    "SELECT id FROM nums WHERE s = 10",
    "SELECT id FROM nums WHERE s > 5",
    "SELECT id FROM nums WHERE a > s",
    "SELECT id FROM nums WHERE x < 1",
    "SELECT id FROM nums WHERE a IS b",
    "SELECT id FROM nums WHERE a IS NOT b",
    "SELECT id FROM nums WHERE a = b",
    "SELECT id FROM nums WHERE a <> b",
]

ORDERING = [
    "SELECT name FROM emp ORDER BY name",
    "SELECT name FROM emp ORDER BY name DESC",
    "SELECT name, salary FROM emp ORDER BY salary, id",
    "SELECT name, salary FROM emp ORDER BY salary DESC, id",
    "SELECT name, salary FROM emp ORDER BY salary ASC, id DESC",
    "SELECT dept, name FROM emp ORDER BY dept, name",
    "SELECT dept, name FROM emp ORDER BY dept DESC, name",
    "SELECT dept, name FROM emp ORDER BY 1, 2",
    "SELECT dept, name FROM emp ORDER BY 1 DESC, 2 DESC",
    "SELECT name AS n FROM emp ORDER BY n",
    "SELECT id, salary * 2 AS s2 FROM emp ORDER BY s2 DESC, id",
    "SELECT id, age FROM emp ORDER BY age + id, id",
    "SELECT id FROM emp ORDER BY -id",
    "SELECT id, name FROM emp ORDER BY lower(name), id",
    "SELECT name AS x, id AS name FROM emp ORDER BY name",
    "SELECT id AS x FROM emp ORDER BY x + 1",
    "SELECT id, dept FROM emp ORDER BY dept NULLS LAST, id",
    "SELECT id, dept FROM emp ORDER BY dept DESC NULLS FIRST, id",
    "SELECT id, salary FROM emp ORDER BY salary IS NULL, salary DESC, id",
    "SELECT s FROM nums ORDER BY s",
    "SELECT s FROM nums ORDER BY s DESC",
    "SELECT x FROM nums ORDER BY x DESC",
    "SELECT a, b FROM nums ORDER BY b, a",
    "SELECT w FROM words ORDER BY w",
    "SELECT w FROM words ORDER BY w DESC",
    "SELECT v FROM mixed ORDER BY v",
    "SELECT v FROM mixed ORDER BY v DESC",
    "SELECT id, v FROM mixed ORDER BY typeof(v), id",
    "SELECT id FROM emp ORDER BY id LIMIT 3",
    "SELECT id FROM emp ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT id FROM emp ORDER BY id LIMIT 2, 3",
    "SELECT id FROM emp ORDER BY id LIMIT -1 OFFSET 10",
    "SELECT id FROM emp ORDER BY id LIMIT 0",
    "SELECT id FROM emp ORDER BY id LIMIT 1 + 1",
    "SELECT id FROM emp ORDER BY id LIMIT '2'",
    "SELECT id FROM emp ORDER BY id LIMIT 2.0",
    "SELECT id FROM emp ORDER BY id LIMIT 5 OFFSET 100",
    "SELECT id FROM emp ORDER BY id LIMIT -5 OFFSET -2",
    "SELECT id FROM emp ORDER BY id DESC LIMIT 4",
    "SELECT DISTINCT dept FROM emp ORDER BY dept",
    "SELECT DISTINCT dept FROM emp ORDER BY dept DESC LIMIT 2",
    "SELECT DISTINCT age FROM emp ORDER BY 1 DESC",
    "SELECT id FROM emp ORDER BY +1",
    "SELECT id, name FROM emp ORDER BY (id % 3), id",
    "SELECT id, name FROM emp ORDER BY CASE WHEN dept = 'eng' THEN 0 ELSE 1 END, id",
    "SELECT id, salary FROM emp WHERE salary > 50000 ORDER BY salary DESC, name LIMIT 3",
    "SELECT name FROM emp ORDER BY name COLLATE BINARY",
]

AGGREGATES = [
    "SELECT COUNT(*) FROM emp",
    "SELECT COUNT(dept) FROM emp",
    "SELECT COUNT(DISTINCT dept) FROM emp",
    "SELECT COUNT(), COUNT(1), COUNT(NULL) FROM emp",
    "SELECT SUM(age) FROM emp",
    "SELECT SUM(salary) FROM emp",
    "SELECT AVG(age) FROM emp",
    "SELECT AVG(salary) FROM emp",
    "SELECT MIN(salary), MAX(salary) FROM emp",
    "SELECT MIN(name), MAX(name) FROM emp",
    "SELECT MIN(dept), MAX(dept) FROM emp",
    "SELECT TOTAL(age), TOTAL(salary) FROM emp",
    "SELECT SUM(age) FROM emp WHERE 0",
    "SELECT COUNT(*), SUM(a), AVG(a), MIN(a), MAX(a), TOTAL(a) FROM empty",
    "SELECT COUNT(b), COUNT(DISTINCT b), SUM(DISTINCT a) FROM empty",
    "SELECT SUM(0.1), AVG(0.1), TOTAL(0.1) FROM emp",
    "SELECT SUM(a), SUM(x), SUM(s), SUM(b) FROM nums",
    "SELECT AVG(x), AVG(a), AVG(s) FROM nums",
    "SELECT SUM(x) FROM nums WHERE x < 1e10",
    "SELECT COUNT(x), COUNT(*), COUNT(s) FROM nums",
    "SELECT MIN(s), MAX(s) FROM nums",
    "SELECT MIN(v), MAX(v), COUNT(v), COUNT(DISTINCT v) FROM mixed",
    "SELECT SUM(v), AVG(v), TOTAL(v) FROM mixed",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept",
    "SELECT dept, SUM(salary), AVG(age) FROM emp GROUP BY dept",
    "SELECT dept, COUNT(*) AS c FROM emp GROUP BY dept HAVING c > 1",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept HAVING COUNT(*) >= 2 "
    "ORDER BY COUNT(*) DESC, dept",
    "SELECT dept, MAX(salary) FROM emp GROUP BY dept ORDER BY 2 DESC, 1",
    "SELECT age > 35, COUNT(*) FROM emp GROUP BY age > 35",
    "SELECT COUNT(*) FROM emp GROUP BY dept",
    "SELECT dept FROM emp GROUP BY dept",
    "SELECT dept, COUNT(*) FROM emp GROUP BY 1",
    "SELECT dept AS d, COUNT(*) FROM emp GROUP BY d",
    "SELECT dept, age / 10 AS decade, COUNT(*) FROM emp GROUP BY dept, decade",
    "SELECT SUM(DISTINCT salary), AVG(DISTINCT salary), COUNT(DISTINCT salary) FROM emp",
    "SELECT dept, COUNT(DISTINCT salary) FROM emp GROUP BY dept",
    "SELECT COUNT(*) FROM emp HAVING COUNT(*) > 5",
    "SELECT COUNT(*) FROM emp HAVING COUNT(*) > 50",
    "SELECT MAX(age), name FROM emp",
    "SELECT MIN(age), name FROM emp",
    "SELECT MAX(salary), id FROM emp",
    "SELECT dept, MIN(age), name FROM emp GROUP BY dept",
    "SELECT dept, MAX(age), name FROM emp WHERE dept <> 'sales' GROUP BY dept",
    "SELECT COUNT(*) + 1, SUM(age) * 2, MAX(age) - MIN(age) FROM emp",
    "SELECT dept, SUM(salary) / COUNT(*) FROM emp GROUP BY dept",
    "SELECT dept, SUM(age) FROM emp GROUP BY dept HAVING SUM(age) > 60 ORDER BY dept",
    "SELECT dept, AVG(salary) AS a FROM emp GROUP BY dept ORDER BY a DESC",
    "SELECT dept, COUNT(*) FROM emp WHERE age > 100 GROUP BY dept",
    "SELECT MAX(age) FROM emp WHERE age < 0",
    "SELECT COUNT(*) FROM emp WHERE dept IS NULL",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept ORDER BY dept",
    "SELECT dept IS NULL, COUNT(*) FROM emp GROUP BY 1 ORDER BY 1",
    "SELECT COUNT(*), dept FROM emp GROUP BY dept HAVING dept LIKE '%s%'",
    "SELECT a % 2, SUM(a), COUNT(a) FROM nums GROUP BY a % 2",
    "SELECT s, COUNT(*) FROM nums GROUP BY s",
    "SELECT v, COUNT(*) FROM mixed GROUP BY v",
    "SELECT n % 3, MIN(w), MAX(w) FROM words GROUP BY n % 3",
    "SELECT COUNT(*) FROM emp e JOIN dept d ON e.dept = d.code",
    "SELECT d.title, COUNT(e.id) FROM dept d LEFT JOIN emp e ON e.dept = d.code "
    "GROUP BY d.title",
    "SELECT d.code, AVG(e.salary), MAX(e.age) FROM dept d LEFT JOIN emp e ON e.dept = d.code "
    "GROUP BY d.code",
    "SELECT d.code, COUNT(*) FROM dept d LEFT JOIN emp e ON e.dept = d.code "
    "GROUP BY d.code ORDER BY COUNT(*) DESC, d.code",
    "SELECT COUNT(*), SUM(age) FROM emp WHERE name LIKE '%a%'",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept HAVING MAX(age) > 40 AND MIN(age) < 40",
    "SELECT SUM(age) AS total_age FROM emp HAVING total_age > 0",
    "SELECT COUNT(*) AS c FROM emp ORDER BY c",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept ORDER BY SUM(age) DESC, dept",
    "SELECT DISTINCT COUNT(*) FROM emp GROUP BY dept",
    "SELECT 1 FROM emp GROUP BY dept",
    "SELECT dept, name FROM emp GROUP BY dept, name HAVING COUNT(*) = 1 ORDER BY dept, name",
    "SELECT COUNT(*) FROM emp LIMIT 0",
    "SELECT SUM(i), SUM(r), SUM(t), SUM(n), MAX(b), MIN(b) FROM aff",
]

JOINS = [
    "SELECT e.name, d.title FROM emp e JOIN dept d ON e.dept = d.code",
    "SELECT e.name, d.title FROM emp e INNER JOIN dept d ON e.dept = d.code",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON e.dept = d.code",
    "SELECT e.name, d.title FROM emp e LEFT OUTER JOIN dept d ON e.dept = d.code",
    "SELECT * FROM emp e LEFT JOIN dept d ON e.dept = d.code",
    "SELECT * FROM dept d JOIN emp e ON e.dept = d.code WHERE e.age > 40",
    "SELECT d.*, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.code",
    "SELECT e.name FROM emp e LEFT JOIN dept d ON e.dept = d.code WHERE d.code IS NULL",
    "SELECT d.code FROM dept d LEFT JOIN emp e ON e.dept = d.code WHERE e.id IS NULL",
    "SELECT d.code, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.code AND e.age > 40",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON e.dept = d.code "
    "AND d.budget > 400000",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON e.dept = d.code "
    "WHERE d.budget > 400000",
    "SELECT e.name, m.name FROM emp e JOIN emp m ON e.mgr = m.id",
    "SELECT e.name, m.name FROM emp e LEFT JOIN emp m ON e.mgr = m.id",
    "SELECT e.name, m.name, d.title FROM emp e LEFT JOIN emp m ON e.mgr = m.id "
    "LEFT JOIN dept d ON m.dept = d.code",
    "SELECT e.name, m.name, d.title FROM emp e JOIN emp m ON e.mgr = m.id "
    "JOIN dept d ON m.dept = d.code WHERE d.floor >= 2",
    "SELECT COUNT(*) FROM emp, dept",
    "SELECT e.id, d.code FROM emp e, dept d WHERE e.dept = d.code AND e.id < 5",
    "SELECT e.id, d.code FROM emp e CROSS JOIN dept d WHERE e.id < 3",
    "SELECT e.id FROM emp e JOIN dept d ON 1 WHERE d.code = e.dept",
    "SELECT e.id FROM emp e JOIN dept d WHERE d.code = e.dept",
    "SELECT name, title FROM emp JOIN dept ON dept = code",
    "SELECT emp.name, dept.title FROM emp JOIN dept ON emp.dept = dept.code",
    "SELECT e.name, d.title FROM emp e JOIN dept d ON e.dept = d.code ORDER BY d.title, e.name",
    "SELECT e.name, d.floor FROM emp e LEFT JOIN dept d ON e.dept = d.code "
    "ORDER BY d.floor DESC, e.name",
    "SELECT d.code, e.id FROM dept d LEFT JOIN emp e ON d.code = e.dept AND e.id > 100",
    "SELECT d.code, e.id FROM dept d LEFT JOIN emp e ON NULL",
    "SELECT a.id, b.id FROM nums a JOIN nums b ON a.a = b.b",
    "SELECT a.id, b.id FROM nums a LEFT JOIN nums b ON a.s = b.a",
    "SELECT a.id, b.id FROM nums a LEFT JOIN nums b ON b.a = a.s",
    "SELECT n.id, w.w FROM nums n JOIN words w ON n.id = w.n WHERE w.w LIKE '%e%'",
    "SELECT e.id, d.code FROM emp e LEFT JOIN dept d ON e.dept = d.code "
    "LEFT JOIN emp m ON m.id = e.mgr WHERE m.id IS NULL",
    "SELECT x.id FROM emp x JOIN emp y ON x.id = y.id + 1 JOIN emp z ON y.id = z.id + 1",
    "SELECT * FROM empty e LEFT JOIN emp ON 1",
    "SELECT * FROM dept d LEFT JOIN empty e ON 1",
]

AFFINITY = [
    "SELECT * FROM aff",
    "SELECT id, typeof(i), typeof(r), typeof(t), typeof(n), typeof(b) FROM aff",
    "SELECT id FROM aff WHERE i = '5'",
    "SELECT id FROM aff WHERE i = ' 5'",
    "SELECT id FROM aff WHERE i = '5.0'",
    "SELECT id FROM aff WHERE t = 5",
    "SELECT id FROM aff WHERE t = 5.0",
    "SELECT id FROM aff WHERE t = 100",
    "SELECT id FROM aff WHERE t = 0.1",
    "SELECT id FROM aff WHERE t > 2",
    "SELECT id FROM aff WHERE +i = '5'",
    "SELECT id FROM aff WHERE +t = 5",
    "SELECT id FROM aff WHERE (i) = '5'",
    "SELECT id FROM aff WHERE b = 5",
    "SELECT id FROM aff WHERE b = '5'",
    "SELECT id FROM aff WHERE b = 3",
    "SELECT id FROM aff WHERE i IN ('5', '12')",
    "SELECT id FROM aff WHERE t IN (5, 100)",
    "SELECT id FROM aff WHERE 5 IN (t)",
    "SELECT id FROM aff WHERE '5' IN (i)",
    "SELECT id FROM aff WHERE i BETWEEN '4' AND '6'",
    "SELECT id FROM aff WHERE r = '5'",
    "SELECT id FROM aff WHERE r > '2'",
    "SELECT id FROM aff WHERE n = '5'",
    "SELECT id FROM aff WHERE n = 7",
    "SELECT id FROM aff WHERE CAST(i AS TEXT) = 5",
    "SELECT id FROM aff WHERE CAST(t AS INTEGER) = '5'",
    "SELECT id FROM aff WHERE i = t",
    "SELECT id FROM aff WHERE t = n",
    "SELECT id FROM aff WHERE r = t",
    "SELECT id FROM aff WHERE b = t",
    "SELECT id FROM aff WHERE i + 0 = '5'",
    "SELECT id FROM aff WHERE CASE i WHEN '5' THEN 1 ELSE 0 END",
    "SELECT id, i || '', r || '', t || '' FROM aff",
    "SELECT id, i LIKE '1%', t LIKE '1%' FROM aff",
    "SELECT id FROM aff WHERE i > 'a'",
    "SELECT id FROM aff WHERE t < 'a'",
]


@pytest.mark.parametrize("sql", BASIC)
def test_basic_select(shared, sql: str) -> None:
    shared.check(sql)


@pytest.mark.parametrize("sql", ORDERING)
def test_ordering(shared, sql: str) -> None:
    shared.check(sql, ordered=True)


@pytest.mark.parametrize("sql", AGGREGATES)
def test_aggregates(shared, sql: str) -> None:
    shared.check(sql)


@pytest.mark.parametrize("sql", JOINS)
def test_joins(shared, sql: str) -> None:
    shared.check(sql)


@pytest.mark.parametrize("sql", AFFINITY)
def test_affinity(shared, sql: str) -> None:
    shared.check(sql)


def test_bare_column_with_max_comes_from_max_row(shared) -> None:
    rows = shared.check("SELECT MAX(age), name FROM emp")
    assert rows == [(60, "ALICE")]
    rows = shared.check("SELECT MIN(salary), name FROM emp")
    assert rows == [(0.0, "Ivan")]


def test_select_star_column_order_across_joins(shared) -> None:
    rows = shared.check("SELECT * FROM dept d JOIN emp e ON e.dept = d.code WHERE e.id = 1")
    assert rows == [("eng", "Engineering", 1000000, 3, 1, "Alice", "eng", 120000.0, 34, None)]


def test_left_join_pads_with_nulls(shared) -> None:
    rows = shared.check(
        "SELECT d.code, e.id FROM dept d LEFT JOIN emp e ON e.dept = d.code WHERE d.code = 'legal'"
    )
    assert rows == [("legal", None)]


def test_empty_aggregate_returns_one_row(shared) -> None:
    rows = shared.check("SELECT COUNT(*), SUM(a), AVG(a), MIN(a), MAX(a) FROM empty")
    assert rows == [(0, None, None, None, None)]


def test_kahan_summation_matches(empty_pair) -> None:
    # Naive left-to-right summation would give 0.6000000000000001 here; SQLite uses
    # Kahan-Babuska-Neumaier compensated summation.
    empty_pair.run("CREATE TABLE f (x REAL)")
    empty_pair.run("INSERT INTO f VALUES (1e20), (1.0), (-1e20), (0.1), (0.2), (0.3)")
    rows = empty_pair.check("SELECT SUM(x), AVG(x), TOTAL(x) FROM f")
    assert rows == [(1.6, 0.26666666666666666, 1.6)]
