"""SELECT/DML behaviour compared against sqlite3."""

import pytest

SCHEMA = [
    "CREATE TABLE emp (id INTEGER, name TEXT, dept INTEGER, salary REAL, boss INTEGER)",
    "CREATE TABLE dept (id INTEGER, title TEXT, budget INTEGER)",
    "CREATE TABLE proj (id INTEGER, emp_id INTEGER, label TEXT)",
    """INSERT INTO emp VALUES
        (1, 'Alice', 10, 5000.0, NULL),
        (2, 'bob', 10, 4000.0, 1),
        (3, 'Carol', 20, 4500.5, 1),
        (4, 'dave', 20, NULL, 3),
        (5, 'Eve', NULL, 3000.0, 3),
        (6, 'frank', 30, 4000.0, NULL),
        (7, NULL, 10, 2500.25, 2)""",
    """INSERT INTO dept VALUES (10, 'Eng', 100000), (20, 'Sales', 50000), (40, 'Legal', NULL),
        (50, NULL, 0)""",
    """INSERT INTO proj (id, emp_id, label) VALUES (1, 1, 'x'), (2, 1, 'y'), (3, 3, 'x'),
        (4, 9, 'z'), (5, NULL, 'w')""",
]


@pytest.fixture
def co(both):
    for stmt in SCHEMA:
        both.run(stmt)
    return both


QUERIES = [
    "SELECT * FROM emp",
    "SELECT id, name FROM emp WHERE salary > 4000",
    "SELECT * FROM emp WHERE salary IS NULL",
    "SELECT * FROM emp WHERE dept IS NOT NULL AND salary >= 4000",
    "SELECT * FROM emp WHERE NOT (dept = 10)",
    "SELECT * FROM emp WHERE name LIKE '%a%'",
    "SELECT * FROM emp WHERE name NOT LIKE '%a%'",
    "SELECT * FROM emp WHERE dept IN (10, 30)",
    "SELECT * FROM emp WHERE dept NOT IN (10, NULL)",
    "SELECT * FROM emp WHERE salary BETWEEN 3000 AND 4500",
    "SELECT * FROM emp WHERE id > 2 OR dept = 10",
    "SELECT * FROM emp ORDER BY salary",
    "SELECT * FROM emp ORDER BY salary DESC, id",
    "SELECT * FROM emp ORDER BY name",
    "SELECT * FROM emp ORDER BY name DESC",
    "SELECT * FROM emp ORDER BY dept DESC, salary ASC, id",
    "SELECT name, salary * 2 AS double FROM emp ORDER BY double DESC, name",
    "SELECT name AS n FROM emp ORDER BY n",
    "SELECT id, name FROM emp ORDER BY 2",
    "SELECT id, name FROM emp ORDER BY 2 DESC",
    "SELECT id FROM emp ORDER BY salary IS NULL, salary",
    "SELECT id, dept AS salary FROM emp ORDER BY salary, id",
    "SELECT id FROM emp ORDER BY -id",
    "SELECT id FROM emp ORDER BY id LIMIT 3",
    "SELECT id FROM emp ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT id FROM emp ORDER BY id LIMIT 2, 3",
    "SELECT id FROM emp ORDER BY id LIMIT 0",
    "SELECT id FROM emp ORDER BY id LIMIT -1 OFFSET 5",
    "SELECT id FROM emp ORDER BY id LIMIT 100 OFFSET 100",
    "SELECT DISTINCT dept FROM emp",
    "SELECT DISTINCT dept FROM emp ORDER BY dept DESC",
    "SELECT DISTINCT salary FROM emp ORDER BY 1",
    "SELECT DISTINCT dept, boss IS NULL FROM emp",
    "SELECT count(*) FROM emp",
    "SELECT count(*), count(salary), count(dept), count(DISTINCT dept) FROM emp",
    "SELECT sum(salary), avg(salary), min(salary), max(salary) FROM emp",
    "SELECT sum(id), avg(id), total(id) FROM emp",
    "SELECT min(name), max(name) FROM emp",
    "SELECT count(*), sum(id), avg(id), min(id), max(id), total(id) FROM emp WHERE id > 100",
    "SELECT count(DISTINCT salary), sum(DISTINCT salary), avg(DISTINCT salary) FROM emp",
    "SELECT dept, count(*) FROM emp GROUP BY dept",
    "SELECT dept, count(*), sum(salary), avg(salary) FROM emp GROUP BY dept ORDER BY dept",
    "SELECT dept, max(salary) FROM emp GROUP BY dept HAVING count(*) > 1",
    "SELECT dept, max(salary) AS m FROM emp GROUP BY dept HAVING m > 4000 ORDER BY m",
    "SELECT dept, count(*) AS c FROM emp GROUP BY dept ORDER BY c DESC, dept",
    "SELECT dept, count(*) FROM emp GROUP BY 1 ORDER BY 1",
    "SELECT dept % 20 AS k, count(*) FROM emp GROUP BY k ORDER BY k",
    "SELECT dept, boss, count(*) FROM emp GROUP BY dept, boss ORDER BY dept, boss",
    "SELECT count(*) FROM emp GROUP BY dept HAVING sum(salary) IS NULL",
    "SELECT dept FROM emp GROUP BY dept ORDER BY sum(salary) DESC",
    "SELECT dept, sum(salary) * 2 + count(*) FROM emp GROUP BY dept",
    "SELECT count(*) FROM emp HAVING count(*) > 3",
    "SELECT count(*) FROM emp HAVING count(*) > 30",
    "SELECT dept, name, max(salary) FROM emp GROUP BY dept",
    "SELECT dept, name, min(salary) FROM emp GROUP BY dept",
    "SELECT max(salary), name FROM emp",
    "SELECT dept, count(*) FROM emp WHERE id > 100 GROUP BY dept",
    "SELECT sum(salary) FROM emp WHERE dept = 20",
    "SELECT avg(dept), sum(dept) FROM emp",
    "SELECT count(name), count(DISTINCT name), min(name || '!') FROM emp",
    "SELECT e.name, d.title FROM emp e JOIN dept d ON e.dept = d.id",
    "SELECT e.name, d.title FROM emp AS e INNER JOIN dept AS d ON e.dept = d.id",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON e.dept = d.id",
    "SELECT e.name, d.title FROM emp e LEFT OUTER JOIN dept d ON e.dept = d.id",
    "SELECT d.title, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.id",
    "SELECT d.title, count(e.id) FROM dept d LEFT JOIN emp e ON e.dept = d.id GROUP BY d.id",
    "SELECT d.title, count(*) FROM dept d LEFT JOIN emp e ON e.dept = d.id GROUP BY d.title",
    "SELECT * FROM emp e LEFT JOIN dept d ON e.dept = d.id AND d.budget > 60000",
    "SELECT * FROM emp e LEFT JOIN dept d ON e.dept = d.id WHERE d.id IS NULL",
    "SELECT e.*, d.title FROM emp e JOIN dept d ON e.dept = d.id",
    "SELECT d.*, e.id FROM emp e JOIN dept d ON e.dept = d.id",
    "SELECT e.name, b.name FROM emp e LEFT JOIN emp b ON e.boss = b.id",
    "SELECT e.name, p.label, d.title FROM emp e JOIN proj p ON p.emp_id = e.id "
    "LEFT JOIN dept d ON d.id = e.dept",
    "SELECT e.name, p.label, d.title FROM emp e LEFT JOIN proj p ON p.emp_id = e.id "
    "LEFT JOIN dept d ON d.id = e.dept",
    "SELECT e.name, p.label FROM emp e LEFT JOIN proj p ON p.emp_id = e.id "
    "JOIN dept d ON d.id = e.dept",
    "SELECT title, name FROM emp JOIN dept ON dept = dept.id",
    "SELECT emp.name, dept.title FROM emp JOIN dept ON emp.dept = dept.id WHERE budget > 60000",
    "SELECT count(*) FROM emp, dept",
    "SELECT e.id, d.id FROM emp e CROSS JOIN dept d WHERE e.id = 1",
    "SELECT * FROM emp JOIN dept ON 1",
    "SELECT * FROM emp LEFT JOIN dept ON 0",
    "SELECT * FROM emp LEFT JOIN dept ON NULL",
    "SELECT e.name, sum(p.id) FROM emp e LEFT JOIN proj p ON p.emp_id = e.id GROUP BY e.name",
    "SELECT d.title, avg(e.salary) FROM dept d LEFT JOIN emp e ON e.dept = d.id "
    "GROUP BY d.title HAVING avg(e.salary) IS NULL OR avg(e.salary) > 3000",
    "SELECT upper(name), length(name) FROM emp",
    "SELECT name || ' (' || dept || ')' FROM emp",
    "SELECT id, CASE WHEN salary > 4000 THEN 'high' WHEN salary IS NULL THEN '?' "
    "ELSE 'low' END FROM emp",
    "SELECT id / 2, id % 3, salary / 3, salary % 3 FROM emp",
    "SELECT 1 + 1",
    "SELECT count(*)",
    "SELECT id FROM emp WHERE salary",
    "SELECT id FROM emp WHERE name",
    "SELECT id FROM emp WHERE boss",
    "SELECT id, salary FROM emp ORDER BY salary DESC LIMIT 2",
    "SELECT dept, count(*) FROM emp GROUP BY dept ORDER BY count(*) DESC, dept LIMIT 2",
    "SELECT Name, DEPT FROM EMP WHERE Dept = 10",
    "select e.NAME from Emp E where E.ID = 1",
    "SELECT id FROM emp WHERE id IN (1, '2', 3.0)",
    "SELECT id FROM emp WHERE name = 'alice'",
    "SELECT id FROM emp WHERE name > 'a'",
    "SELECT sum(salary) / count(*) FROM emp",
    "SELECT dept, group_concat(name) FROM emp WHERE name IS NOT NULL AND dept = 20 GROUP BY dept",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_query_matches_sqlite(co, sql):
    co.check(sql)


DML = [
    ["UPDATE emp SET salary = salary + 100 WHERE dept = 10"],
    ["UPDATE emp SET salary = NULL, name = 'x' WHERE id > 5"],
    ["UPDATE emp SET dept = boss, boss = dept"],
    ["UPDATE emp SET salary = 7 WHERE salary IS NULL"],
    ["UPDATE emp SET name = id"],
    ["UPDATE emp SET id = '42' WHERE id = 1"],
    ["UPDATE emp SET salary = 3"],
    ["UPDATE emp SET salary = '3.5x'"],
    ["DELETE FROM emp WHERE dept = 10"],
    ["DELETE FROM emp WHERE salary > 1000 AND dept IS NULL"],
    ["DELETE FROM emp WHERE NULL"],
    ["DELETE FROM emp"],
    ["INSERT INTO emp (id, name) VALUES (8, 'Zed'), (9, 'Amy')"],
    ["INSERT INTO emp (name, id) VALUES ('Rev', 10)"],
    ["INSERT INTO emp VALUES (11, 12, '13', '14.5', 15.0)"],
    ["INSERT INTO emp VALUES (12, 'n', 1 + 2, 10 / 4, -5)"],
    ["INSERT INTO emp VALUES ('13', 'n', '1.0', 2, '3e1')"],
    ["INSERT INTO emp (id) VALUES (NULL)", "DELETE FROM emp WHERE id IS NULL"],
]


@pytest.mark.parametrize("stmts", DML)
def test_dml_matches_sqlite(co, stmts):
    for s in stmts:
        assert co.db.execute(s) == []
        co.lite.execute(s)
    co.check("SELECT * FROM emp")
    co.check("SELECT typeof(id), typeof(name), typeof(dept), typeof(salary), typeof(boss) FROM emp")
