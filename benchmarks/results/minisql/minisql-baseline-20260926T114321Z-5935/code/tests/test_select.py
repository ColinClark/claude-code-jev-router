"""SELECT queries over tables, compared against sqlite3."""

import pytest

QUERIES = [
    # projection, star, aliases
    "SELECT * FROM emp",
    "SELECT * FROM dept",
    "SELECT name, salary FROM emp",
    "SELECT e.* FROM emp e",
    "SELECT d.*, e.name FROM emp AS e JOIN dept AS d ON e.dept = d.code",
    "SELECT id * 2 AS double_id, name AS n FROM emp",
    "SELECT id, id + age, salary / 1000, name || '@' || dept FROM emp",
    "SELECT EMP.NAME, Emp.Id FROM EMP",
    "select name from emp where AGE > 30",
    "SELECT emp.name FROM emp WHERE emp.id < 4",
    "SELECT 1, 'x', NULL FROM dept",
    # WHERE
    "SELECT name FROM emp WHERE salary > 70000",
    "SELECT name FROM emp WHERE salary >= 70000 AND dept = 'eng'",
    "SELECT name FROM emp WHERE dept = 'ops' OR age < 30",
    "SELECT name FROM emp WHERE NOT dept = 'eng'",
    "SELECT name FROM emp WHERE dept IS NULL",
    "SELECT name FROM emp WHERE dept IS NOT NULL AND salary IS NULL",
    "SELECT name FROM emp WHERE dept IN ('eng', 'sales')",
    "SELECT name FROM emp WHERE dept NOT IN ('eng', 'sales')",
    "SELECT name FROM emp WHERE dept NOT IN ('eng', NULL)",
    "SELECT name FROM emp WHERE age BETWEEN 28 AND 39",
    "SELECT name FROM emp WHERE age NOT BETWEEN 28 AND 39",
    "SELECT name FROM emp WHERE name LIKE '%a%'",
    "SELECT name FROM emp WHERE name LIKE 'a%'",
    "SELECT name FROM emp WHERE name NOT LIKE '_a%'",
    "SELECT name FROM emp WHERE salary",
    "SELECT name FROM emp WHERE boss",
    "SELECT name FROM emp WHERE age > '30'",
    "SELECT name FROM emp WHERE id = '3'",
    "SELECT name FROM emp WHERE 0",
    "SELECT name FROM emp WHERE NULL",
    # ORDER BY
    "SELECT name, salary FROM emp ORDER BY salary",
    "SELECT name, salary FROM emp ORDER BY salary DESC, name",
    "SELECT name, salary FROM emp ORDER BY salary ASC, name DESC",
    "SELECT name, dept FROM emp ORDER BY dept, name",
    "SELECT name, dept FROM emp ORDER BY dept DESC, name ASC",
    "SELECT name, age FROM emp ORDER BY age DESC, id",
    "SELECT name AS n FROM emp ORDER BY n",
    "SELECT name AS n FROM emp ORDER BY n DESC",
    "SELECT name, salary * 2 AS s2 FROM emp ORDER BY s2 DESC, name",
    "SELECT name FROM emp ORDER BY 1",
    "SELECT name, age FROM emp ORDER BY 2 DESC, 1",
    "SELECT name FROM emp ORDER BY age * -1, id",
    "SELECT name FROM emp ORDER BY lower(name)",
    "SELECT name FROM emp ORDER BY id % 3, id DESC",
    "SELECT id, salary FROM emp ORDER BY salary IS NULL, salary",
    "SELECT name, dept FROM emp ORDER BY dept NULLS LAST, name",
    "SELECT name, dept FROM emp ORDER BY dept DESC NULLS FIRST, name",
    "SELECT id FROM emp ORDER BY salary + age DESC, id",
    "SELECT name AS age, age AS name FROM emp ORDER BY age",
    "SELECT name AS x FROM emp ORDER BY x || 'z'",
    "SELECT id AS salary FROM emp ORDER BY salary, id",
    # LIMIT / OFFSET
    "SELECT name FROM emp ORDER BY id LIMIT 3",
    "SELECT name FROM emp ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT name FROM emp ORDER BY id LIMIT 0",
    "SELECT name FROM emp ORDER BY id LIMIT -1 OFFSET 8",
    "SELECT name FROM emp ORDER BY id LIMIT 100 OFFSET 9",
    "SELECT name FROM emp ORDER BY id LIMIT 2, 3",
    "SELECT name FROM emp ORDER BY id LIMIT 1 + 1",
    "SELECT name FROM emp ORDER BY id LIMIT 3 OFFSET -2",
    # DISTINCT
    "SELECT DISTINCT dept FROM emp",
    "SELECT DISTINCT dept FROM emp ORDER BY dept",
    "SELECT DISTINCT dept, age FROM emp ORDER BY dept, age",
    "SELECT DISTINCT salary FROM emp ORDER BY salary DESC",
    "SELECT DISTINCT age / 10 FROM emp ORDER BY 1",
    "SELECT DISTINCT dept FROM emp ORDER BY dept LIMIT 2",
    # joins
    "SELECT e.name, d.title FROM emp e JOIN dept d ON e.dept = d.code",
    "SELECT e.name, d.title FROM emp e INNER JOIN dept d ON e.dept = d.code ORDER BY e.name",
    "SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON e.dept = d.code",
    "SELECT e.name, d.title FROM emp e LEFT OUTER JOIN dept d ON e.dept = d.code ORDER BY d.title, e.name",
    "SELECT d.title, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.code",
    "SELECT d.code, e.id FROM dept d LEFT JOIN emp e ON e.dept = d.code AND e.age > 40",
    "SELECT d.code, e.id FROM dept d LEFT JOIN emp e ON e.dept = d.code WHERE e.id IS NULL",
    "SELECT e.name, b.name FROM emp e JOIN emp b ON e.boss = b.id",
    "SELECT e.name, b.name AS boss FROM emp e LEFT JOIN emp b ON e.boss = b.id ORDER BY e.id",
    "SELECT e.name, b.name, bb.name FROM emp e LEFT JOIN emp b ON e.boss = b.id "
    "LEFT JOIN emp bb ON b.boss = bb.id",
    "SELECT e.name, d.title, b.name FROM emp e JOIN dept d ON d.code = e.dept "
    "LEFT JOIN emp b ON b.id = e.boss AND b.dept = d.code",
    "SELECT * FROM emp e LEFT JOIN dept d ON e.dept = d.code WHERE d.floor > 1",
    "SELECT * FROM dept d1 JOIN dept d2 ON d1.floor < d2.floor",
    "SELECT * FROM dept d1 LEFT JOIN dept d2 ON d1.floor < d2.floor",
    "SELECT d1.code, d2.code FROM dept d1, dept d2",
    "SELECT d1.code, d2.code FROM dept d1 CROSS JOIN dept d2 WHERE d1.code < d2.code",
    "SELECT e.name FROM emp e JOIN dept d ON 1",
    "SELECT e.id, d.code FROM emp e JOIN dept d",
    "SELECT e.name, title FROM emp e JOIN dept ON dept = code",
    "SELECT * FROM emp e LEFT JOIN dept d ON NULL",
    "SELECT e.id, d.code FROM emp e LEFT JOIN dept d ON e.dept = d.code ORDER BY d.code DESC, e.id",
    # GROUP BY / aggregates
    "SELECT dept, count(*) FROM emp GROUP BY dept",
    "SELECT dept, count(*), count(salary), sum(salary), avg(salary), min(salary), max(salary) "
    "FROM emp GROUP BY dept",
    "SELECT dept, count(DISTINCT age), sum(DISTINCT salary) FROM emp GROUP BY dept",
    "SELECT dept, sum(age), avg(age), total(age) FROM emp GROUP BY dept ORDER BY dept",
    "SELECT count(*), count(dept), count(DISTINCT dept), sum(age), avg(age), min(name), max(name) FROM emp",
    "SELECT count(*), sum(salary), avg(salary), min(salary), max(salary), total(salary) FROM emp WHERE 0",
    "SELECT count(*) FROM emp WHERE 0 GROUP BY dept",
    "SELECT dept, count(*) AS c FROM emp GROUP BY dept HAVING c > 1",
    "SELECT dept, count(*) FROM emp GROUP BY dept HAVING count(*) > 1 ORDER BY count(*) DESC, dept",
    "SELECT dept, avg(salary) FROM emp GROUP BY dept HAVING avg(salary) > 70000",
    "SELECT dept, max(age) - min(age) AS spread FROM emp GROUP BY dept ORDER BY spread DESC, dept",
    "SELECT dept FROM emp GROUP BY dept ORDER BY sum(salary) DESC",
    "SELECT dept, age, count(*) FROM emp GROUP BY dept, age",
    "SELECT age / 10 AS decade, count(*) FROM emp GROUP BY decade ORDER BY decade",
    "SELECT age / 10, count(*) FROM emp GROUP BY age / 10 ORDER BY 1",
    "SELECT dept, count(*) FROM emp GROUP BY 1 ORDER BY 2 DESC, 1",
    "SELECT sum(salary) / count(*) FROM emp",
    "SELECT count(*) * 2 + 1 FROM emp",
    "SELECT dept, max(salary), name FROM emp GROUP BY dept",
    "SELECT dept, min(age), name FROM emp WHERE age IS NOT NULL GROUP BY dept",
    "SELECT max(salary), name FROM emp",
    "SELECT count(*) FROM emp HAVING count(*) > 5",
    "SELECT count(*) FROM emp HAVING count(*) > 50",
    "SELECT d.title, count(e.id), avg(e.salary) FROM dept d LEFT JOIN emp e ON e.dept = d.code "
    "GROUP BY d.title ORDER BY d.title",
    "SELECT d.floor, sum(e.age) FROM dept d JOIN emp e ON e.dept = d.code GROUP BY d.floor",
    "SELECT DISTINCT count(*) FROM emp GROUP BY dept",
    "SELECT dept, count(*) FROM emp GROUP BY dept ORDER BY count(*) DESC, dept LIMIT 2",
    "SELECT min(dept), max(dept) FROM emp",
    "SELECT sum(age > 30), sum(dept = 'eng') FROM emp",
    "SELECT avg(id), sum(id * 1.5), sum(1), count(1), count(NULL), sum(NULL), avg(NULL) FROM emp",
    "SELECT min(NULL), max(NULL), total(NULL) FROM emp",
    "SELECT boss, count(*) FROM emp GROUP BY boss ORDER BY boss",
    "SELECT salary, count(*) FROM emp GROUP BY salary ORDER BY salary DESC",
    "SELECT count(*) FROM emp e JOIN emp f ON e.dept = f.dept",
    "SELECT e.dept, count(*) FROM emp e JOIN emp f ON e.dept = f.dept GROUP BY e.dept ORDER BY e.dept",
    "SELECT upper(dept), count(*) FROM emp GROUP BY upper(dept)",
    "SELECT dept, sum(salary) FROM emp WHERE age > 25 GROUP BY dept HAVING sum(salary) > 100000 "
    "ORDER BY 2",
    "SELECT dept AS d, count(*) FROM emp GROUP BY d HAVING d IS NOT NULL ORDER BY d",
    "SELECT name FROM emp ORDER BY name LIMIT 1",
    # expressions without FROM
    "SELECT 1 + 1, 'a' || 'b'",
    "SELECT count(*)",
    "SELECT count(*) WHERE 0",
    "SELECT 5 AS x ORDER BY x",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_query_matches_sqlite(sample, sql):
    sample.check(sql)


def test_left_join_pads_nulls(sample):
    rows = sample.check("SELECT d.code, e.name FROM dept d LEFT JOIN emp e ON e.dept = d.code ORDER BY 1, 2")
    assert ("hr", None) in rows


def test_null_ordering(pair):
    pair.run(
        "CREATE TABLE n (a INTEGER, b TEXT, c REAL)",
        "INSERT INTO n VALUES (3, 'x', 1.5), (NULL, 'y', NULL), (1, NULL, -2.0), (2, 'a', NULL)",
        "INSERT INTO n VALUES (NULL, NULL, 0.0)",
    )
    asc = pair.check("SELECT a FROM n ORDER BY a")
    assert asc[:2] == [(None,), (None,)]
    desc = pair.check("SELECT a FROM n ORDER BY a DESC")
    assert desc[-2:] == [(None,), (None,)]
    pair.check("SELECT b, a FROM n ORDER BY b DESC, a")
    pair.check("SELECT c, a FROM n ORDER BY c, a DESC")


def test_mixed_type_ordering(pair):
    pair.run(
        "CREATE TABLE m (x)",
        "INSERT INTO m VALUES (1), ('a'), (NULL), (2.5), ('B'), (-3), (''), ('10')",
    )
    pair.check("SELECT x FROM m ORDER BY x")
    pair.check("SELECT x FROM m ORDER BY x DESC")
    pair.check("SELECT min(x), max(x), count(x) FROM m")


def test_bare_columns_follow_sqlite(sample):
    sample.check("SELECT name, max(age) FROM emp")
    sample.check("SELECT name, min(salary) FROM emp")
    sample.check("SELECT dept, name, max(salary) FROM emp GROUP BY dept ORDER BY dept")


def test_sum_uses_compensated_summation(pair):
    pair.run("CREATE TABLE f (x REAL)")
    pair.run(*["INSERT INTO f VALUES (0.1)"] * 10)
    assert pair.check("SELECT sum(x), avg(x), total(x) FROM f") == [(1.0, 0.1, 1.0)]


def test_sum_types(pair):
    pair.run(
        "CREATE TABLE s (i INTEGER, r REAL, t TEXT)",
        "INSERT INTO s VALUES (1, 1.0, '1'), (2, 2.0, '2'), (3, NULL, 'x')",
    )
    pair.check("SELECT sum(i), sum(r), sum(t), avg(i), avg(t), total(i), min(t), max(t) FROM s")
    pair.check("SELECT sum(i) FROM s WHERE i < 3")


def test_group_by_null_forms_one_group(pair):
    pair.run(
        "CREATE TABLE g (k TEXT, v INTEGER)",
        "INSERT INTO g VALUES (NULL, 1), ('a', 2), (NULL, 3), ('a', NULL), ('b', NULL)",
    )
    pair.check("SELECT k, count(*), count(v), sum(v), avg(v) FROM g GROUP BY k")


def test_large_join_matches_sqlite(pair):
    pair.run("CREATE TABLE a (id INTEGER, grp INTEGER)", "CREATE TABLE b (grp INTEGER, label TEXT)")
    pair.run("INSERT INTO a VALUES " + ", ".join(f"({i}, {i % 7})" for i in range(200)))
    pair.run("INSERT INTO b VALUES " + ", ".join(f"({i % 9}, 'L{i}')" for i in range(40)))
    pair.check(
        "SELECT a.grp, count(b.label), min(b.label) FROM a LEFT JOIN b ON a.grp = b.grp "
        "GROUP BY a.grp ORDER BY a.grp"
    )


BARE_COLUMN_QUERIES = [
    "SELECT v, count(*) FROM u",
    "SELECT v, sum(k) FROM u WHERE k > 1",
    "SELECT v, max(k) FROM u",
    "SELECT v, min(k), max(k) FROM u",
    "SELECT v, max(k), min(k) FROM u",
    "SELECT g, v, count(*) FROM u GROUP BY g",
    "SELECT g, v, max(k) FROM u GROUP BY g",
    "SELECT g, v, min(k) FROM u GROUP BY g",
    "SELECT g, v, min(k), max(k) FROM u GROUP BY g",
    "SELECT g, v, max(k), count(*) FROM u GROUP BY g HAVING min(k) > 0 OR max(k) IS NULL",
    "SELECT g, v, min(k) FROM u GROUP BY g ORDER BY max(k)",
]


@pytest.mark.parametrize("sql", BARE_COLUMN_QUERIES)
def test_bare_columns_pick_sqlite_row(pair, sql):
    pair.run(
        "CREATE TABLE u (g INTEGER, k INTEGER, v TEXT)",
        "INSERT INTO u VALUES (1, 5, 'a'), (1, NULL, 'b'), (1, 9, 'c'), (1, 9, 'd'), (1, 1, 'e')",
        "INSERT INTO u VALUES (1, 1, 'f'), (1, 7, 'h'), (2, NULL, 'a'), (2, NULL, 'b'), (2, 3, 'c')",
        "INSERT INTO u VALUES (2, NULL, 'd'), (3, NULL, 'a'), (3, NULL, 'b')",
    )
    pair.check(sql)


def test_group_key_value_comes_from_first_row(pair):
    pair.run("CREATE TABLE t (k, v TEXT)", "INSERT INTO t VALUES (2.0, 'a'), (2, 'b'), (3, 'c'), (2, 'd')")
    pair.check("SELECT k, v, count(*) FROM t GROUP BY k")


NAME_RESOLUTION_QUERIES = [
    "SELECT salary * 2 AS s2 FROM emp WHERE s2 > 150000",
    "SELECT id AS salary FROM emp ORDER BY salary + 0, id",
    "SELECT dept AS name, count(*) FROM emp GROUP BY name ORDER BY 1, 2",
    "SELECT dept AS d, count(*) AS n FROM emp GROUP BY d ORDER BY n DESC, d",
    "SELECT *, name FROM emp ORDER BY id",
    "SELECT name, * FROM dept d JOIN emp e ON e.dept = d.code ORDER BY e.id",
    "SELECT e.*, d.* FROM emp e LEFT JOIN dept d ON d.code = e.dept ORDER BY e.id",
    "SELECT DISTINCT dept FROM emp ORDER BY dept DESC",
    "SELECT name FROM emp WHERE name > 'a' ORDER BY name",
    "SELECT upper(name) AS u FROM emp ORDER BY u",
    "SELECT e.name, b.name, d.title FROM emp e JOIN emp b ON e.boss = b.id JOIN dept d ON d.code = b.dept "
    "ORDER BY e.id",
    "SELECT d.title, count(*) FROM emp e JOIN emp b ON e.boss = b.id JOIN dept d ON d.code = b.dept "
    "GROUP BY d.title ORDER BY 2 DESC, 1",
    "SELECT dept, name FROM emp GROUP BY dept HAVING name > 'B' ORDER BY dept",
    "SELECT age, count(*) FROM emp WHERE age IN (28, 39, NULL) GROUP BY age ORDER BY age",
    "SELECT name FROM emp WHERE (age > 30 AND dept = 'eng') OR (salary < 60000 AND NOT dept IS NULL)",
    "SELECT name FROM emp WHERE NOT age BETWEEN 25 AND 40 ORDER BY name",
    "SELECT count(*), count(DISTINCT dept), count(DISTINCT salary) FROM emp WHERE dept LIKE '%S'",
]


@pytest.mark.parametrize("sql", NAME_RESOLUTION_QUERIES)
def test_name_resolution_matches_sqlite(sample, sql):
    sample.check(sql)
