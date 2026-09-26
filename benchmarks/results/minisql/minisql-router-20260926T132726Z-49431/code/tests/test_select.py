"""SELECT clauses: projection, WHERE, DISTINCT, ORDER BY, LIMIT/OFFSET."""

import pytest

QUERIES = [
    "SELECT * FROM emp",
    "SELECT e.* FROM emp e",
    "SELECT id, name FROM emp",
    "SELECT id AS x, name n FROM emp",
    "SELECT id * 2 + 1, name || '!' FROM emp",
    "SELECT name FROM emp WHERE salary > 80000",
    "SELECT name FROM emp WHERE salary IS NULL",
    "SELECT name FROM emp WHERE dept = 'eng' AND age < 40",
    "SELECT name FROM emp WHERE dept = 'eng' OR dept IS NULL",
    "SELECT name FROM emp WHERE NOT dept = 'eng'",
    "SELECT name FROM emp WHERE dept != 'eng'",
    "SELECT name FROM emp WHERE dept IN ('hr', 'ops')",
    "SELECT name FROM emp WHERE dept NOT IN ('hr', 'ops')",
    "SELECT name FROM emp WHERE dept NOT IN ('hr', NULL)",
    "SELECT name FROM emp WHERE age BETWEEN 30 AND 45",
    "SELECT name FROM emp WHERE age NOT BETWEEN 30 AND 45",
    "SELECT name FROM emp WHERE name LIKE '%a%'",
    "SELECT name FROM emp WHERE name LIKE 'A%'",
    "SELECT name FROM emp WHERE name NOT LIKE '%e%'",
    "SELECT name FROM emp WHERE name LIKE '____'",
    "SELECT name FROM emp WHERE name LIKE '%\\_%' ESCAPE '\\'",
    "SELECT name FROM emp WHERE name LIKE '%\\%' ESCAPE '\\'",
    "SELECT name FROM emp WHERE boss",
    "SELECT name FROM emp WHERE salary",
    "SELECT name FROM emp WHERE NULL",
    "SELECT name FROM emp WHERE age > 30 AND salary > 60000 OR dept = 'hr'",
    "SELECT name FROM emp WHERE (age > 30 AND salary > 60000) OR NOT (dept <> 'hr')",
    "SELECT DISTINCT dept FROM emp",
    "SELECT DISTINCT dept, age > 40 FROM emp",
    "SELECT DISTINCT salary FROM emp",
    "SELECT ALL dept FROM emp",
    "SELECT name FROM emp ORDER BY name",
    "SELECT name FROM emp ORDER BY name DESC",
    "SELECT name, salary FROM emp ORDER BY salary, id",
    "SELECT name, salary FROM emp ORDER BY salary DESC, id",
    "SELECT name, salary FROM emp ORDER BY salary ASC, id DESC",
    "SELECT dept, name FROM emp ORDER BY dept, name",
    "SELECT dept, name FROM emp ORDER BY dept DESC, name ASC",
    "SELECT id, age FROM emp ORDER BY age DESC, id",
    "SELECT id, salary * 2 AS double FROM emp ORDER BY double DESC, id",
    "SELECT id, age AS a FROM emp ORDER BY a, id",
    "SELECT id FROM emp ORDER BY 1 DESC",
    "SELECT name, id FROM emp ORDER BY 2",
    "SELECT id FROM emp ORDER BY age IS NULL, age, id",
    "SELECT id FROM emp ORDER BY salary / 1000 + age, id",
    "SELECT name FROM emp ORDER BY lower(name)",
    "SELECT name FROM emp ORDER BY length(name), name",
    "SELECT id FROM emp ORDER BY dept NULLS LAST, id",
    "SELECT id FROM emp ORDER BY dept DESC NULLS FIRST, id",
    "SELECT id, name FROM emp ORDER BY id LIMIT 3",
    "SELECT id, name FROM emp ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT id, name FROM emp ORDER BY id LIMIT 2, 3",
    "SELECT id FROM emp ORDER BY id LIMIT 0",
    "SELECT id FROM emp ORDER BY id LIMIT -1",
    "SELECT id FROM emp ORDER BY id LIMIT -1 OFFSET 8",
    "SELECT id FROM emp ORDER BY id LIMIT 100 OFFSET 100",
    "SELECT id FROM emp ORDER BY id LIMIT 1 + 1",
    "SELECT DISTINCT dept FROM emp ORDER BY dept",
    "SELECT DISTINCT dept FROM emp ORDER BY dept DESC LIMIT 2",
    "SELECT id AS x FROM emp WHERE x > 5",
    "SELECT id + 1 AS id FROM emp ORDER BY id DESC",
    "SELECT name FROM emp e WHERE e.id = 3",
    "SELECT emp.name FROM emp WHERE emp.id < 3",
    "SELECT 1, 'a', NULL",
    "SELECT 1 + 1 AS two ORDER BY two",
    "SELECT t, i FROM nums ORDER BY t",
    "SELECT t, i FROM nums ORDER BY t DESC",
    "SELECT r, i FROM nums ORDER BY r, i",
    "SELECT i FROM nums ORDER BY i DESC",
    "SELECT coalesce(t, i, r) AS m FROM nums ORDER BY m",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_select(sample, sql):
    sample.check(sql)


def test_mixed_type_ordering(pair):
    p = pair("CREATE TABLE m (v TEXT, k INTEGER)")
    p.run("CREATE TABLE x (v, k INTEGER)")
    p.run("INSERT INTO x VALUES (1, 1), ('a', 2), (NULL, 3), (2.5, 4), ('B', 5), (-3, 6)")
    p.check("SELECT v FROM x ORDER BY v")
    p.check("SELECT v FROM x ORDER BY v DESC")
    p.check("SELECT k FROM x WHERE v > 2 ORDER BY k")
    p.check("SELECT k FROM x WHERE v < 'a' ORDER BY k")


def test_select_star_empty_table(pair):
    p = pair("CREATE TABLE e (a INTEGER, b TEXT)")
    p.check("SELECT * FROM e")
    p.check("SELECT a FROM e WHERE a > 1 ORDER BY a")
