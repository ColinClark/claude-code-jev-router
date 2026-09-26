"""Differential tests: every query must return exactly what SQLite returns."""

import pytest

from .conftest import assert_same

QUERIES = [
    # --- basic projection / filtering
    "SELECT * FROM emp",
    "SELECT id, name FROM emp WHERE dept = 'eng'",
    "SELECT e.* FROM emp e WHERE e.age > 30",
    "SELECT name AS n, salary * 2 AS double_pay FROM emp",
    "SELECT name n FROM emp",
    "SELECT emp.name FROM emp WHERE emp.id <= 3",
    "SELECT ID, NAME FROM EMP WHERE DEPT = 'eng'",
    "select Id, nAmE from Emp where dEpT = 'eng'",
    "SELECT 1, 2.5, 'x', NULL FROM emp WHERE id = 1",
    "SELECT 1 + 1",
    "SELECT * FROM empty",
    "SELECT a, b FROM empty WHERE a > 1",
    # --- WHERE with three-valued logic
    "SELECT id FROM emp WHERE salary > 60000 AND age < 40",
    "SELECT id FROM emp WHERE salary > 60000 OR age < 40",
    "SELECT id FROM emp WHERE NOT (salary > 60000)",
    "SELECT id FROM emp WHERE NOT (age > 30 AND salary > 60000)",
    "SELECT id FROM emp WHERE NOT (age > 30 OR salary > 60000)",
    "SELECT id FROM emp WHERE salary = NULL",
    "SELECT id FROM emp WHERE salary != NULL",
    "SELECT id FROM emp WHERE salary IS NULL",
    "SELECT id FROM emp WHERE salary IS NOT NULL",
    "SELECT id FROM emp WHERE dept <> 'eng'",
    "SELECT id FROM emp WHERE dept != 'eng' OR dept IS NULL",
    "SELECT id FROM emp WHERE age == 29",
    "SELECT id FROM emp WHERE boss",
    "SELECT id FROM emp WHERE name",
    "SELECT id, (age > 30) AND (salary > 60000), (age > 30) OR (salary > 60000) FROM emp",
    "SELECT id, NOT age, NOT salary, NOT NULL FROM emp",
    "SELECT NULL AND 0, NULL AND 1, NULL OR 0, NULL OR 1, NULL AND NULL, NULL OR NULL",
    "SELECT 1 = 1, 1 = 2, 1 < 2, 2 <= 2, 3 > 4, 3 >= 3, 1 = NULL, NULL = NULL",
    "SELECT NULL IS NULL, 1 IS NULL, NULL IS NOT NULL, 1 IS NOT NULL",
    "SELECT 1 IS 1, NULL IS NULL, 1 IS NULL, 1 IS NOT 2, NULL IS NOT NULL",
    # --- IN / BETWEEN / LIKE
    "SELECT id FROM emp WHERE dept IN ('eng', 'hr')",
    "SELECT id FROM emp WHERE dept NOT IN ('eng', 'hr')",
    "SELECT id FROM emp WHERE age IN (29, NULL)",
    "SELECT id FROM emp WHERE age NOT IN (29, NULL)",
    "SELECT id, age IN (29, 34), age NOT IN (29, 34), age IN (NULL, 29) FROM emp",
    "SELECT 1 IN (1, 2), 3 IN (1, 2), NULL IN (1), 1 IN (NULL), 1 NOT IN (NULL, 2), NULL IN ()",
    "SELECT id FROM emp WHERE age BETWEEN 30 AND 45",
    "SELECT id FROM emp WHERE age NOT BETWEEN 30 AND 45",
    "SELECT id, age BETWEEN 30 AND NULL, age NOT BETWEEN NULL AND 30 FROM emp",
    "SELECT id FROM emp WHERE salary BETWEEN 65000 AND 95000 AND dept = 'hr'",
    "SELECT id FROM emp WHERE name LIKE 'a%'",
    "SELECT id FROM emp WHERE name LIKE '%A%'",
    "SELECT id FROM emp WHERE name LIKE '_ve'",
    "SELECT id FROM emp WHERE name NOT LIKE '%e%'",
    "SELECT id FROM emp WHERE name LIKE 'judy_x'",
    "SELECT id FROM emp WHERE name LIKE '%'",
    "SELECT id FROM emp WHERE dept LIKE NULL",
    "SELECT 'abc' LIKE 'ABC', 'abc' LIKE 'a_c', 'abc' LIKE 'a', 'a.c' LIKE 'a.c', 'abc' LIKE 'a.c'",
    "SELECT 10 LIKE '1%', 1.5 LIKE '1.5', NULL LIKE 'a', 'a' LIKE NULL, 'a\nb' LIKE 'a_b'",
    "SELECT s, s LIKE 'a_b', s LIKE 'A%B', s LIKE 'hello' FROM nums",
    # --- arithmetic
    "SELECT a, b, a + b, a - b, a * b, a / b, a % b FROM nums",
    "SELECT a, x, a + x, a * x, a / x, a % x, x % 2 FROM nums",
    "SELECT 7 / 2, -7 / 2, 7 / -2, 7.0 / 2, 7 / 2.0, 1 / 0, 1.0 / 0, 1 % 0, 0 / 0",
    "SELECT 7 % 3, -7 % 3, 7 % -3, -7 % -3, 5.5 % 2, 7 % 2.5, 5 % 0.5, -5.5 % 2",
    "SELECT 2 * 3, 2.0 * 3, 0.1 + 0.2, 1e3, .5, 1.5e-3, 3 - 5, -3 * -3",
    "SELECT -a, -x, - -a, -NULL, +a FROM nums",
    "SELECT 9223372036854775807 + 1, -9223372036854775808 - 1, 9223372036854775807 * 2",
    "SELECT 9223372036854775807, -9223372036854775808, 9223372036854775808",
    "SELECT s + 1, s * 2, -s FROM nums",
    "SELECT '3' + '4', '3.0' + 1, '12abc' + 1, 'abc' * 2, ' 5 ' + 0",
    "SELECT 1 + NULL, NULL * 2, NULL / 0, NULL % 2",
    "SELECT 2 + 3 * 4, (2 + 3) * 4, 10 - 4 - 3, 100 / 10 / 5, 2 * 3 % 4, -2 * 3",
    "SELECT id, salary / 1000, salary / 3, age / 7, age % 7 FROM emp",
    # --- string concatenation
    "SELECT name || ' (' || dept || ')' FROM emp",
    "SELECT 'a' || 1, 1 || 2, 1.5 || 'x', 'x' || NULL, 1.0 || '', 0.1 || '', 100.0 || ''",
    "SELECT x || '', a || x FROM nums",
    "SELECT 1e20 || '', 1.5e-7 || '', 1e16 || '', 1e17 || '', 0.00001 || '', 123456789.125 || ''",
    "SELECT (0.1 + 0.2) || '', (1 / 3.0) || '', 1e15 || '', 1e14 || '', 123456789012345.6 || ''",
    "SELECT CAST(' -12.5e3x' AS INTEGER), CAST('99999999999999999999' AS INTEGER), CAST('-' AS INTEGER)",
    "SELECT 1 || 2 + 3, 2 * 3 || 4, -1 || 1",
    # --- comparisons across types / affinity
    "SELECT 1 < 'a', 'a' < 1, 1 = 1.0, 'a' < 'b', 'B' < 'a', NULL < 1",
    "SELECT id FROM emp WHERE age = '34'",
    "SELECT id FROM emp WHERE age > '40'",
    "SELECT id FROM emp WHERE age IN ('29', '34')",
    "SELECT a FROM nums WHERE s = 10",
    "SELECT a FROM nums WHERE s > 5",
    "SELECT a FROM nums WHERE s IN (10, 3.5)",
    "SELECT a FROM nums WHERE x = '1.5'",
    "SELECT a FROM nums WHERE a BETWEEN '1' AND '7'",
    "SELECT '10' = 10, '10' < 9, 10 = '10'",
    # --- DISTINCT
    "SELECT DISTINCT dept FROM emp",
    "SELECT DISTINCT dept, age > 30 FROM emp",
    "SELECT DISTINCT salary FROM emp ORDER BY salary",
    "SELECT DISTINCT dept FROM emp ORDER BY dept DESC",
    "SELECT ALL dept FROM emp",
    # --- ORDER BY
    "SELECT id, salary FROM emp ORDER BY salary, id",
    "SELECT id, salary FROM emp ORDER BY salary DESC, id",
    "SELECT id, dept FROM emp ORDER BY dept, id DESC",
    "SELECT id, dept FROM emp ORDER BY dept DESC, id",
    "SELECT id, name FROM emp ORDER BY name",
    "SELECT id, age FROM emp ORDER BY age ASC, id ASC",
    "SELECT id, name AS n FROM emp ORDER BY n DESC",
    "SELECT id, salary * -1 AS neg FROM emp ORDER BY neg, id",
    "SELECT id, name FROM emp ORDER BY 2",
    "SELECT id, dept, age FROM emp ORDER BY 2, 3 DESC, 1",
    "SELECT id FROM emp ORDER BY age * 2 + id, id",
    "SELECT id FROM emp ORDER BY length(name), name",
    "SELECT name FROM emp ORDER BY boss, id",
    "SELECT id, age FROM emp ORDER BY age NULLS LAST, id",
    "SELECT id, age FROM emp ORDER BY age DESC NULLS FIRST, id",
    "SELECT s FROM nums ORDER BY s",
    "SELECT a, x FROM nums ORDER BY x DESC, a",
    "SELECT * FROM emp ORDER BY id LIMIT 3",
    "SELECT * FROM emp ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT * FROM emp ORDER BY id LIMIT 3 OFFSET 20",
    "SELECT * FROM emp ORDER BY id LIMIT 0",
    "SELECT * FROM emp ORDER BY id LIMIT -1 OFFSET 7",
    "SELECT * FROM emp ORDER BY id LIMIT 2, 3",
    "SELECT * FROM emp ORDER BY id LIMIT 1 + 1",
    "SELECT id FROM emp ORDER BY id DESC LIMIT 4",
    # --- aggregates without GROUP BY
    "SELECT COUNT(*), COUNT(salary), COUNT(dept), COUNT(DISTINCT dept) FROM emp",
    "SELECT SUM(salary), AVG(salary), MIN(salary), MAX(salary) FROM emp",
    "SELECT SUM(age), AVG(age), MIN(age), MAX(age) FROM emp",
    "SELECT MIN(name), MAX(name), MIN(dept), MAX(dept) FROM emp",
    "SELECT COUNT(*), SUM(a), AVG(a), MIN(a), MAX(a), COUNT(a) FROM empty",
    "SELECT COUNT(*), SUM(salary), AVG(salary), MAX(name) FROM emp WHERE id > 100",
    "SELECT SUM(DISTINCT salary), AVG(DISTINCT salary), COUNT(DISTINCT salary) FROM emp",
    "SELECT SUM(a), SUM(x), AVG(a), AVG(x), SUM(s), SUM(b) FROM nums",
    "SELECT MIN(s), MAX(s), MIN(x), MAX(x) FROM nums",
    "SELECT SUM(a) FROM nums WHERE a IS NULL",
    "SELECT COUNT(*) + 1, SUM(age) / COUNT(age), MAX(age) - MIN(age) FROM emp",
    "SELECT SUM(0.1) FROM emp",
    "SELECT TOTAL(age), TOTAL(salary) FROM emp",
    "SELECT COUNT(*) FROM emp WHERE salary > (65000)",
    "SELECT name, MAX(salary) FROM emp",
    "SELECT name, MIN(age) FROM emp",
    # --- GROUP BY / HAVING
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept",
    "SELECT dept, COUNT(*), SUM(salary), AVG(salary), MIN(age), MAX(age) FROM emp GROUP BY dept",
    "SELECT dept, COUNT(*) AS c FROM emp GROUP BY dept ORDER BY c DESC, dept",
    "SELECT dept, AVG(salary) FROM emp GROUP BY dept HAVING AVG(salary) > 70000",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept HAVING COUNT(*) > 1 ORDER BY dept",
    "SELECT dept FROM emp GROUP BY dept HAVING MAX(age) < 50",
    "SELECT dept, SUM(salary) FROM emp GROUP BY dept ORDER BY SUM(salary) DESC",
    "SELECT dept, SUM(salary) FROM emp GROUP BY dept ORDER BY COUNT(*) DESC, dept",
    "SELECT dept, age > 30 AS old, COUNT(*) FROM emp GROUP BY dept, old ORDER BY dept, old",
    "SELECT age % 2, COUNT(*) FROM emp GROUP BY age % 2 ORDER BY 1",
    "SELECT dept, COUNT(*) FROM emp GROUP BY 1 ORDER BY 1",
    "SELECT dept, COUNT(DISTINCT age) FROM emp GROUP BY dept ORDER BY dept",
    "SELECT dept, name, MAX(salary) FROM emp GROUP BY dept ORDER BY dept",
    "SELECT dept, MIN(salary) + MAX(salary) FROM emp GROUP BY dept ORDER BY dept",
    "SELECT COUNT(*) FROM emp HAVING COUNT(*) > 5",
    "SELECT COUNT(*) FROM emp HAVING COUNT(*) > 50",
    "SELECT a, COUNT(*) FROM empty GROUP BY a",
    "SELECT b, COUNT(*), SUM(a) FROM empty GROUP BY b",
    "SELECT COUNT(*), MAX(a) FROM empty HAVING COUNT(*) = 0",
    "SELECT dept, COUNT(*) FROM emp WHERE age > 30 GROUP BY dept HAVING SUM(salary) IS NOT NULL",
    "SELECT dept, COUNT(*) c FROM emp GROUP BY dept HAVING c >= 2 ORDER BY dept",
    "SELECT DISTINCT COUNT(*) FROM emp GROUP BY dept",
    "SELECT b, SUM(a) % 3, AVG(x) FROM nums GROUP BY b ORDER BY b",
    # --- joins
    "SELECT e.name, d.floor FROM emp e JOIN dept d ON e.dept = d.name",
    "SELECT e.name, d.floor FROM emp e INNER JOIN dept d ON e.dept = d.name ORDER BY e.id",
    "SELECT e.name, d.floor, d.budget FROM emp e LEFT JOIN dept d ON e.dept = d.name",
    "SELECT e.name, d.name FROM emp e LEFT OUTER JOIN dept d ON e.dept = d.name WHERE d.name IS NULL",
    "SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.name ORDER BY d.name, e.id",
    "SELECT d.name, COUNT(e.id), COUNT(*) FROM dept d LEFT JOIN emp e ON e.dept = d.name "
    "GROUP BY d.name ORDER BY d.name",
    "SELECT d.name, SUM(e.salary), AVG(e.age) FROM dept d LEFT JOIN emp e ON e.dept = d.name "
    "GROUP BY d.name",
    "SELECT e.name, b.name AS boss FROM emp e LEFT JOIN emp b ON e.boss = b.id ORDER BY e.id",
    "SELECT e.name, b.name, bb.name FROM emp e JOIN emp b ON e.boss = b.id "
    "JOIN emp bb ON b.boss = bb.id",
    "SELECT e.name, b.name, d.floor FROM emp e LEFT JOIN emp b ON e.boss = b.id "
    "LEFT JOIN dept d ON b.dept = d.name ORDER BY e.id",
    "SELECT * FROM emp e JOIN dept d ON e.dept = d.name ORDER BY e.id",
    "SELECT d.*, e.id FROM emp e JOIN dept d ON e.dept = d.name ORDER BY e.id",
    "SELECT e.id, d.name FROM emp e JOIN dept d ON d.floor > 2 ORDER BY e.id, d.name",
    "SELECT e.id, d.name FROM emp e LEFT JOIN dept d ON e.dept = d.name AND d.floor > 1 ORDER BY e.id",
    "SELECT e.id FROM emp e LEFT JOIN dept d ON 0",
    "SELECT e.id, d.name FROM emp e LEFT JOIN dept d ON 1 = 1 WHERE e.id < 3 ORDER BY 1, 2",
    "SELECT emp.name, dept.floor FROM emp JOIN dept ON emp.dept = dept.name",
    "SELECT age, floor FROM emp JOIN dept AS d ON dept = d.name ORDER BY floor, age",
    "SELECT e.id, n.a FROM emp e JOIN nums n ON e.id = n.a ORDER BY e.id",
    "SELECT e.id, n.a FROM emp e LEFT JOIN nums n ON e.id = n.a LEFT JOIN dept d ON d.floor = n.b "
    "ORDER BY e.id",
    # --- scalar functions / cast
    "SELECT ABS(a), ABS(x), LENGTH(s), UPPER(s), LOWER(s), TYPEOF(x) FROM nums",
    "SELECT COALESCE(salary, age, -1), IFNULL(dept, 'none'), NULLIF(age, 29) FROM emp",
    "SELECT MIN(a, b), MAX(a, b, 3) FROM nums",
    "SELECT CAST(x AS INTEGER), CAST(a AS REAL), CAST(a AS TEXT), CAST(s AS INTEGER) FROM nums",
    "SELECT CAST(s AS REAL), CAST(s AS NUMERIC), CAST('12.0' AS NUMERIC) FROM nums",
    # --- expressions on aggregates / aliases
    "SELECT dept AS d, COUNT(*) FROM emp GROUP BY d ORDER BY d",
    "SELECT salary AS s FROM emp WHERE s > 80000",
    "SELECT id, age * 2 AS twice FROM emp ORDER BY twice DESC, id",
    "SELECT dept, MAX(age) - MIN(age) AS spread FROM emp GROUP BY dept ORDER BY spread, dept",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_matches_sqlite(db, lite, sql):
    assert_same(db, lite, sql)


MUTATIONS = [
    ["UPDATE emp SET salary = salary * 1.1 WHERE dept = 'eng'"],
    ["UPDATE emp SET age = age + 1, dept = 'x' WHERE age IS NULL"],
    ["UPDATE emp SET salary = 1"],
    ["UPDATE emp SET age = '42' WHERE id = 1", "UPDATE emp SET salary = 5 WHERE id = 2"],
    ["UPDATE emp SET name = id WHERE id < 3"],
    ["UPDATE emp SET boss = id, id = boss"],
    ["UPDATE emp SET salary = NULL WHERE salary < 70000"],
    ["DELETE FROM emp WHERE dept = 'eng'"],
    ["DELETE FROM emp WHERE salary IS NULL OR age < 30"],
    ["DELETE FROM emp WHERE NULL"],
    ["DELETE FROM emp"],
    ["INSERT INTO emp (id, name) VALUES (11, 'Zed'), (12, 'Yan')"],
    ["INSERT INTO emp (name, id, age) VALUES ('Q', 13, 22.0)"],
    ["INSERT INTO emp VALUES (14, 'R', 'eng', 1, 30, NULL)"],
    ["INSERT INTO emp VALUES (15, 'S', 'eng', '99.5', '31', NULL)"],
    ["INSERT INTO emp VALUES (16, 99, 'eng', 2 + 3, 10 / 4, -1)"],
    ["INSERT INTO nums VALUES (1, 2, 3, 4.5)", "INSERT INTO nums (s) VALUES (1e20)"],
    ["INSERT INTO nums (a, x) VALUES (2.0, 7)", "INSERT INTO nums (a, x) VALUES ('0x10', '1e2')"],
]


@pytest.mark.parametrize("statements", MUTATIONS)
def test_mutations_match_sqlite(db, lite, statements):
    for stmt in statements:
        assert db.execute(stmt) == []
        lite.execute(stmt)
    for table in ("emp", "nums"):
        assert_same(db, lite, f"SELECT * FROM {table}", ordered=False)
    assert_same(db, lite, "SELECT typeof(a), typeof(x), typeof(s) FROM nums", ordered=False)
    assert_same(
        db, lite, "SELECT typeof(age), typeof(salary), typeof(name) FROM emp", ordered=False
    )


BARE_COLUMN_QUERIES = [
    "SELECT dept, name FROM emp GROUP BY dept",
    "SELECT dept, name, COUNT(*) FROM emp GROUP BY dept",
    "SELECT COUNT(*), name FROM emp",
    "SELECT dept, name, MIN(age) FROM emp GROUP BY dept",
    "SELECT dept, name, MAX(salary), COUNT(*) FROM emp GROUP BY dept",
    "SELECT age / 10 AS decade, name FROM emp GROUP BY decade",
    "SELECT MIN(1, 1.0), MIN(1.0, 1), MAX(1, 1.0), MAX(1.0, 1)",
]


@pytest.mark.parametrize("sql", BARE_COLUMN_QUERIES)
def test_bare_columns_match_sqlite(db, lite, sql):
    assert_same(db, lite, sql)
