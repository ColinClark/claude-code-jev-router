"""Queries compared value-for-value (including Python types) against sqlite3."""

import pytest

from .conftest import Pair

SCHEMA = [
    "CREATE TABLE dept (id INTEGER, name TEXT, budget REAL)",
    "CREATE TABLE emp (id INTEGER, name TEXT, dept_id INTEGER, salary REAL, age INTEGER, "
    "nick TEXT)",
    "CREATE TABLE proj (id INTEGER, emp_id INTEGER, title TEXT, hours INTEGER)",
    "INSERT INTO dept VALUES (1, 'Engineering', 1000000.5), (2, 'Sales', 250000.0), "
    "(3, 'HR', NULL), (4, 'Empty', 10.0)",
    "INSERT INTO emp VALUES "
    "(1, 'Alice', 1, 120000.0, 34, 'al'),"
    "(2, 'Bob', 1, 95000.5, 45, NULL),"
    "(3, 'carol', 2, 70000.0, 29, 'Caz'),"
    "(4, 'Dave', 2, NULL, 51, 'dave'),"
    "(5, 'Eve', NULL, 88000.25, NULL, 'E_ve'),"
    "(6, 'frank', 3, 50000.0, 29, '100%'),"
    "(7, 'Grace', 1, 120000.0, 38, 'g'),"
    "(8, 'Heidi', 9, 43000.0, 22, '')",
    "INSERT INTO proj (id, emp_id, title, hours) VALUES "
    "(1, 1, 'Compiler', 120), (2, 1, 'Parser', 40), (3, 2, 'Parser', 60),"
    "(4, 3, 'Deals', NULL), (5, 7, 'Compiler', 80), (6, 99, 'Orphan', 5)",
    "INSERT INTO proj (id, title) VALUES (7, 'Unassigned')",
]


@pytest.fixture
def data():
    p = Pair()
    p.exec(*SCHEMA)
    yield p
    p.lite.close()


QUERIES = [
    # projection, star, aliases
    "SELECT * FROM emp",
    "SELECT * FROM dept ORDER BY id",
    "SELECT id, name FROM emp WHERE id > 3",
    "SELECT e.* FROM emp e WHERE e.id < 3",
    "SELECT emp.name, emp.age FROM emp",
    "SELECT name AS n, age + 1 AS next_age FROM emp ORDER BY n",
    "SELECT name n FROM emp ORDER BY n DESC",
    "SELECT d.*, e.name FROM dept AS d JOIN emp AS e ON e.dept_id = d.id ORDER BY e.id",
    "SELECT DISTINCT dept_id FROM emp",
    "SELECT DISTINCT dept_id, age FROM emp ORDER BY dept_id, age",
    "SELECT DISTINCT salary FROM emp ORDER BY salary DESC",
    "SELECT 1, 2.5, 'x', NULL FROM dept",
    # WHERE
    "SELECT name FROM emp WHERE salary >= 88000.25",
    "SELECT name FROM emp WHERE salary IS NULL",
    "SELECT name FROM emp WHERE salary IS NOT NULL AND age IS NOT NULL",
    "SELECT name FROM emp WHERE NOT (age > 30)",
    "SELECT name FROM emp WHERE age > 30 OR dept_id = 2",
    "SELECT name FROM emp WHERE age BETWEEN 29 AND 38",
    "SELECT name FROM emp WHERE age NOT BETWEEN 29 AND 38",
    "SELECT name FROM emp WHERE dept_id IN (1, 3)",
    "SELECT name FROM emp WHERE dept_id NOT IN (1, 3)",
    "SELECT name FROM emp WHERE dept_id NOT IN (1, NULL)",
    "SELECT name FROM emp WHERE dept_id IN (1, NULL)",
    "SELECT name FROM emp WHERE name LIKE 'a%'",
    "SELECT name FROM emp WHERE name LIKE '%A%'",
    "SELECT name FROM emp WHERE name NOT LIKE '_a%'",
    "SELECT name FROM emp WHERE nick LIKE '%\\%'",
    "SELECT name FROM emp WHERE nick LIKE '___'",
    "SELECT name FROM emp WHERE nick LIKE ''",
    "SELECT name FROM emp WHERE nick = ''",
    "SELECT name FROM emp WHERE age = 29.0",
    "SELECT name FROM emp WHERE age == 29 AND salary <> 70000",
    "SELECT name FROM emp WHERE age != 29",
    "SELECT name FROM emp WHERE dept_id",
    "SELECT name FROM emp WHERE nick",
    "SELECT name FROM emp WHERE NULL",
    "SELECT name FROM emp WHERE age > '30'",
    "SELECT name FROM emp WHERE nick > 5",
    "SELECT name FROM emp WHERE name = 'alice'",
    "SELECT name FROM emp WHERE name < 'b'",
    # expressions
    "SELECT id, salary / 1000, age / 7, age % 7, -age, age * 2 - 1 FROM emp ORDER BY id",
    "SELECT id, age / 0, age % 0, salary / 0, salary % 0.5 FROM emp ORDER BY id",
    "SELECT id, name || '-' || nick, id || age, salary || '' FROM emp ORDER BY id",
    "SELECT id, age > 30, age = NULL, NULL = NULL, age IS NULL FROM emp ORDER BY id",
    "SELECT id, (age > 30) AND (salary > 60000), (age > 30) OR (salary > 60000) "
    "FROM emp ORDER BY id",
    "SELECT id, NOT age, NOT nick, NOT NULL FROM emp ORDER BY id",
    "SELECT 7 / 2, -7 / 2, 7 % -3, -7 % 3, 7.0 / 2, 7 / 2.0, 1 / 3.0, 2 * 3 + 4 * 5 FROM dept",
    "SELECT 5 - -3, - (2 + 3), 2 + 3 * 4, (2 + 3) * 4, 10 - 2 - 3, 100 / 10 / 5 FROM dept",
    "SELECT 'a' || 1 || 2.5, 1 || NULL, 'x' + 1, '3abc' * 2, '1.5' + 1 FROM dept",
    "SELECT 1 = 1 < 2, 2 < 1 = 0, 1 + 2 || 3, 3 || 1 + 2 FROM dept",
    "SELECT 9223372036854775807 + 1, -9223372036854775808 - 1, 9223372036854775807 * 2 FROM dept",
    "SELECT 1e3, 1.5e-3, .5, 3., 12345678901234567890 FROM dept",
    "SELECT 'it''s', 'A' LIKE 'a', 'a' LIKE 'A', 'abc' LIKE 'a_c', 'ac' LIKE 'a_c' FROM dept",
    "SELECT NULL LIKE 'a', 'a' LIKE NULL, 'a' NOT LIKE NULL, 5 LIKE '5', 2.5 LIKE '2._' FROM dept",
    "SELECT 1 IN (1, 2), 3 IN (1, 2), NULL IN (1), 1 IN (NULL, 1), 3 NOT IN (1, NULL) FROM dept",
    "SELECT 2 BETWEEN 1 AND 3, NULL BETWEEN 1 AND 3, 2 BETWEEN NULL AND 1, "
    "2 BETWEEN NULL AND 3, 5 NOT BETWEEN 1 AND NULL FROM dept",
    "SELECT NULL AND 0, NULL AND 1, NULL OR 1, NULL OR 0, NOT NULL, 0 AND NULL FROM dept",
    "SELECT 1 < 'a', 'a' < 'b', 'B' < 'a', 2 < 10, '2' < '10', NULL < 1 FROM dept",
    "SELECT 1 = 1.0, '1' = 1, 1 IS 1, NULL IS NULL, 1 IS NOT NULL, NULL IS NOT 1 FROM dept",
    "SELECT id, CASE WHEN age < 30 THEN 'young' WHEN age < 45 THEN 'mid' ELSE 'old' END "
    "FROM emp ORDER BY id",
    "SELECT id, CASE dept_id WHEN 1 THEN 'eng' WHEN 2 THEN 'sales' END FROM emp ORDER BY id",
    "SELECT id, COALESCE(salary, age, -1), IFNULL(nick, 'none'), NULLIF(age, 29) "
    "FROM emp ORDER BY id",
    "SELECT id, ABS(-age), UPPER(name), LOWER(nick), LENGTH(nick), TYPEOF(salary) "
    "FROM emp ORDER BY id",
    "SELECT MIN(age, 30), MAX(id, dept_id) FROM emp ORDER BY 1, 2",
    # aggregates without grouping
    "SELECT COUNT(*), COUNT(salary), COUNT(nick), COUNT(DISTINCT dept_id) FROM emp",
    "SELECT SUM(age), AVG(age), MIN(age), MAX(age), SUM(salary), AVG(salary) FROM emp",
    "SELECT MIN(name), MAX(name), MIN(nick), MAX(nick) FROM emp",
    "SELECT SUM(DISTINCT age), AVG(DISTINCT age), COUNT(DISTINCT age) FROM emp",
    "SELECT COUNT(*), SUM(age), AVG(age), MIN(age), MAX(age), COUNT(age) FROM emp WHERE 0",
    "SELECT COUNT(*) FROM emp WHERE age > 100",
    "SELECT SUM(salary) / COUNT(*), MAX(age) - MIN(age) FROM emp",
    "SELECT SUM(hours), TOTAL(hours), AVG(hours) FROM proj WHERE hours IS NULL",
    "SELECT SUM(name), SUM(nick) FROM emp",
    "SELECT MAX(age) + 1, COUNT(*) * 2 FROM emp WHERE dept_id = 1",
    # grouping
    "SELECT dept_id, COUNT(*) FROM emp GROUP BY dept_id",
    "SELECT dept_id, COUNT(*), SUM(salary), AVG(age) FROM emp GROUP BY dept_id ORDER BY dept_id",
    "SELECT dept_id, MAX(salary) FROM emp GROUP BY dept_id HAVING COUNT(*) > 1",
    "SELECT dept_id, COUNT(*) AS c FROM emp GROUP BY dept_id HAVING c >= 2 ORDER BY c DESC, "
    "dept_id",
    "SELECT dept_id FROM emp GROUP BY dept_id HAVING SUM(salary) > 100000 ORDER BY dept_id",
    "SELECT age, COUNT(*) FROM emp GROUP BY age ORDER BY COUNT(*) DESC, age",
    "SELECT age % 2, COUNT(*) FROM emp GROUP BY age % 2 ORDER BY 1",
    "SELECT dept_id, age > 30 AS senior, COUNT(*) FROM emp GROUP BY dept_id, senior "
    "ORDER BY dept_id, senior",
    "SELECT dept_id, COUNT(*) FROM emp GROUP BY 1 ORDER BY 1",
    "SELECT COUNT(*) FROM emp GROUP BY dept_id HAVING dept_id > 5",
    "SELECT dept_id, COUNT(*) FROM emp WHERE age IS NOT NULL GROUP BY dept_id ORDER BY 2, 1",
    "SELECT COUNT(*) FROM emp WHERE 0 GROUP BY dept_id",
    "SELECT dept_id, SUM(salary) FROM emp GROUP BY dept_id ORDER BY SUM(salary) DESC",
    "SELECT dept_id, MIN(name), MAX(name) FROM emp GROUP BY dept_id ORDER BY dept_id",
    "SELECT dept_id, name, MAX(salary) FROM emp WHERE dept_id = 2 GROUP BY dept_id",
    "SELECT name, MIN(age) FROM emp",
    "SELECT COUNT(*) FROM emp HAVING COUNT(*) > 3",
    "SELECT COUNT(*) FROM emp HAVING COUNT(*) > 30",
    "SELECT dept_id * 10, COUNT(DISTINCT age) FROM emp GROUP BY dept_id * 10 ORDER BY 1 DESC",
    # joins
    "SELECT e.name, d.name FROM emp e JOIN dept d ON e.dept_id = d.id",
    "SELECT e.name, d.name FROM emp e INNER JOIN dept d ON e.dept_id = d.id ORDER BY e.name",
    "SELECT e.name, d.name FROM emp e LEFT JOIN dept d ON e.dept_id = d.id ORDER BY e.id",
    "SELECT e.name, d.name FROM emp e LEFT OUTER JOIN dept d ON e.dept_id = d.id "
    "WHERE d.id IS NULL ORDER BY e.id",
    "SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id ORDER BY d.id, e.id",
    "SELECT d.name, COUNT(e.id), COUNT(*) FROM dept d LEFT JOIN emp e ON e.dept_id = d.id "
    "GROUP BY d.name ORDER BY d.name",
    "SELECT d.name, SUM(p.hours) FROM dept d LEFT JOIN emp e ON e.dept_id = d.id "
    "LEFT JOIN proj p ON p.emp_id = e.id GROUP BY d.id ORDER BY d.id",
    "SELECT e.name, p.title FROM emp e JOIN proj p ON p.emp_id = e.id JOIN dept d "
    "ON d.id = e.dept_id WHERE d.name = 'Engineering' ORDER BY e.name, p.title",
    "SELECT e.name, p.title FROM emp e LEFT JOIN proj p ON p.emp_id = e.id AND p.hours > 50 "
    "ORDER BY e.id, p.id",
    "SELECT a.name, b.name FROM emp a JOIN emp b ON a.age = b.age AND a.id < b.id",
    "SELECT a.name, b.name FROM emp a JOIN emp b ON a.dept_id = b.dept_id WHERE a.id <> b.id",
    "SELECT COUNT(*) FROM emp, dept",
    "SELECT COUNT(*) FROM emp CROSS JOIN dept WHERE emp.dept_id = dept.id",
    "SELECT e.name, d.name FROM emp e JOIN dept d ON 1 ORDER BY e.id, d.id LIMIT 5",
    "SELECT p.title, e.name, d.name FROM proj p LEFT JOIN emp e ON p.emp_id = e.id "
    "LEFT JOIN dept d ON e.dept_id = d.id ORDER BY p.id",
    "SELECT e.name FROM emp e LEFT JOIN proj p ON p.emp_id = e.id WHERE p.id IS NULL "
    "ORDER BY e.name",
    "SELECT title, COUNT(*) FROM proj p JOIN emp e ON p.emp_id = e.id GROUP BY title",
    "SELECT name, title FROM emp JOIN proj ON emp_id = emp.id ORDER BY name, title",
    # ordering
    "SELECT name, salary FROM emp ORDER BY salary, id",
    "SELECT name, salary FROM emp ORDER BY salary DESC, name",
    "SELECT name, nick FROM emp ORDER BY nick",
    "SELECT name, nick FROM emp ORDER BY nick DESC",
    "SELECT name FROM emp ORDER BY age DESC, name ASC",
    "SELECT name FROM emp ORDER BY LENGTH(name), name",
    "SELECT name, age FROM emp ORDER BY 2, 1",
    "SELECT name AS x FROM emp ORDER BY x",
    "SELECT name, age * -1 AS neg FROM emp ORDER BY neg, name",
    "SELECT name FROM emp ORDER BY dept_id IS NULL, dept_id, name",
    "SELECT name, age FROM emp ORDER BY age IS NULL DESC, age, name",
    "SELECT name FROM emp ORDER BY salary / 1000 DESC, id",
    "SELECT UPPER(name) AS name FROM emp ORDER BY name",
    "SELECT id FROM emp ORDER BY id DESC",
    # limit/offset
    "SELECT name FROM emp ORDER BY id LIMIT 3",
    "SELECT name FROM emp ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT name FROM emp ORDER BY id LIMIT 2, 3",
    "SELECT name FROM emp ORDER BY id LIMIT 0",
    "SELECT name FROM emp ORDER BY id LIMIT -1 OFFSET 6",
    "SELECT name FROM emp ORDER BY id LIMIT 100 OFFSET 100",
    "SELECT name FROM emp ORDER BY id LIMIT 1 + 1",
    "SELECT DISTINCT age FROM emp ORDER BY age LIMIT 3",
    # case-insensitivity
    "select NAME from EMP where Age > 30 order by Name",
    "SeLeCt e.NaMe FrOm EmP AS E wHeRe E.iD = 1",
    "SELECT COUNT(*), count(*), Sum(age) FROM emp",
    # select without from
    "SELECT 1 + 1, 'a' || 'b', NULL IS NULL",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_query(data, sql):
    data.check(sql)


def test_mutations_match(data):
    data.exec(
        "UPDATE emp SET salary = salary * 1.1 WHERE dept_id = 1",
        "UPDATE emp SET age = age + 1, nick = UPPER(nick) WHERE age < 30",
        "UPDATE emp SET dept_id = NULL WHERE name LIKE 'd%'",
        "DELETE FROM proj WHERE hours IS NULL OR hours < 50",
        "INSERT INTO emp (id, name) VALUES (9, 'Ivan'), (10, 'Judy')",
        "UPDATE dept SET budget = 5",
    )
    for sql in [
        "SELECT * FROM emp ORDER BY id",
        "SELECT * FROM proj ORDER BY id",
        "SELECT * FROM dept ORDER BY id",
        "SELECT dept_id, SUM(salary), COUNT(*) FROM emp GROUP BY dept_id ORDER BY 1",
    ]:
        data.check(sql)
    data.exec("DELETE FROM emp")
    data.check("SELECT COUNT(*), MAX(id) FROM emp")
