"""SELECT queries over a small company dataset, compared against sqlite3."""

import pytest

QUERIES = [
    # projection, aliases, star
    "SELECT * FROM emp",
    "SELECT id, name FROM emp",
    "SELECT e.* FROM emp e",
    "SELECT emp.name, emp.salary * 2 AS double FROM emp",
    "SELECT name AS n, salary s FROM emp",
    "SELECT EMP.NAME, Emp.Id FROM EMP",
    "SELECT *, id FROM dept",
    "SELECT 1, 'x' FROM dept",
    # where
    "SELECT name FROM emp WHERE salary > 80000",
    "SELECT name FROM emp WHERE salary IS NULL",
    "SELECT name FROM emp WHERE dept_id IS NOT NULL AND salary < 100000",
    "SELECT name FROM emp WHERE dept_id IN (1, 3)",
    "SELECT name FROM emp WHERE dept_id NOT IN (1, 3)",
    "SELECT name FROM emp WHERE dept_id NOT IN (1, NULL)",
    "SELECT name FROM emp WHERE salary BETWEEN 70000 AND 100000",
    "SELECT name FROM emp WHERE salary NOT BETWEEN 70000 AND 100000",
    "SELECT name FROM emp WHERE name LIKE '%a%'",
    "SELECT name FROM emp WHERE name NOT LIKE '_a%'",
    "SELECT name FROM emp WHERE note LIKE 'remote'",
    "SELECT name FROM emp WHERE note = 42",
    "SELECT name FROM emp WHERE note > 5",
    "SELECT name FROM emp WHERE note",
    "SELECT name FROM emp WHERE NOT note",
    "SELECT name FROM emp WHERE manager_id = 1 OR dept_id = 3",
    "SELECT name FROM emp WHERE NOT (dept_id = 1)",
    "SELECT name FROM emp WHERE salary / 1000 > 99",
    "SELECT name FROM emp WHERE id % 2 = 0",
    "SELECT name FROM emp WHERE name || note = 'Aliceremote' OR name || note = 'Alicelead'",
    "SELECT name FROM emp WHERE 1",
    "SELECT name FROM emp WHERE 0",
    "SELECT name FROM emp WHERE NULL",
    "SELECT id * 2 AS x FROM emp WHERE x > 6",
    # order by
    "SELECT name, salary FROM emp ORDER BY salary, name",
    "SELECT name, salary FROM emp ORDER BY salary DESC, name ASC",
    "SELECT name FROM emp ORDER BY name",
    "SELECT name FROM emp ORDER BY lower(name) DESC",
    "SELECT name, dept_id FROM emp ORDER BY dept_id DESC, id",
    "SELECT name, note FROM emp ORDER BY note, id",
    "SELECT name, note FROM emp ORDER BY note DESC, id DESC",
    "SELECT name AS who FROM emp ORDER BY who DESC",
    "SELECT id, -id AS id FROM emp ORDER BY id",
    "SELECT name, salary FROM emp ORDER BY 2 DESC, 1",
    "SELECT name, salary * 2 AS s2 FROM emp ORDER BY s2 + 0, name",
    "SELECT id FROM emp ORDER BY salary IS NULL, salary",
    "SELECT id FROM emp ORDER BY dept_id * 10 + id DESC",
    "SELECT id, name FROM emp ORDER BY id % 3, id DESC",
    # limit / offset
    "SELECT id FROM emp ORDER BY id LIMIT 3",
    "SELECT id FROM emp ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT id FROM emp ORDER BY id LIMIT -1 OFFSET 5",
    "SELECT id FROM emp ORDER BY id LIMIT 0",
    "SELECT id FROM emp ORDER BY id LIMIT 100 OFFSET 7",
    "SELECT id FROM emp ORDER BY id LIMIT 2, 3",
    "SELECT id FROM emp ORDER BY id LIMIT 1 + 1",
    "SELECT id FROM emp ORDER BY id LIMIT '2'",
    "SELECT id FROM emp ORDER BY id LIMIT 2.0 OFFSET -3",
    # distinct
    "SELECT DISTINCT dept_id FROM emp",
    "SELECT DISTINCT dept_id, manager_id FROM emp",
    "SELECT DISTINCT salary FROM emp ORDER BY salary DESC",
    "SELECT DISTINCT note IS NULL FROM emp",
    "SELECT DISTINCT title FROM proj ORDER BY title LIMIT 3",
    "SELECT ALL dept_id FROM emp",
    # aggregates without group by
    "SELECT COUNT(*) FROM emp",
    "SELECT COUNT(salary), COUNT(note), COUNT(dept_id) FROM emp",
    "SELECT SUM(salary), AVG(salary), MIN(salary), MAX(salary) FROM emp",
    "SELECT SUM(id), AVG(id), MIN(id), MAX(id) FROM emp",
    "SELECT SUM(hours), AVG(hours) FROM proj",
    "SELECT MIN(note), MAX(note) FROM emp",
    "SELECT MIN(name), MAX(name) FROM emp",
    "SELECT COUNT(DISTINCT dept_id), COUNT(DISTINCT title) FROM emp, proj",
    "SELECT COUNT(DISTINCT salary) FROM emp",
    "SELECT SUM(DISTINCT salary), AVG(DISTINCT dept_id) FROM emp",
    "SELECT COUNT(*), SUM(salary), AVG(salary), MIN(salary), MAX(salary) FROM emp WHERE 0",
    "SELECT COUNT(note), SUM(note), AVG(note), TOTAL(note) FROM emp",
    "SELECT SUM(salary) / COUNT(salary) = AVG(salary) FROM emp",
    "SELECT COUNT(*) + 1, MAX(id) - MIN(id) FROM emp",
    "SELECT COUNT(*) FROM emp WHERE salary > 1000000",
    "SELECT SUM(NULL), AVG(NULL), MIN(NULL), COUNT(NULL) FROM emp",
    "SELECT COUNT(*)",
    "SELECT MAX(salary) FROM emp HAVING MAX(salary) > 10",
    "SELECT COUNT(*) FROM emp HAVING COUNT(*) > 100",
    # group by / having
    "SELECT dept_id, COUNT(*) FROM emp GROUP BY dept_id",
    "SELECT dept_id, COUNT(*), SUM(salary), AVG(salary) FROM emp GROUP BY dept_id",
    "SELECT dept_id, MIN(name), MAX(name) FROM emp GROUP BY dept_id ORDER BY dept_id",
    "SELECT dept_id, COUNT(*) AS c FROM emp GROUP BY dept_id HAVING c > 1",
    "SELECT dept_id, COUNT(*) FROM emp GROUP BY dept_id HAVING COUNT(*) >= 2 ORDER BY dept_id",
    "SELECT dept_id FROM emp GROUP BY dept_id HAVING SUM(salary) > 100000",
    "SELECT dept_id FROM emp GROUP BY dept_id HAVING MAX(salary) IS NULL",
    "SELECT dept_id, COUNT(*) FROM emp GROUP BY dept_id ORDER BY COUNT(*) DESC, dept_id",
    "SELECT dept_id, COUNT(*) FROM emp GROUP BY 1 ORDER BY 2, 1",
    "SELECT dept_id % 2 AS parity, COUNT(*) FROM emp GROUP BY parity",
    "SELECT dept_id, manager_id, COUNT(*) FROM emp GROUP BY dept_id, manager_id",
    "SELECT note IS NULL, COUNT(*) FROM emp GROUP BY note IS NULL",
    "SELECT COUNT(*) FROM emp GROUP BY dept_id",
    "SELECT dept_id, SUM(salary) / COUNT(*) FROM emp GROUP BY dept_id",
    "SELECT dept_id, COUNT(DISTINCT manager_id) FROM emp GROUP BY dept_id",
    "SELECT title, SUM(hours), COUNT(hours) FROM proj GROUP BY title",
    "SELECT dept_id, COUNT(*) FROM emp WHERE salary > 60000 GROUP BY dept_id",
    "SELECT dept_id, COUNT(*) FROM emp WHERE 0 GROUP BY dept_id",
    "SELECT DISTINCT COUNT(*) FROM emp GROUP BY dept_id",
    "SELECT dept_id, COUNT(*) FROM emp GROUP BY dept_id ORDER BY 2 DESC, 1 LIMIT 2",
    (
        "SELECT dept_id, MAX(salary) - MIN(salary) AS spread FROM emp GROUP BY dept_id "
        "ORDER BY spread DESC, dept_id"
    ),
    # joins
    "SELECT e.name, d.name FROM emp e JOIN dept d ON e.dept_id = d.id",
    "SELECT e.name, d.name FROM emp e INNER JOIN dept d ON e.dept_id = d.id WHERE d.id = 1",
    "SELECT * FROM emp JOIN dept ON emp.dept_id = dept.id",
    "SELECT e.name, d.name FROM emp AS e LEFT JOIN dept AS d ON e.dept_id = d.id",
    "SELECT e.name, d.name FROM emp e LEFT OUTER JOIN dept d ON e.dept_id = d.id",
    "SELECT * FROM emp e LEFT JOIN dept d ON e.dept_id = d.id",
    "SELECT d.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id WHERE e.id IS NULL",
    "SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id AND e.salary > 100000",
    (
        "SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id "
        "WHERE e.salary > 100000"
    ),
    "SELECT d.name, COUNT(e.id) FROM dept d LEFT JOIN emp e ON e.dept_id = d.id GROUP BY d.name",
    "SELECT d.name, COUNT(*) FROM dept d LEFT JOIN emp e ON e.dept_id = d.id GROUP BY d.id",
    "SELECT e.name, m.name FROM emp e LEFT JOIN emp m ON e.manager_id = m.id",
    "SELECT e.name, m.name FROM emp e JOIN emp m ON e.manager_id = m.id ORDER BY e.id",
    (
        "SELECT e.name, d.name, p.title FROM emp e JOIN dept d ON e.dept_id = d.id "
        "JOIN proj p ON p.emp_id = e.id"
    ),
    (
        "SELECT e.name, d.name, p.title FROM emp e LEFT JOIN dept d ON e.dept_id = d.id "
        "LEFT JOIN proj p ON p.emp_id = e.id"
    ),
    (
        "SELECT p.title, e.name, d.name FROM proj p LEFT JOIN emp e ON p.emp_id = e.id "
        "LEFT JOIN dept d ON d.id = e.dept_id ORDER BY p.id"
    ),
    (
        "SELECT d.name, SUM(p.hours) FROM dept d JOIN emp e ON e.dept_id = d.id "
        "JOIN proj p ON p.emp_id = e.id GROUP BY d.name ORDER BY d.name"
    ),
    (
        "SELECT d.name, SUM(p.hours) AS h FROM dept d LEFT JOIN emp e ON e.dept_id = d.id "
        "LEFT JOIN proj p ON p.emp_id = e.id GROUP BY d.name HAVING h IS NULL OR h > 100"
    ),
    "SELECT e.name, d.name FROM emp e, dept d WHERE e.dept_id = d.id",
    "SELECT COUNT(*) FROM emp CROSS JOIN dept",
    "SELECT e.id, d.id FROM emp e JOIN dept d ON 1 WHERE e.id < 3 AND d.id < 3",
    "SELECT e.name FROM emp e JOIN dept d ON e.dept_id = d.id AND d.name LIKE 'e%'",
    "SELECT salary, budget FROM emp JOIN dept ON dept_id = dept.id",
    "SELECT e.*, d.name FROM emp e JOIN dept d ON e.dept_id = d.id",
    "SELECT d.*, e.id FROM dept d LEFT JOIN emp e ON e.dept_id = d.id",
    "SELECT DISTINCT d.name FROM dept d JOIN emp e ON e.dept_id = d.id",
    "SELECT e.name FROM emp e LEFT JOIN proj p ON p.emp_id = e.id WHERE p.id IS NULL",
    "SELECT a.id, b.id FROM dept a JOIN dept b ON a.id < b.id ORDER BY a.id, b.id",
    # expressions over columns
    "SELECT id, salary + id, salary / 3, id / 3, id % 3, -salary FROM emp",
    "SELECT name || ' (' || dept_id || ')' FROM emp",
    "SELECT name, note + 1, note || 1 FROM emp",
    "SELECT id, id IN (1, 3, NULL), dept_id BETWEEN 1 AND 2 FROM emp",
    "SELECT id, coalesce(note, 'none'), typeof(salary) FROM emp",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_select(company, sql):
    company.query(sql)


def test_select_without_order_uses_multiset_comparison(company):
    rows = company.query("SELECT dept_id FROM emp")
    assert len(rows) == 8


def test_null_ordering_asc_desc(pair):
    pair.run(
        "CREATE TABLE t (x)",
        "INSERT INTO t VALUES (3), (NULL), ('b'), (1.5), ('A'), (NULL), (-2), ('a'), (2)",
    )
    pair.query("SELECT x FROM t ORDER BY x")
    pair.query("SELECT x FROM t ORDER BY x DESC")
    pair.query("SELECT x FROM t ORDER BY x ASC LIMIT 4")
    pair.query("SELECT MIN(x), MAX(x), COUNT(x), COUNT(*) FROM t")


def test_order_by_multiple_keys_is_stable(pair):
    pair.run(
        "CREATE TABLE t (a INTEGER, b TEXT, c REAL)",
        "INSERT INTO t VALUES (1, 'x', 1.0), (2, 'x', 0.5), (1, 'y', NULL), (2, NULL, 3.0), "
        "(1, 'x', 2.0), (NULL, 'z', 1.0)",
    )
    pair.query("SELECT a, b, c FROM t ORDER BY a, b DESC, c")
    pair.query("SELECT a, b, c FROM t ORDER BY b, a DESC, c DESC")


def test_group_by_nulls_and_numeric_equality(pair):
    pair.run(
        "CREATE TABLE t (k, v INTEGER)",
        "INSERT INTO t VALUES (1, 1), (1.0, 2), ('1', 3), (NULL, 4), (NULL, 5), (2, 6)",
    )
    pair.query("SELECT COUNT(*), SUM(v) FROM t GROUP BY k")
    pair.query("SELECT COUNT(DISTINCT k) FROM t")
    pair.query("SELECT DISTINCT typeof(k) FROM t")


def test_distinct_treats_nulls_equal(pair):
    pair.run(
        "CREATE TABLE t (a INTEGER, b TEXT)",
        "INSERT INTO t VALUES (NULL, NULL), (NULL, NULL), (1, NULL), (1, 'x'), (1, 'x')",
    )
    pair.query("SELECT DISTINCT a, b FROM t")


def test_sum_types(pair):
    pair.run(
        "CREATE TABLE t (g INTEGER, x)",
        "INSERT INTO t VALUES (1, 1), (1, 2), (2, 1), (2, 2.5), (3, NULL), (4, '3'), (4, 4), "
        "(5, 'abc'), (6, 0.1), (6, 0.2), (6, 0.3), (7, '1x'), (8, 1e308), (8, 1e308)",
    )
    pair.query("SELECT g, SUM(x), AVG(x), TOTAL(x), MIN(x), MAX(x), COUNT(x) FROM t GROUP BY g")


def test_empty_table_aggregates(pair):
    pair.run("CREATE TABLE t (a INTEGER, b TEXT)")
    pair.query("SELECT COUNT(*), COUNT(a), SUM(a), AVG(a), MIN(b), MAX(b) FROM t")
    pair.query("SELECT a, COUNT(*) FROM t GROUP BY a")
    pair.query("SELECT * FROM t")
    pair.query("SELECT a FROM t ORDER BY a")


def test_select_without_from(pair):
    pair.query("SELECT 1 + 1, 'a' || 'b' WHERE 1")
    pair.query("SELECT 1 WHERE 0")


def test_left_join_with_empty_right_table(pair):
    pair.run(
        "CREATE TABLE a (id INTEGER)",
        "CREATE TABLE b (id INTEGER, v TEXT)",
        "INSERT INTO a VALUES (1), (2)",
    )
    pair.query("SELECT * FROM a LEFT JOIN b ON a.id = b.id")
    pair.query("SELECT a.id, COUNT(b.id) FROM a LEFT JOIN b ON a.id = b.id GROUP BY a.id")
    pair.query("SELECT * FROM a JOIN b ON a.id = b.id")


@pytest.mark.parametrize(
    "rows",
    [
        "(1, 4), (2, 7.5)",
        "(1, 7.5), (2, 4)",
        "(1, 7.5), (2, 4), (3, 1.5)",
        "(1, 4), (2, 7.5), (3, 10)",
    ],
)
def test_group_key_value_comes_from_first_row_of_group(pair, rows):
    # 4 % 3 = 1 and 7.5 % 3 = 1.0 fall in the same group; SQLite reports the key value
    # of the group's first row for GROUP BY terms, and bare columns from the last row.
    pair.run("CREATE TABLE t (id INTEGER, a)", f"INSERT INTO t VALUES {rows}")
    pair.query("SELECT a % 3, COUNT(*), MAX(id) FROM t GROUP BY a % 3")
    pair.query("SELECT a % 3 AS g, COUNT(*) FROM t GROUP BY g")
    pair.query("SELECT a % 3, COUNT(*) FROM t GROUP BY 1 HAVING (a % 3) > 0 ORDER BY 1")
    pair.query("SELECT DISTINCT a % 3 FROM t")
