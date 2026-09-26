"""SELECT features compared against sqlite3."""

import pytest

SAMPLE_QUERIES = [
    # projection / star
    "SELECT * FROM emp",
    "SELECT emp.* FROM emp",
    "SELECT e.* FROM emp e",
    "SELECT e.*, d.dname FROM emp AS e JOIN dept AS d ON e.dept = d.id",
    "SELECT d.*, e.* FROM emp e JOIN dept d ON e.dept = d.id",
    "SELECT id, name AS n, salary * 2 AS double_pay FROM emp",
    "SELECT id, name n, salary pay FROM emp",
    "SELECT ID, NaMe FROM EMP",
    "select id from emp where NAME = 'Alice'",
    "SELECT emp.id, EMP.name FROM emp",
    "SELECT 1, 'x', NULL FROM emp",
    "SELECT id + dept, name || '!' FROM emp",
    # WHERE
    "SELECT id FROM emp WHERE salary > 4000",
    "SELECT id FROM emp WHERE salary >= 4000 AND dept = 10",
    "SELECT id FROM emp WHERE dept = 10 OR salary IS NULL",
    "SELECT id FROM emp WHERE NOT dept = 10",
    "SELECT id FROM emp WHERE dept IS NULL",
    "SELECT id FROM emp WHERE dept IS NOT NULL",
    "SELECT id FROM emp WHERE dept IN (10, 30)",
    "SELECT id FROM emp WHERE dept NOT IN (10, 30)",
    "SELECT id FROM emp WHERE dept NOT IN (10, NULL)",
    "SELECT id FROM emp WHERE salary BETWEEN 4000 AND 5000",
    "SELECT id FROM emp WHERE salary NOT BETWEEN 4000 AND 5000",
    "SELECT id FROM emp WHERE name LIKE 'a%'",
    "SELECT id FROM emp WHERE name NOT LIKE '%e'",
    "SELECT id FROM emp WHERE name LIKE '_o_'",
    "SELECT id FROM emp WHERE boss",
    "SELECT id FROM emp WHERE name",
    "SELECT id FROM emp WHERE dept = '10'",
    "SELECT id FROM emp WHERE name = 1",
    "SELECT id FROM emp WHERE salary = '4000'",
    "SELECT id FROM emp WHERE salary * 2 > 9000 AND name IS NOT NULL",
    "SELECT id FROM emp WHERE 0",
    "SELECT id FROM emp WHERE NULL",
    "SELECT id * 10 AS x FROM emp WHERE x > 30",
    # ORDER BY
    "SELECT id, salary FROM emp ORDER BY salary, id",
    "SELECT id, salary FROM emp ORDER BY salary DESC, id",
    "SELECT id, dept FROM emp ORDER BY dept ASC, id DESC",
    "SELECT id, dept FROM emp ORDER BY dept DESC, id DESC",
    "SELECT id, name FROM emp ORDER BY name",
    "SELECT id, name FROM emp ORDER BY name DESC",
    "SELECT id, salary AS s FROM emp ORDER BY s DESC, id",
    "SELECT id, salary AS s FROM emp ORDER BY -s, id",
    "SELECT id, name FROM emp ORDER BY 2, 1",
    "SELECT id, name FROM emp ORDER BY 2 DESC, 1 DESC",
    "SELECT id FROM emp ORDER BY salary * -1, id",
    "SELECT id FROM emp ORDER BY dept IS NULL, dept, id",
    "SELECT id, name AS dept FROM emp ORDER BY dept, id",
    "SELECT name FROM emp ORDER BY lower(name), name",
    "SELECT id FROM emp ORDER BY boss, id",
    "SELECT id FROM emp ORDER BY CASE WHEN dept = 20 THEN 0 ELSE 1 END, id",
    # LIMIT / OFFSET
    "SELECT id FROM emp ORDER BY id LIMIT 3",
    "SELECT id FROM emp ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT id FROM emp ORDER BY id LIMIT 2, 3",
    "SELECT id FROM emp ORDER BY id LIMIT 0",
    "SELECT id FROM emp ORDER BY id LIMIT -1 OFFSET 5",
    "SELECT id FROM emp ORDER BY id LIMIT 100 OFFSET 100",
    "SELECT id FROM emp ORDER BY id LIMIT 1 + 1",
    "SELECT id FROM emp ORDER BY id DESC LIMIT '2'",
    # DISTINCT
    "SELECT DISTINCT dept FROM emp",
    "SELECT DISTINCT dept FROM emp ORDER BY dept",
    "SELECT DISTINCT dept FROM emp ORDER BY dept DESC",
    "SELECT DISTINCT boss, dept FROM emp",
    "SELECT DISTINCT lower(name) FROM emp",
    "SELECT DISTINCT salary FROM emp ORDER BY salary",
    "SELECT DISTINCT dept, salary > 4000 FROM emp",
    "SELECT ALL dept FROM emp",
    "SELECT DISTINCT dept FROM emp ORDER BY dept LIMIT 2 OFFSET 1",
    # joins
    "SELECT e.name, d.dname FROM emp e JOIN dept d ON e.dept = d.id",
    "SELECT e.name, d.dname FROM emp e INNER JOIN dept d ON e.dept = d.id",
    "SELECT e.name, d.dname FROM emp e LEFT JOIN dept d ON e.dept = d.id",
    "SELECT e.name, d.dname FROM emp e LEFT OUTER JOIN dept d ON e.dept = d.id",
    "SELECT d.dname, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.id",
    "SELECT d.dname, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.id AND e.salary > 4500",
    "SELECT d.dname, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.id WHERE e.id IS NULL",
    "SELECT e.name, b.name FROM emp e LEFT JOIN emp b ON e.boss = b.id",
    "SELECT e.name, b.name, bb.name FROM emp e LEFT JOIN emp b ON e.boss = b.id"
    " LEFT JOIN emp bb ON b.boss = bb.id",
    "SELECT e.name, d.dname, p.title FROM emp e LEFT JOIN dept d ON e.dept = d.id"
    " LEFT JOIN proj p ON p.emp_id = e.id",
    "SELECT e.name, d.dname, p.title FROM emp e JOIN dept d ON e.dept = d.id"
    " LEFT JOIN proj p ON p.emp_id = e.id",
    "SELECT e.name, p.title, d.dname FROM emp e LEFT JOIN proj p ON p.emp_id = e.id"
    " JOIN dept d ON d.id = e.dept",
    "SELECT p.title, e.name, d.dname FROM proj p LEFT JOIN emp e ON p.emp_id = e.id"
    " LEFT JOIN dept d ON e.dept = d.id",
    "SELECT dname, name FROM emp JOIN dept ON dept = dept.id",
    "SELECT emp.name, dept.dname FROM emp, dept WHERE emp.dept = dept.id",
    "SELECT e.id, d.id FROM emp e CROSS JOIN dept d",
    "SELECT e.id, d.id FROM emp e JOIN dept d",
    "SELECT e.id, d.id FROM emp e LEFT JOIN dept d ON 0",
    "SELECT e.id, d.id FROM emp e LEFT JOIN dept d ON NULL",
    "SELECT e.id, d.dname FROM emp e LEFT JOIN dept d ON e.dept = d.id ORDER BY d.dname, e.id",
    "SELECT a.id, b.id FROM emp a JOIN emp b ON a.dept = b.dept AND a.id < b.id",
    "SELECT e.id, d.budget FROM emp e LEFT JOIN dept d ON e.dept = d.id"
    " WHERE d.budget IS NULL OR d.budget > 60000",
    # aggregates
    "SELECT COUNT(*) FROM emp",
    "SELECT COUNT(*), COUNT(dept), COUNT(salary), COUNT(name) FROM emp",
    "SELECT COUNT(DISTINCT dept), COUNT(DISTINCT boss), COUNT(DISTINCT lower(name)) FROM emp",
    "SELECT SUM(salary), AVG(salary), MIN(salary), MAX(salary) FROM emp",
    "SELECT SUM(id), AVG(id), MIN(id), MAX(id) FROM emp",
    "SELECT SUM(dept), AVG(dept), SUM(boss) FROM emp",
    "SELECT MIN(name), MAX(name) FROM emp",
    "SELECT SUM(DISTINCT dept), AVG(DISTINCT dept), MIN(DISTINCT dept) FROM emp",
    "SELECT total(salary), total(dept) FROM emp",
    "SELECT COUNT(*), SUM(salary), AVG(salary), MIN(salary), MAX(salary) FROM emp WHERE 0",
    "SELECT COUNT(dept), SUM(dept), total(dept), COUNT(DISTINCT dept) FROM emp WHERE id > 100",
    "SELECT COUNT(*) FROM emp WHERE dept IS NULL",
    "SELECT SUM(salary) + 1, COUNT(*) * 2, MAX(salary) - MIN(salary) FROM emp",
    "SELECT SUM(salary) / COUNT(salary) FROM emp",
    "SELECT MAX(id) FROM emp WHERE salary IS NULL",
    "SELECT COUNT(*) FROM emp e JOIN dept d ON e.dept = d.id",
    "SELECT COUNT(p.pid), COUNT(*) FROM emp e LEFT JOIN proj p ON p.emp_id = e.id",
    "SELECT SUM(hours), AVG(hours), MAX(title) FROM proj",
    "SELECT name, MAX(salary) FROM emp",
    "SELECT name, MIN(salary) FROM emp",
    "SELECT COUNT(*) AS c FROM emp HAVING c > 3",
    "SELECT COUNT(*) FROM emp HAVING COUNT(*) > 100",
    # GROUP BY / HAVING
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept",
    "SELECT dept, COUNT(*), SUM(salary), AVG(salary) FROM emp GROUP BY dept",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept ORDER BY dept",
    "SELECT dept, COUNT(*) AS c FROM emp GROUP BY dept ORDER BY c DESC, dept",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept ORDER BY COUNT(*), dept",
    "SELECT dept, SUM(salary) FROM emp GROUP BY dept ORDER BY SUM(salary) DESC",
    "SELECT dept, SUM(salary) AS total FROM emp GROUP BY dept ORDER BY total",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept HAVING COUNT(*) > 1",
    "SELECT dept, COUNT(*) AS c FROM emp GROUP BY dept HAVING c >= 2 ORDER BY dept",
    "SELECT dept, MAX(salary) FROM emp GROUP BY dept HAVING MAX(salary) > 4500",
    "SELECT dept FROM emp GROUP BY dept HAVING SUM(salary) IS NULL OR dept IS NULL",
    "SELECT dept, AVG(salary) FROM emp GROUP BY dept HAVING AVG(salary) > 4000 ORDER BY 2",
    "SELECT dept, COUNT(*) FROM emp GROUP BY 1 ORDER BY 1",
    "SELECT dept AS d, COUNT(*) FROM emp GROUP BY d ORDER BY d",
    "SELECT dept, boss, COUNT(*) FROM emp GROUP BY dept, boss",
    "SELECT dept % 20, COUNT(*) FROM emp GROUP BY dept % 20",
    "SELECT lower(name), COUNT(*) FROM emp GROUP BY lower(name) ORDER BY 1",
    "SELECT salary > 4000, COUNT(*) FROM emp GROUP BY salary > 4000",
    "SELECT COUNT(*) FROM emp GROUP BY dept",
    "SELECT dept, COUNT(*) FROM emp WHERE salary > 3500 GROUP BY dept",
    "SELECT dept, COUNT(*) FROM emp WHERE 0 GROUP BY dept",
    "SELECT dept, COUNT(DISTINCT boss), MIN(name), MAX(name) FROM emp GROUP BY dept",
    "SELECT d.dname, COUNT(e.id), SUM(e.salary) FROM dept d LEFT JOIN emp e ON e.dept = d.id"
    " GROUP BY d.dname ORDER BY d.dname",
    "SELECT d.dname, COUNT(*) FROM dept d LEFT JOIN emp e ON e.dept = d.id GROUP BY d.id"
    " HAVING COUNT(e.id) = 0",
    "SELECT e.name, COUNT(p.pid), SUM(p.hours) FROM emp e LEFT JOIN proj p ON p.emp_id = e.id"
    " GROUP BY e.id ORDER BY COUNT(p.pid) DESC, e.id",
    "SELECT dept, SUM(salary) * 1.0 / COUNT(*) FROM emp GROUP BY dept",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept ORDER BY dept LIMIT 2",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept ORDER BY dept DESC LIMIT 1 OFFSET 1",
    "SELECT DISTINCT COUNT(*) FROM emp GROUP BY dept",
    "SELECT dept, name, MAX(salary) FROM emp GROUP BY dept",
    "SELECT dept, MIN(id) FROM emp GROUP BY dept ORDER BY MIN(id)",
    "SELECT dept, COUNT(*) FROM emp GROUP BY dept HAVING dept > 10",
    "SELECT MAX(salary) - MIN(salary) AS spread, dept FROM emp GROUP BY dept"
    " ORDER BY spread DESC, dept",
    "SELECT boss, SUM(salary) FROM emp GROUP BY boss HAVING SUM(salary) > 5000 ORDER BY boss",
    "SELECT dept IS NULL, COUNT(*) FROM emp GROUP BY dept IS NULL",
    "SELECT CASE WHEN salary >= 4500 THEN 'high' ELSE 'low' END AS band, COUNT(*)"
    " FROM emp GROUP BY band ORDER BY band",
    # no FROM
    "SELECT 1 + 1",
    "SELECT COUNT(*)",
    "SELECT SUM(NULL), COUNT(NULL), AVG(1), MAX(3)",
]


@pytest.mark.parametrize("sql", SAMPLE_QUERIES)
def test_sample_query(sample, sql):
    sample.query(sql)


def test_group_by_null_and_numeric_equality(pair):
    pair.exec(
        "CREATE TABLE g (k REAL, t TEXT, v INTEGER)",
        "INSERT INTO g VALUES (1, 'a', 1), (1.0, 'A', 2), (NULL, NULL, 3), (NULL, 'a', 4),"
        " (2.5, 'b', 5), (2.5, NULL, NULL)",
    )
    pair.query("SELECT k, COUNT(*), SUM(v) FROM g GROUP BY k")
    pair.query("SELECT t, COUNT(*), SUM(v) FROM g GROUP BY t")
    pair.query("SELECT DISTINCT k FROM g")
    pair.query("SELECT DISTINCT t FROM g")
    pair.query("SELECT DISTINCT k, t FROM g")
    pair.query("SELECT COUNT(DISTINCT k), COUNT(DISTINCT t) FROM g")
    pair.query("SELECT k, t FROM g ORDER BY k DESC, t DESC")
    pair.query("SELECT k, t FROM g ORDER BY k, t")


def test_group_by_mixed_types_in_untyped_column(pair):
    pair.exec(
        "CREATE TABLE m (x, y INTEGER)",
        "INSERT INTO m VALUES (1, 1), (1.0, 2), ('1', 3), (NULL, 4), ('a', 5), (2, 6)",
    )
    pair.query("SELECT x, COUNT(*), SUM(y) FROM m GROUP BY x")
    pair.query("SELECT DISTINCT x FROM m")
    pair.query("SELECT x, y FROM m ORDER BY x, y")
    pair.query("SELECT x, y FROM m ORDER BY x DESC, y")
    pair.query("SELECT MIN(x), MAX(x), SUM(x), COUNT(x), AVG(x) FROM m")
    pair.query("SELECT x FROM m WHERE x = 1")
    pair.query("SELECT x FROM m WHERE x = '1'")
    pair.query("SELECT x FROM m WHERE x > 1")
    pair.query("SELECT x FROM m WHERE x IN (1, 'a')")


def test_sum_types_and_precision(pair):
    pair.exec(
        "CREATE TABLE s (i INTEGER, r REAL, t TEXT)",
        "INSERT INTO s VALUES (1, 0.1, '5'), (2, 0.2, '5.0'), (3, 0.3, 'abc'), (4, NULL, '12x')",
    )
    pair.query("SELECT SUM(i), typeof(SUM(i)), SUM(r), AVG(r), AVG(i), typeof(AVG(i)) FROM s")
    pair.query("SELECT SUM(t), AVG(t), total(t), SUM(i + r) FROM s")
    pair.query("SELECT SUM(i) FROM s WHERE i < 3")
    pair.query("SELECT SUM(r) FROM s WHERE r IS NULL")
    pair.query("SELECT i % 2, SUM(r), AVG(r) FROM s GROUP BY i % 2")
    pair.exec("INSERT INTO s VALUES (9007199254740993, 1e16, NULL)")
    pair.query("SELECT SUM(i), SUM(r), SUM(i) + 0.5, AVG(i) FROM s")


def test_order_by_nulls_and_mixed(pair):
    pair.exec(
        "CREATE TABLE o (id INTEGER, x)",
        "INSERT INTO o VALUES (1, 3), (2, NULL), (3, 'b'), (4, 2.5), (5, 'A'), (6, NULL),"
        " (7, -1), (8, '10'), (9, 10)",
    )
    pair.query("SELECT id, x FROM o ORDER BY x, id")
    pair.query("SELECT id, x FROM o ORDER BY x DESC, id")
    pair.query("SELECT id, x FROM o ORDER BY x DESC, id DESC")
    pair.query("SELECT x FROM o WHERE x IS NOT NULL ORDER BY 1 LIMIT 3")


def test_left_join_chain_with_nulls(pair):
    pair.exec(
        "CREATE TABLE a (id INTEGER, v TEXT)",
        "CREATE TABLE b (id INTEGER, a_id INTEGER, w REAL)",
        "CREATE TABLE c (id INTEGER, b_id INTEGER, z TEXT)",
        "INSERT INTO a VALUES (1, 'x'), (2, 'y'), (3, NULL), (NULL, 'n')",
        "INSERT INTO b VALUES (10, 1, 1.5), (11, 1, NULL), (12, 2, 3), (13, NULL, 4)",
        "INSERT INTO c VALUES (100, 10, 'p'), (101, 12, 'q'), (102, 99, 'r')",
    )
    pair.query(
        "SELECT a.id, b.id, c.id FROM a LEFT JOIN b ON b.a_id = a.id LEFT JOIN c ON c.b_id = b.id"
    )
    pair.query(
        "SELECT a.v, COUNT(b.id), COUNT(c.id), SUM(b.w) FROM a LEFT JOIN b ON b.a_id = a.id"
        " LEFT JOIN c ON c.b_id = b.id GROUP BY a.v ORDER BY a.v"
    )
    pair.query(
        "SELECT a.id, b.id FROM a LEFT JOIN b ON b.a_id = a.id AND b.w > 2 ORDER BY a.id, b.id"
    )
    pair.query("SELECT a.id, b.id FROM a LEFT JOIN b ON b.a_id = a.id WHERE b.w IS NULL")
    pair.query("SELECT * FROM a LEFT JOIN b ON a.id = b.a_id LEFT JOIN c ON b.id = c.b_id")
    pair.query("SELECT b.*, a.v FROM b LEFT JOIN a ON a.id = b.a_id")
    pair.query("SELECT x.id, y.id FROM a x LEFT JOIN a y ON x.id = y.id")


def test_order_by_alias_vs_column_precedence(pair):
    pair.exec(
        "CREATE TABLE p (a INTEGER, b INTEGER)",
        "INSERT INTO p VALUES (1, 30), (2, 20), (3, 10)",
    )
    pair.query("SELECT b AS a FROM p ORDER BY a")
    pair.query("SELECT a, b AS a2 FROM p ORDER BY a2 DESC")
    pair.query("SELECT a, -b AS neg FROM p ORDER BY neg + 0")
    pair.query("SELECT a + b AS s FROM p WHERE s > 25 ORDER BY s")
    pair.query("SELECT a AS b FROM p WHERE b > 15 ORDER BY 1")
    pair.query("SELECT b % 20 AS k, COUNT(*) FROM p GROUP BY k ORDER BY k")


def test_empty_tables(pair):
    pair.exec("CREATE TABLE e (a INTEGER, b TEXT)", "CREATE TABLE f (a INTEGER)")
    pair.query("SELECT * FROM e")
    pair.query("SELECT COUNT(*), SUM(a), AVG(a), MIN(b), MAX(b), COUNT(DISTINCT a) FROM e")
    pair.query("SELECT a, COUNT(*) FROM e GROUP BY a")
    pair.query("SELECT e.a, f.a FROM e LEFT JOIN f ON e.a = f.a")
    pair.query("SELECT f.a, e.a FROM f LEFT JOIN e ON e.a = f.a")
    pair.query("SELECT b, COUNT(*) FROM e")
    pair.query("SELECT COUNT(*) FROM e HAVING COUNT(*) = 0")
    pair.exec("INSERT INTO f VALUES (1), (NULL)")
    pair.query("SELECT f.a, e.a, e.b FROM f LEFT JOIN e ON e.a = f.a")
    pair.query("SELECT COUNT(e.a), COUNT(*) FROM f LEFT JOIN e ON 1")


def test_quoted_identifiers_and_comments(pair):
    pair.exec(
        'CREATE TABLE "my table" ("select" INTEGER, [order] TEXT, `x y` REAL)',
        "INSERT INTO \"my table\" VALUES (1, 'a', 1.5) -- trailing comment",
        "/* leading */ INSERT INTO [my table] (\"select\") VALUES (2);",
    )
    pair.query('SELECT "select", [order], `x y` FROM "my table" ORDER BY "select"')
    pair.query('SELECT t."select" FROM "my table" AS t WHERE t."order" IS NULL')
