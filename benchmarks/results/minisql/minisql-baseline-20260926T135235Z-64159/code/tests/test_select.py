"""SELECT features compared against sqlite3."""

import pytest

SETUP = [
    "CREATE TABLE emp (id INTEGER, name TEXT, dept INTEGER, salary REAL, boss INTEGER)",
    "CREATE TABLE dept (id INTEGER, title TEXT, budget INTEGER)",
    "CREATE TABLE proj (id INTEGER, emp_id INTEGER, label TEXT)",
    "CREATE TABLE empty (x INTEGER, y TEXT)",
    "INSERT INTO emp VALUES (1, 'Alice', 10, 5000.0, NULL), (2, 'bob', 10, 4000.5, 1), "
    "(3, 'Carol', 20, 6000.0, 1), (4, 'dave', NULL, 3000.0, 3), (5, 'Eve', 20, NULL, 3), "
    "(6, 'Frank', 30, 4000.5, NULL), (7, 'alice', 10, 2500.0, 2)",
    "INSERT INTO dept VALUES (10, 'Eng', 100000), (20, 'Sales', 50000), (40, 'Void', NULL)",
    "INSERT INTO proj VALUES (1, 1, 'x'), (2, 1, 'y'), (3, 3, 'z'), (4, 9, 'orphan'), "
    "(5, NULL, 'none')",
]

QUERIES = [
    # projection
    "SELECT * FROM emp",
    "SELECT name, salary FROM emp",
    "SELECT e.* FROM emp e",
    "SELECT emp.name FROM emp",
    "SELECT id * 2 AS double, name AS n FROM emp",
    "SELECT id, id FROM emp",
    "SELECT 1, 'a', NULL FROM emp",
    "SELECT 1 + 1",
    "SELECT name nm FROM emp ORDER BY nm",
    "SELECT * FROM empty",
    # where
    "SELECT name FROM emp WHERE dept = 10",
    "SELECT name FROM emp WHERE dept <> 10",
    "SELECT name FROM emp WHERE salary > 4000 AND dept IS NOT NULL",
    "SELECT name FROM emp WHERE NOT (salary > 4000)",
    "SELECT name FROM emp WHERE salary IS NULL OR dept IS NULL",
    "SELECT name FROM emp WHERE name LIKE 'a%'",
    "SELECT name FROM emp WHERE dept IN (10, 30)",
    "SELECT name FROM emp WHERE dept NOT IN (10, NULL)",
    "SELECT name FROM emp WHERE salary BETWEEN 3000 AND 5000",
    "SELECT name FROM emp WHERE boss",
    "SELECT name FROM emp WHERE 0",
    "SELECT name FROM emp WHERE NULL",
    "SELECT id * 10 AS big FROM emp WHERE big > 30",
    # order by
    "SELECT name FROM emp ORDER BY name",
    "SELECT name FROM emp ORDER BY name DESC",
    "SELECT name, salary FROM emp ORDER BY salary",
    "SELECT name, salary FROM emp ORDER BY salary DESC",
    "SELECT name, dept FROM emp ORDER BY dept ASC, name DESC",
    "SELECT name, dept, salary FROM emp ORDER BY dept DESC, salary ASC",
    "SELECT name FROM emp ORDER BY lower(name), id",
    "SELECT name, salary FROM emp ORDER BY 2 DESC, 1",
    "SELECT name AS n, salary AS s FROM emp ORDER BY s, n",
    "SELECT name AS n FROM emp ORDER BY -id",
    "SELECT salary * 2 AS s2 FROM emp ORDER BY s2 + 1 DESC",
    "SELECT name FROM emp ORDER BY salary IS NULL, salary",
    "SELECT name, dept FROM emp ORDER BY dept IS NULL DESC, dept, name",
    "SELECT id AS name, name AS id FROM emp ORDER BY name",
    "SELECT id FROM emp ORDER BY id % 3, id",
    # limit / offset
    "SELECT id FROM emp ORDER BY id LIMIT 3",
    "SELECT id FROM emp ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT id FROM emp ORDER BY id LIMIT 2, 3",
    "SELECT id FROM emp ORDER BY id LIMIT 0",
    "SELECT id FROM emp ORDER BY id LIMIT -1 OFFSET 5",
    "SELECT id FROM emp ORDER BY id LIMIT 100 OFFSET 100",
    "SELECT id FROM emp ORDER BY id LIMIT 1 + 1",
    # distinct
    "SELECT DISTINCT dept FROM emp",
    "SELECT DISTINCT dept FROM emp ORDER BY dept",
    "SELECT DISTINCT dept, salary FROM emp ORDER BY dept DESC, salary",
    "SELECT DISTINCT salary FROM emp ORDER BY salary DESC",
    "SELECT DISTINCT lower(name) FROM emp ORDER BY 1",
    "SELECT DISTINCT dept FROM emp ORDER BY dept LIMIT 2",
    # joins
    "SELECT e.name, d.title FROM emp e JOIN dept d ON e.dept = d.id",
    "SELECT e.name, d.title FROM emp e INNER JOIN dept d ON e.dept = d.id ORDER BY e.name",
    "SELECT e.name, d.title FROM emp AS e LEFT JOIN dept AS d ON e.dept = d.id",
    "SELECT e.name, d.title FROM emp e LEFT OUTER JOIN dept d ON e.dept = d.id WHERE d.id IS NULL",
    "SELECT d.title, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.id ORDER BY d.title, e.name",
    "SELECT * FROM emp e JOIN dept d ON e.dept = d.id",
    "SELECT d.*, e.name FROM emp e JOIN dept d ON e.dept = d.id",
    "SELECT * FROM dept d LEFT JOIN emp e ON e.dept = d.id AND e.salary > 4500",
    "SELECT e.name, b.name FROM emp e LEFT JOIN emp b ON e.boss = b.id",
    "SELECT e.name, b.name, bb.name FROM emp e JOIN emp b ON e.boss = b.id "
    "LEFT JOIN emp bb ON b.boss = bb.id",
    "SELECT e.name, p.label, d.title FROM emp e LEFT JOIN proj p ON p.emp_id = e.id "
    "LEFT JOIN dept d ON d.id = e.dept",
    "SELECT e.name, p.label FROM emp e JOIN proj p ON p.emp_id = e.id JOIN dept d "
    "ON d.id = e.dept WHERE d.budget > 60000",
    "SELECT title, name FROM dept JOIN emp ON dept = dept.id",
    "SELECT emp.name, dept.title FROM emp, dept WHERE emp.dept = dept.id",
    "SELECT count(*) FROM emp CROSS JOIN dept",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON 0",
    "SELECT e.name, x.y FROM emp e LEFT JOIN empty x ON 1",
    "SELECT e.name FROM emp e JOIN empty x ON 1",
    "SELECT d.title, p.label FROM dept d LEFT JOIN emp e ON e.dept = d.id "
    "LEFT JOIN proj p ON p.emp_id = e.id",
    "SELECT d.title, count(e.id), sum(e.salary) FROM dept d LEFT JOIN emp e "
    "ON e.dept = d.id GROUP BY d.title",
    # aggregates without GROUP BY
    "SELECT count(*) FROM emp",
    "SELECT count(*), count(salary), count(dept), count(DISTINCT dept) FROM emp",
    "SELECT sum(salary), avg(salary), min(salary), max(salary) FROM emp",
    "SELECT sum(id), avg(id), min(name), max(name) FROM emp",
    "SELECT count(*), sum(x), avg(x), min(x), max(x), count(x) FROM empty",
    "SELECT count(*), sum(salary) FROM emp WHERE 0",
    "SELECT sum(salary) + 1, count(*) * 2 FROM emp",
    "SELECT max(salary) - min(salary) FROM emp",
    "SELECT sum(DISTINCT salary), avg(DISTINCT salary), count(DISTINCT salary) FROM emp",
    "SELECT sum(dept), sum(boss) FROM emp",
    "SELECT min(dept), max(boss) FROM emp WHERE dept IS NULL",
    "SELECT count(*) FROM emp HAVING count(*) > 3",
    "SELECT count(*) FROM emp HAVING count(*) > 30",
    "SELECT sum(name) FROM emp",
    "SELECT avg(name), total(salary) FROM emp",
    "SELECT sum(1), count(1), avg(2) FROM emp",
    "SELECT min(salary), name FROM emp",
    "SELECT max(salary), name FROM emp",
    # GROUP BY
    "SELECT dept, count(*) FROM emp GROUP BY dept",
    "SELECT dept, count(*) FROM emp GROUP BY dept ORDER BY dept",
    "SELECT dept, sum(salary), avg(salary), min(name), max(name) FROM emp GROUP BY dept",
    "SELECT dept, count(*) AS c FROM emp GROUP BY dept ORDER BY c DESC, dept",
    "SELECT dept, count(*) FROM emp GROUP BY dept HAVING count(*) > 1",
    "SELECT dept, count(*) FROM emp GROUP BY dept HAVING sum(salary) > 5000 ORDER BY dept",
    "SELECT dept FROM emp GROUP BY dept HAVING max(salary) IS NULL OR dept IS NULL",
    "SELECT dept, count(*) FROM emp GROUP BY 1 ORDER BY 2, 1",
    "SELECT dept, salary, count(*) FROM emp GROUP BY dept, salary",
    "SELECT dept % 20 AS m, count(*) FROM emp GROUP BY m",
    "SELECT dept % 20, count(*) FROM emp GROUP BY dept % 20 ORDER BY 1",
    "SELECT dept, count(*) FROM emp WHERE salary > 3000 GROUP BY dept ORDER BY sum(salary)",
    "SELECT dept, max(salary) FROM emp GROUP BY dept ORDER BY max(salary) DESC",
    "SELECT dept FROM emp GROUP BY dept ORDER BY count(*) DESC, dept",
    "SELECT count(*) FROM emp GROUP BY dept",
    "SELECT dept, count(DISTINCT salary) FROM emp GROUP BY dept",
    "SELECT DISTINCT count(*) FROM emp GROUP BY dept",
    "SELECT x, count(*) FROM empty GROUP BY x",
    "SELECT dept, sum(salary) / count(*) FROM emp GROUP BY dept",
    "SELECT dept, count(*) FROM emp GROUP BY dept HAVING dept > 10",
    "SELECT lower(name) AS ln, count(*) FROM emp GROUP BY ln ORDER BY ln",
    "SELECT dept, sum(salary) AS total FROM emp GROUP BY dept HAVING total > 5000",
    "SELECT dept, count(*) FROM emp GROUP BY dept ORDER BY dept LIMIT 2 OFFSET 1",
    "SELECT d.title, count(*) FROM emp e JOIN dept d ON e.dept = d.id GROUP BY d.title "
    "HAVING count(*) >= 2",
    "SELECT boss, count(*), group_concat(name) FROM emp WHERE boss IS NOT NULL "
    "GROUP BY boss ORDER BY boss",
    "SELECT dept, max(salary), name FROM emp GROUP BY dept ORDER BY dept",
    "SELECT dept, min(salary), name FROM emp GROUP BY dept ORDER BY dept",
]


@pytest.fixture
def spair(pair):
    pair.run(*SETUP)
    return pair


@pytest.mark.parametrize("sql", QUERIES)
def test_query(spair, sql):
    spair.check(sql)


def test_null_ordering(spair):
    rows = spair.check("SELECT dept FROM emp ORDER BY dept")
    assert rows[0] == (("NoneType", None),)
    rows = spair.check("SELECT dept FROM emp ORDER BY dept DESC")
    assert rows[-1] == (("NoneType", None),)


def test_mixed_type_ordering(pair):
    pair.run("CREATE TABLE m (v TEXT)", "CREATE TABLE n (v)")
    pair.run("INSERT INTO n VALUES (1), ('a'), (NULL), (2.5), ('B'), (-3), ('')")
    pair.check("SELECT v FROM n ORDER BY v")
    pair.check("SELECT v FROM n ORDER BY v DESC")
    pair.check("SELECT min(v), max(v), count(v) FROM n")


def test_empty_aggregates(db):
    db.execute("CREATE TABLE t (a INTEGER, b REAL)")
    assert db.execute("SELECT count(*), count(a), sum(a), avg(a), min(a), max(b) FROM t") == [
        (0, 0, None, None, None, None)
    ]
    assert db.execute("SELECT a, count(*) FROM t GROUP BY a") == []


def test_sum_types(db):
    db.execute("CREATE TABLE t (a INTEGER, b REAL)")
    db.execute("INSERT INTO t VALUES (1, 1.0), (2, 2.0)")
    ((s_int, s_real, avg_int),) = db.execute("SELECT sum(a), sum(b), avg(a) FROM t")
    assert (type(s_int), type(s_real), type(avg_int)) == (int, float, float)


def test_left_join_no_match_is_null_padded(db):
    db.execute("CREATE TABLE a (x INTEGER)")
    db.execute("CREATE TABLE b (x INTEGER, y TEXT)")
    db.execute("INSERT INTO a VALUES (1), (2)")
    db.execute("INSERT INTO b VALUES (1, 'one')")
    assert db.execute("SELECT a.x, b.x, b.y FROM a LEFT JOIN b ON a.x = b.x ORDER BY a.x") == [
        (1, 1, "one"),
        (2, None, None),
    ]


def test_order_by_out_of_range(db):
    from minisql import SQLError

    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("SELECT a FROM t ORDER BY 2")


def test_insert_select_and_integer_overflow(pair):
    pair.run("CREATE TABLE a (x INTEGER)", "CREATE TABLE b (x INTEGER)")
    pair.run("INSERT INTO a VALUES (9223372036854775807), (1)")
    pair.run("INSERT INTO b SELECT x FROM a WHERE x = 1")
    pair.check("SELECT * FROM b")
    pair.check("SELECT x + 1, x * 2, -x FROM a")
    from minisql import SQLError

    with pytest.raises(SQLError):
        pair.db.execute("SELECT sum(x) FROM a")


def test_bare_columns_in_aggregate_queries(pair):
    pair.run(
        "CREATE TABLE t (g INTEGER, a INTEGER, v INTEGER)",
        "INSERT INTO t VALUES (1, 10, 5), (2, 20, 1), (1, 11, 7), (2, 21, 9), (1, 12, 6), "
        "(3, 30, NULL)",
    )
    for sql in [
        "SELECT a, count(*) FROM t",
        "SELECT g, a, count(*) FROM t GROUP BY g",
        "SELECT g, a, max(v) FROM t GROUP BY g",
        "SELECT g, a, min(v) FROM t GROUP BY g",
        "SELECT a, max(v) FROM t",
        "SELECT a, min(v), max(v) FROM t",
        "SELECT a FROM t GROUP BY g HAVING max(v) > 0",
    ]:
        pair.check(sql)


def test_aggregate_in_order_by_of_plain_query_raises(db):
    from minisql import SQLError

    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("SELECT a FROM t ORDER BY count(*)")
    assert db.execute("SELECT count(*) FROM t ORDER BY count(*)") == [(0,)]
