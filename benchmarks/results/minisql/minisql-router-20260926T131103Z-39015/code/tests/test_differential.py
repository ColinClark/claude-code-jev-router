"""Differential tests: every query must return exactly what sqlite3 returns."""

from __future__ import annotations

import pytest

from tests.conftest import Dual

SETUP = [
    "CREATE TABLE emp (id INTEGER, name TEXT, dept TEXT, salary REAL, age INTEGER, mgr INTEGER)",
    "INSERT INTO emp VALUES (1, 'Alice', 'eng', 120000, 34, NULL)",
    "INSERT INTO emp VALUES (2, 'bob', 'eng', 95000.5, 28, 1), (3, 'Carol', 'sales', 70000, 45, 1)",
    "INSERT INTO emp VALUES (4, 'dave', 'sales', NULL, 23, 3), (5, 'Eve', NULL, 50000, NULL, 3)",
    "INSERT INTO emp VALUES (6, 'frank', 'ops', 70000, 51, 1), (7, 'Grace', 'eng', 130000, 39, 1)",
    "INSERT INTO emp (id, name) VALUES (8, 'Heidi')",
    "INSERT INTO emp VALUES (9, 'ivan', 'ops', 64000.25, 28, 6),"
    " (10, 'Judy', 'sales', 70000, 31, 3)",
    "CREATE TABLE dept (code TEXT, title TEXT, budget INTEGER)",
    "INSERT INTO dept VALUES ('eng', 'Engineering', 1000000), ('sales', 'Sales', 250000)",
    "INSERT INTO dept VALUES ('hr', 'Human Resources', NULL), ('ops', 'Operations', 400000)",
    "CREATE TABLE proj (pid INTEGER, emp_id INTEGER, pname TEXT, hours REAL)",
    "INSERT INTO proj VALUES (1, 1, 'apollo', 10.5), (2, 1, 'zeus', 3), (3, 2, 'apollo', 7)",
    "INSERT INTO proj VALUES (4, 7, 'hermes', NULL), (5, 99, 'orphan', 1), (6, 3, 'zeus', 2.25)",
    "CREATE TABLE empty (x INTEGER, y TEXT, z REAL)",
    "CREATE TABLE nums (i INTEGER, r REAL, t TEXT, n)",
    "INSERT INTO nums VALUES (1, 1.5, '1', 1), (-7, -2.5, 'abc', 'abc'), (NULL, NULL, NULL, NULL)",
    "INSERT INTO nums VALUES (0, 0.0, '', 0.0), (2, 2.0, '10', '10'), (7, 7.5, '3.5', 2.5)",
    "INSERT INTO nums VALUES (3, 1e20, 'ABC', NULL), (-1, -0.5, '-1', -1)",
]

QUERIES = [
    # basic projection / filtering
    "SELECT * FROM emp",
    "SELECT id, name FROM emp WHERE dept = 'eng'",
    "SELECT name, salary * 2 AS double_pay FROM emp WHERE salary > 70000",
    "SELECT name FROM emp WHERE salary >= 70000 AND age < 40",
    "SELECT name FROM emp WHERE dept = 'eng' OR age > 50",
    "SELECT name FROM emp WHERE NOT dept = 'eng'",
    "SELECT name FROM emp WHERE dept IS NULL",
    "SELECT name FROM emp WHERE dept IS NOT NULL",
    "SELECT name FROM emp WHERE salary IS NULL OR age IS NULL",
    "SELECT name FROM emp WHERE dept IN ('eng', 'ops')",
    "SELECT name FROM emp WHERE dept NOT IN ('eng', 'ops')",
    "SELECT name FROM emp WHERE dept NOT IN ('eng', NULL)",
    "SELECT name FROM emp WHERE age BETWEEN 28 AND 39",
    "SELECT name FROM emp WHERE age NOT BETWEEN 28 AND 39",
    "SELECT name FROM emp WHERE name LIKE 'a%'",
    "SELECT name FROM emp WHERE name LIKE '%E%'",
    "SELECT name FROM emp WHERE name LIKE '_o%'",
    "SELECT name FROM emp WHERE name NOT LIKE '%a%'",
    "SELECT name, name LIKE 'ALICE', 'x' LIKE NULL, NULL LIKE 'x' FROM emp",
    "select Name, DEPT from EMP where Dept = 'eng'",
    "SELECT e.name FROM emp e WHERE e.age > 30",
    "SELECT e.name FROM emp AS e WHERE e.age > 30;",
    "SELECT id, name n FROM emp WHERE id < 4",
    # ORDER BY
    "SELECT name, salary FROM emp ORDER BY salary",
    "SELECT name, salary FROM emp ORDER BY salary DESC, name",
    "SELECT name, age FROM emp ORDER BY age, name DESC",
    "SELECT name, dept FROM emp ORDER BY dept DESC, id",
    "SELECT name AS n, age AS a FROM emp ORDER BY a DESC, n",
    "SELECT name, age FROM emp ORDER BY 2, 1",
    "SELECT name, salary / 1000 AS k FROM emp ORDER BY k DESC, name",
    "SELECT name FROM emp ORDER BY age * -1, id",
    "SELECT name, age FROM emp ORDER BY -age, id",
    "SELECT name FROM emp ORDER BY lower(name)",
    "SELECT name FROM emp ORDER BY name",
    "SELECT id FROM emp ORDER BY salary IS NULL, salary DESC, id",
    # LIMIT / OFFSET
    "SELECT id FROM emp ORDER BY id LIMIT 3",
    "SELECT id FROM emp ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT id FROM emp ORDER BY id LIMIT 0",
    "SELECT id FROM emp ORDER BY id LIMIT -1 OFFSET 8",
    "SELECT id FROM emp ORDER BY id LIMIT 100 OFFSET 100",
    "SELECT id FROM emp ORDER BY id LIMIT 2, 3",
    # DISTINCT
    "SELECT DISTINCT dept FROM emp",
    "SELECT DISTINCT salary FROM emp ORDER BY salary",
    "SELECT DISTINCT dept, age > 30 FROM emp",
    "SELECT DISTINCT n FROM nums",
    "SELECT DISTINCT 1 FROM emp",
    # aggregates without GROUP BY
    "SELECT COUNT(*) FROM emp",
    "SELECT COUNT(salary), COUNT(dept), COUNT(DISTINCT dept) FROM emp",
    "SELECT SUM(salary), AVG(salary), MIN(salary), MAX(salary) FROM emp",
    "SELECT SUM(age), AVG(age), MIN(name), MAX(name) FROM emp",
    "SELECT COUNT(*), SUM(x), AVG(x), MIN(x), MAX(x), COUNT(x) FROM empty",
    "SELECT COUNT(*) FROM emp WHERE age > 100",
    "SELECT SUM(salary) FROM emp WHERE salary IS NULL",
    "SELECT SUM(DISTINCT salary), AVG(DISTINCT salary), COUNT(DISTINCT salary) FROM emp",
    "SELECT MIN(n), MAX(n), SUM(n), COUNT(n) FROM nums",
    "SELECT MIN(t), MAX(t) FROM nums",
    "SELECT SUM(i), SUM(r), TOTAL(i), AVG(i) FROM nums",
    "SELECT COUNT(*) + 1, MAX(age) - MIN(age) FROM emp",
    "SELECT name, MAX(salary) FROM emp",
    "SELECT name, MIN(age) FROM emp",
    "SELECT group_concat(name) FROM emp WHERE dept = 'eng'",
    # GROUP BY / HAVING
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept",
    "SELECT dept, COUNT(*) AS c, AVG(salary) FROM emp GROUP BY dept ORDER BY c DESC, dept",
    "SELECT dept, SUM(salary) FROM emp GROUP BY dept HAVING SUM(salary) > 100000",
    "SELECT dept, COUNT(*) AS c FROM emp GROUP BY dept HAVING c > 1 ORDER BY dept",
    "SELECT dept, MAX(age) FROM emp GROUP BY dept ORDER BY MAX(age) DESC",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept ORDER BY COUNT(*), dept",
    "SELECT age, COUNT(*) FROM emp GROUP BY age",
    "SELECT salary, COUNT(*) FROM emp GROUP BY salary ORDER BY salary DESC",
    "SELECT dept, age > 30 AS senior, COUNT(*) FROM emp GROUP BY dept, senior",
    "SELECT dept, name, MAX(salary) FROM emp GROUP BY dept",
    "SELECT dept, name, MIN(age) FROM emp GROUP BY dept",
    "SELECT COUNT(*) FROM emp GROUP BY dept HAVING COUNT(*) > 100",
    "SELECT x, COUNT(*) FROM empty GROUP BY x",
    "SELECT dept FROM emp GROUP BY 1 ORDER BY 1",
    "SELECT dept, SUM(age) / COUNT(age) FROM emp GROUP BY dept",
    "SELECT n, COUNT(*) FROM nums GROUP BY n",
    "SELECT dept, COUNT(DISTINCT salary) FROM emp GROUP BY dept",
    "SELECT dept, SUM(salary) AS total FROM emp WHERE age > 25 GROUP BY dept "
    "HAVING total > 50000 ORDER BY total DESC LIMIT 2",
    # joins
    "SELECT e.name, d.title FROM emp e JOIN dept d ON e.dept = d.code",
    "SELECT e.name, d.title FROM emp e INNER JOIN dept d ON e.dept = d.code ORDER BY e.id",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON e.dept = d.code",
    "SELECT e.name, d.title FROM emp e LEFT OUTER JOIN dept d ON e.dept = d.code "
    "WHERE d.code IS NULL",
    "SELECT d.title, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.code ORDER BY d.title, e.id",
    "SELECT e.name, p.pname FROM emp e JOIN proj p ON p.emp_id = e.id",
    "SELECT e.name, p.pname, d.title FROM emp e JOIN proj p ON p.emp_id = e.id "
    "JOIN dept d ON d.code = e.dept",
    "SELECT e.name, p.pname, d.title FROM emp e LEFT JOIN proj p ON p.emp_id = e.id "
    "LEFT JOIN dept d ON d.code = e.dept ORDER BY e.id, p.pid",
    "SELECT e.name, m.name FROM emp e LEFT JOIN emp m ON e.mgr = m.id",
    "SELECT e.name AS worker, m.name AS boss FROM emp e JOIN emp m ON e.mgr = m.id "
    "ORDER BY boss, worker",
    "SELECT d.*, e.name FROM dept d JOIN emp e ON e.dept = d.code",
    "SELECT e.*, p.* FROM emp e JOIN proj p ON e.id = p.emp_id",
    "SELECT * FROM emp e JOIN proj p ON e.id = p.emp_id",
    "SELECT * FROM dept LEFT JOIN emp ON emp.dept = dept.code AND emp.age > 40",
    "SELECT d.title, COUNT(e.id) FROM dept d LEFT JOIN emp e ON e.dept = d.code GROUP BY d.title",
    "SELECT d.title, COUNT(*), SUM(p.hours) FROM dept d JOIN emp e ON e.dept = d.code "
    "LEFT JOIN proj p ON p.emp_id = e.id GROUP BY d.title ORDER BY 2 DESC, 1",
    "SELECT e.name, p.pname FROM emp e, proj p WHERE e.id = p.emp_id",
    "SELECT COUNT(*) FROM emp CROSS JOIN dept",
    "SELECT p.pname, e.name FROM proj p LEFT JOIN emp e ON p.emp_id = e.id WHERE e.name IS NULL",
    "SELECT name, title FROM emp JOIN dept ON dept = code",
    # expressions / arithmetic / types
    "SELECT 5 / 2, 5 / 2.0, -7 / 2, 7 / -2, -7 % 2, 7 % -2, 7.5 % 2, -7.5 % 2",
    "SELECT 1 / 0, 1 % 0, 1.0 / 0, 1 / 0.0, 5 % 0.5, NULL / 0",
    "SELECT 1 = 1, 1 = 2, 1 < 2, 2 <= 1, 'a' < 'b', 'a' = 'A', 1 == 1, 1 <> 2, 1 != 1",
    "SELECT 1 + 2 * 3, (1 + 2) * 3, 10 - 2 - 3, 2 * 3 % 4, -2 * -3",
    "SELECT 'a' || 'b' || 1 || 2.5, 'x' || NULL, NULL || NULL",
    "SELECT 1 + '2', '3' * '4', 'abc' + 1, '12abc' + 0, '1.5' + 1, '1e2' + 0, ' 7 ' + 1",
    "SELECT 1 + 1.0, 2 * 1.5, 3 - 1.0, 4 / 2, 4.0 / 2, 0.1 + 0.2",
    "SELECT NULL + 1, NULL * 0, -NULL, NOT NULL, NULL = NULL, NULL <> 1",
    "SELECT NULL AND 0, NULL AND 1, NULL OR 1, NULL OR 0, 0 AND NULL, 1 OR NULL",
    "SELECT NULL IN (1, 2), 1 IN (1, NULL), 3 IN (1, NULL), 3 NOT IN (1, NULL), 3 NOT IN (1, 2)",
    "SELECT NULL BETWEEN 1 AND 2, 1 BETWEEN NULL AND 2, 5 BETWEEN NULL AND 2, 1 BETWEEN 0 AND NULL",
    "SELECT 2 BETWEEN 1 AND 3, 2 NOT BETWEEN 1 AND 3, 'b' BETWEEN 'a' AND 'c'",
    "SELECT NOT 0, NOT 1, NOT 5, NOT 'abc', NOT '1', - -3, +'abc', -'3'",
    "SELECT 1 IS NULL, NULL IS NULL, NULL IS NOT NULL, 1 IS 1, NULL IS 1, 1 IS NOT 2",
    "SELECT 1 < 'a', 'a' > 99999, NULL < 1, 2 > 1.5, 1 = 1.0",
    "SELECT 'abc' LIKE 'ABC', 'abc' LIKE 'a_c', 'abc' LIKE 'a%', 'abc' LIKE '%d%', 5 LIKE '5'",
    "SELECT 'a%c' LIKE 'a%c', '' LIKE '%', '' LIKE '_', 'aXb' NOT LIKE 'a_b'",
    "SELECT 1 + 2 = 3, 1 < 2 = 1, 1 = 1 AND 2 = 2, NOT 1 = 2, 1 = 2 OR 3 = 3",
    "SELECT 2 + 3 || 4, 'x' || 1 + 2, 10 - 3 || '1', -2 || 3",
    "SELECT 1 < 2 < 3, 3 > 2 > 1, 1 = 2 = 0",
    "SELECT 5 IN (5), 5 IN (4 + 1, 7), 'a' IN ('A', 'a')",
    "SELECT 1 BETWEEN 0 AND 2 AND 0",
    "SELECT 9223372036854775807, -9223372036854775808, 1e3, .5, 1.5e-3",
    "SELECT abs(-5), abs(-2.5), abs(NULL), length('hello'), length(NULL), length(123)",
    "SELECT upper('abc'), lower('ABC'), coalesce(NULL, NULL, 3), ifnull(NULL, 'x'), nullif(1, 1)",
    "SELECT round(2.5), round(-2.5), round(3.14159, 2), round(1), typeof(round(1))",
    "SELECT substr('hello', 2), substr('hello', 2, 3), substr('hello', -3), substr('hello', 0, 2)",
    "SELECT typeof(1), typeof(1.0), typeof('x'), typeof(NULL), typeof(1/2), typeof(1/2.0)",
    "SELECT CASE WHEN 1 > 2 THEN 'a' WHEN 2 > 1 THEN 'b' ELSE 'c' END",
    "SELECT CASE 3 WHEN 1 THEN 'one' WHEN 3 THEN 'three' END, CASE 4 WHEN 1 THEN 'one' END",
    "SELECT CAST('12' AS INTEGER), CAST(3.7 AS INTEGER), CAST(5 AS REAL), CAST(5 AS TEXT)",
    "SELECT max(1, 2, 3), min(1, 'a'), max(NULL, 1), trim('  x  '), replace('aaa', 'a', 'b')",
    # expressions over columns (affinity)
    "SELECT name, salary + age, salary / age, age % 7, age / 7, -age FROM emp",
    "SELECT name || ' (' || dept || ')' FROM emp",
    "SELECT i, r, t, n, i + r, i * t, t + 0, n + 0 FROM nums",
    "SELECT i FROM nums WHERE i = '2'",
    "SELECT i FROM nums WHERE i < '3'",
    "SELECT r FROM nums WHERE r > '1'",
    "SELECT t FROM nums WHERE t = 10",
    "SELECT t FROM nums WHERE t > 5",
    "SELECT n FROM nums WHERE n = '10'",
    "SELECT n FROM nums WHERE n = 10",
    "SELECT i FROM nums WHERE i IN ('1', '2', 7)",
    "SELECT t FROM nums WHERE t IN (1, 10)",
    "SELECT i FROM nums WHERE i BETWEEN '0' AND '5'",
    "SELECT i, t FROM nums WHERE i = t",
    "SELECT i, n FROM nums WHERE i = n",
    "SELECT * FROM nums ORDER BY n",
    "SELECT * FROM nums ORDER BY t DESC",
    "SELECT * FROM nums ORDER BY r DESC, i",
    "SELECT i, i / 2, i % 3, i * 1.0 / 2 FROM nums ORDER BY i",
    "SELECT name FROM emp WHERE age",
    "SELECT name FROM emp WHERE salary > 70000 AND dept",
    "SELECT name FROM emp WHERE name > 'M'",
    # select without FROM
    "SELECT 1 + 1",
    "SELECT 'hello', NULL, 3.5",
    "SELECT COUNT(*)",
    "SELECT 1 AS x ORDER BY x",
]


@pytest.fixture(scope="module")
def db() -> Dual:
    d = Dual()
    d.script(*SETUP)
    return d


@pytest.mark.parametrize("sql", QUERIES)
def test_query_matches_sqlite(db: Dual, sql: str) -> None:
    db.check(sql)


ERRORS = [
    "SELECT * FROM missing",
    "SELECT nosuch FROM emp",
    "SELECT e.nosuch FROM emp e",
    "SELECT x.name FROM emp e",
    "SELECT id FROM emp JOIN emp AS e2 ON 1",
    "SELECT name FROM emp e JOIN emp m ON e.mgr = m.id",
    "SELECT nosuchfn(1)",
    "SELECT COUNT(1, 2) FROM emp",
    "SELECT FROM emp",
    "SELECT * FROM",
    "SELEKT 1",
    "SELECT 1 +",
    "SELECT (1",
    "SELECT 'abc",
    "SELECT * FROM emp WHERE",
    "SELECT * FROM emp ORDER BY 99",
    "SELECT name FROM emp WHERE COUNT(*) > 1",
    "SELECT name FROM emp HAVING age > 1",
    "SELECT SUM(COUNT(*)) FROM emp",
    "SELECT * FROM emp LIMIT 'x'",
    "SELECT *",
    "SELECT 1 2",
    "INSERT INTO emp VALUES (1, 2)",
    "INSERT INTO emp (id, name) VALUES (1)",
    "INSERT INTO emp (id, nope) VALUES (1, 2)",
    "INSERT INTO missing VALUES (1)",
    "UPDATE missing SET a = 1",
    "UPDATE emp SET nope = 1",
    "UPDATE emp SET age = nope",
    "DELETE FROM missing",
    "DELETE FROM emp WHERE nope = 1",
    "CREATE TABLE emp (a INTEGER)",
    "CREATE TABLE",
]


@pytest.mark.parametrize("sql", ERRORS)
def test_errors_match_sqlite(db: Dual, sql: str) -> None:
    db.check_error(sql)


def test_dml_sequence() -> None:
    d = Dual()
    d.script(
        "CREATE TABLE t (id INTEGER, v REAL, s TEXT)",
        "INSERT INTO t VALUES (1, 1, 'a'), (2, 2.5, 'b'), (3, NULL, 'c'), (4, '7', 8)",
        "INSERT INTO t (s, id) VALUES ('only', 5)",
    )
    d.check("SELECT * FROM t ORDER BY id")
    d.run("UPDATE t SET v = v * 2, s = s || '!' WHERE id <= 2")
    d.check("SELECT * FROM t ORDER BY id")
    d.run("UPDATE t SET v = id, id = id + 10")
    d.check("SELECT * FROM t ORDER BY id")
    d.run("UPDATE t SET s = 42 WHERE v > 12")
    d.check("SELECT * FROM t ORDER BY id")
    d.run("DELETE FROM t WHERE v IS NULL OR id = 12")
    d.check("SELECT * FROM t ORDER BY id")
    d.run("DELETE FROM t")
    d.check("SELECT COUNT(*), SUM(v) FROM t")
    d.run("INSERT INTO t VALUES (1, '2.5', 3.0);")
    d.check("SELECT * FROM t")


def test_type_affinity_on_insert() -> None:
    d = Dual()
    d.run("CREATE TABLE a (i INTEGER, r REAL, t TEXT, n NUMERIC, b)")
    values = [
        "1", "1.0", "3.0", "3.5", "'12'", "' 7 '", "'3.0'", "'1e2'", "'abc'", "''", "NULL",
        "-0.0", "1e20", "'1.5x'", "0.1", "1.0/3", "'-5'", "123456789012345678",
    ]
    for v in values:
        d.run(f"INSERT INTO a VALUES ({v}, {v}, {v}, {v}, {v})")
    d.check("SELECT i, typeof(i), r, typeof(r), t, typeof(t), n, typeof(n), b FROM a")
    d.check("SELECT i FROM a WHERE i = 3 ORDER BY i")
    d.check("SELECT t FROM a WHERE t = 1 ORDER BY t")
