"""Curated queries whose results must match sqlite3 exactly."""

import pytest

COMPANY_QUERIES = [
    # projection, star, aliases
    "SELECT * FROM emp",
    "SELECT e.* FROM emp e",
    "SELECT d.*, e.name FROM dept d JOIN emp e ON e.dept_id = d.id",
    "SELECT name AS n, salary * 2 AS double_pay FROM emp ORDER BY n",
    "SELECT name n FROM emp ORDER BY n DESC",
    "SELECT DISTINCT dept_id FROM emp ORDER BY dept_id",
    "SELECT DISTINCT title FROM emp",
    "SELECT DISTINCT dept_id, title FROM emp ORDER BY dept_id, title",
    # WHERE and three-valued logic
    "SELECT name FROM emp WHERE salary > 90000",
    "SELECT name FROM emp WHERE NOT salary > 90000",
    "SELECT name FROM emp WHERE salary IS NULL",
    "SELECT name FROM emp WHERE salary IS NOT NULL AND dept_id = 1",
    "SELECT name FROM emp WHERE dept_id = 1 OR manager_id IS NULL",
    "SELECT name FROM emp WHERE manager_id = NULL",
    "SELECT name FROM emp WHERE manager_id != 1",
    "SELECT name FROM emp WHERE NOT (manager_id = 1)",
    "SELECT name FROM emp WHERE dept_id IN (1, 3)",
    "SELECT name FROM emp WHERE dept_id NOT IN (1, 3)",
    "SELECT name FROM emp WHERE dept_id NOT IN (1, NULL)",
    "SELECT name FROM emp WHERE dept_id IN (2, NULL)",
    "SELECT name FROM emp WHERE salary BETWEEN 60000 AND 100000",
    "SELECT name FROM emp WHERE salary NOT BETWEEN 60000 AND 100000",
    "SELECT name FROM emp WHERE name LIKE 'a%'",
    "SELECT name FROM emp WHERE name LIKE '%E%'",
    "SELECT name FROM emp WHERE name NOT LIKE '_o%'",
    "SELECT name FROM emp WHERE title LIKE 'engineer'",
    "SELECT name FROM emp WHERE name = 'alice'",
    "SELECT name FROM emp WHERE name > 'D' ORDER BY name",
    "SELECT name, (salary > 90000) AND (dept_id = 1) FROM emp",
    "SELECT name, (salary > 90000) OR (manager_id = 1) FROM emp",
    "SELECT name, NOT (salary > 90000) FROM emp",
    # ORDER BY
    "SELECT name, salary FROM emp ORDER BY salary",
    "SELECT name, salary FROM emp ORDER BY salary DESC",
    "SELECT name, salary FROM emp ORDER BY salary DESC, name ASC",
    "SELECT name, dept_id FROM emp ORDER BY dept_id DESC, name",
    "SELECT name, dept_id FROM emp ORDER BY 2, 1 DESC",
    "SELECT name FROM emp ORDER BY salary * -1, name",
    "SELECT name FROM emp ORDER BY lower(name)",
    "SELECT name, salary AS s FROM emp ORDER BY s DESC, name",
    "SELECT name, salary AS s FROM emp ORDER BY s + 0 DESC, name",
    "SELECT name AS dept_id, dept_id AS name FROM emp ORDER BY name, dept_id",
    "SELECT name FROM emp ORDER BY title, name",
    "SELECT name FROM emp ORDER BY manager_id IS NULL, name",
    # LIMIT / OFFSET
    "SELECT name FROM emp ORDER BY id LIMIT 3",
    "SELECT name FROM emp ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT name FROM emp ORDER BY id LIMIT 2, 3",
    "SELECT name FROM emp ORDER BY id LIMIT 0",
    "SELECT name FROM emp ORDER BY id LIMIT -1 OFFSET 6",
    "SELECT name FROM emp ORDER BY id LIMIT 100 OFFSET 100",
    "SELECT name FROM emp ORDER BY id LIMIT 1 + 1",
    # joins
    "SELECT e.name, d.name FROM emp e JOIN dept d ON e.dept_id = d.id",
    "SELECT e.name, d.name FROM emp e INNER JOIN dept d ON e.dept_id = d.id "
    "ORDER BY d.name, e.name",
    "SELECT e.name, d.name FROM emp e LEFT JOIN dept d ON e.dept_id = d.id",
    "SELECT e.name, d.name FROM emp e LEFT OUTER JOIN dept d ON e.dept_id = d.id",
    "SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id ORDER BY d.id, e.id",
    "SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id AND e.salary > 90000",
    "SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id WHERE e.id IS NULL",
    "SELECT e.name, m.name FROM emp e LEFT JOIN emp m ON e.manager_id = m.id",
    "SELECT e.name, m.name FROM emp AS e JOIN emp AS m ON e.manager_id = m.id",
    "SELECT e.name, p.name, d.name FROM emp e JOIN project p ON p.emp_id = e.id "
    "JOIN dept d ON d.id = e.dept_id",
    "SELECT e.name, p.name, d.name FROM emp e LEFT JOIN project p ON p.emp_id = e.id "
    "LEFT JOIN dept d ON d.id = e.dept_id",
    "SELECT p.name, e.name FROM project p LEFT JOIN emp e ON p.emp_id = e.id",
    "SELECT e.name, d.name FROM emp e JOIN dept d ON e.dept_id < d.id",
    "SELECT e.name, d.name FROM emp e LEFT JOIN dept d ON d.budget > e.salary * 10",
    "SELECT count(*) FROM emp, dept",
    "SELECT e.name, d.name FROM emp e CROSS JOIN dept d WHERE d.id = 4",
    "SELECT e.name, title, budget FROM emp e JOIN dept d ON e.dept_id = d.id",
    "SELECT dept.name, emp.name FROM dept JOIN emp ON emp.dept_id = dept.id",
    "SELECT e.name, d.name FROM emp e LEFT JOIN dept d ON e.dept_id = d.id AND d.budget IS NULL",
    "SELECT e.name, d.name FROM emp e LEFT JOIN dept d ON 1 = 0",
    # aggregates
    "SELECT count(*), count(salary), count(DISTINCT salary), sum(salary), avg(salary), "
    "min(salary), max(salary) FROM emp",
    "SELECT count(*), sum(salary), avg(salary), min(salary), max(salary), total(salary) "
    "FROM emp WHERE id > 100",
    "SELECT count(*) FROM emp WHERE 0",
    "SELECT sum(hours), avg(hours), min(hours), max(hours), count(hours) FROM project",
    "SELECT sum(id), avg(id) FROM emp",
    "SELECT min(name), max(name), min(title), max(title) FROM emp",
    "SELECT dept_id, count(*) FROM emp GROUP BY dept_id",
    "SELECT dept_id, count(*), sum(salary), avg(salary) FROM emp GROUP BY dept_id "
    "ORDER BY dept_id",
    "SELECT dept_id, count(*) FROM emp GROUP BY dept_id HAVING count(*) > 1",
    "SELECT dept_id, count(*) AS c FROM emp GROUP BY dept_id HAVING c >= 2 ORDER BY c DESC",
    "SELECT dept_id, max(salary) FROM emp GROUP BY dept_id HAVING max(salary) > 65000",
    "SELECT dept_id FROM emp GROUP BY dept_id HAVING sum(salary) IS NULL",
    "SELECT dept_id, count(*) FROM emp GROUP BY dept_id ORDER BY count(*) DESC, dept_id",
    "SELECT dept_id, count(*) FROM emp GROUP BY dept_id ORDER BY sum(salary)",
    "SELECT dept_id, title, count(*) FROM emp GROUP BY dept_id, title",
    "SELECT lower(title) AS t, count(*) FROM emp GROUP BY t ORDER BY t",
    "SELECT lower(title), count(*) FROM emp GROUP BY lower(title) ORDER BY 1",
    "SELECT dept_id % 2, count(*) FROM emp GROUP BY 1 ORDER BY 1",
    "SELECT salary > 90000, count(*) FROM emp GROUP BY salary > 90000",
    "SELECT d.name, count(e.id), sum(e.salary) FROM dept d LEFT JOIN emp e "
    "ON e.dept_id = d.id GROUP BY d.name ORDER BY d.name",
    "SELECT d.name, count(*), count(e.id) FROM dept d LEFT JOIN emp e ON e.dept_id = d.id "
    "GROUP BY d.id ORDER BY 2 DESC, 1",
    "SELECT e.name, sum(p.hours), count(p.id) FROM emp e LEFT JOIN project p ON p.emp_id = e.id "
    "GROUP BY e.id, e.name HAVING count(p.id) > 0 ORDER BY e.name",
    "SELECT count(DISTINCT dept_id), count(DISTINCT title), sum(DISTINCT salary), "
    "avg(DISTINCT salary) FROM emp",
    "SELECT count(DISTINCT name) FROM project",
    "SELECT name, count(*) FROM project GROUP BY name HAVING count(DISTINCT emp_id) > 1",
    "SELECT count(*) > 3, sum(salary) / count(salary) FROM emp",
    "SELECT max(salary) - min(salary) FROM emp",
    "SELECT dept_id, max(salary), name FROM emp GROUP BY dept_id",
    "SELECT dept_id, min(salary), name FROM emp GROUP BY dept_id",
    "SELECT max(salary), name FROM emp",
    "SELECT min(id), max(id) FROM emp WHERE dept_id = 1",
    "SELECT count(*) FROM emp HAVING count(*) > 100",
    "SELECT count(*) FROM emp HAVING count(*) > 1",
    "SELECT dept_id, count(*) FROM emp WHERE salary > 1000000 GROUP BY dept_id",
    "SELECT avg(hours), sum(hours) FROM project WHERE hours IS NULL",
    "SELECT DISTINCT count(*) FROM emp GROUP BY dept_id",
    "SELECT dept_id, avg(salary) FROM emp GROUP BY dept_id ORDER BY avg(salary) DESC",
    "SELECT dept_id, count(*) FROM emp GROUP BY dept_id ORDER BY 2 DESC, 1 LIMIT 2",
    "SELECT title FROM emp GROUP BY title ORDER BY title",
    # expressions in select
    "SELECT name || ' (' || title || ')' FROM emp",
    "SELECT id * 10 + 1, id / 2, id % 3, -id, id - 0.5 FROM emp",
    "SELECT salary / 1000, salary / 7 FROM emp",
    "SELECT hours / 3, hours % 7, hours * 1.0 / 3 FROM project",
    "SELECT CASE WHEN salary > 100000 THEN 'high' WHEN salary > 60000 THEN 'mid' "
    "ELSE 'low' END FROM emp",
    "SELECT CASE dept_id WHEN 1 THEN 'eng' WHEN 2 THEN 'sales' END FROM emp",
    "SELECT coalesce(salary, 0), ifnull(title, 'none'), nullif(dept_id, 1) FROM emp",
    "SELECT abs(-salary), length(name), upper(name), lower(name) FROM emp",
    "SELECT typeof(salary), typeof(id), typeof(name), typeof(manager_id) FROM emp",
    "SELECT CAST(salary AS INTEGER), CAST(id AS TEXT), CAST('12.5' AS REAL) FROM emp",
    "SELECT name FROM emp WHERE CAST(salary AS INTEGER) = 95000",
]


@pytest.mark.parametrize("sql", COMPANY_QUERIES)
def test_company_queries(company, sql):
    company.check(sql)


EXPRESSIONS = [
    # integer vs real arithmetic
    "7 / 2", "-7 / 2", "7 / -2", "7.0 / 2", "7 / 2.0", "1 / 3.0", "7 % 3", "-7 % 3", "7 % -3",
    "7.5 % 2", "-7.5 % 2", "5 % 2.5", "7 / 0", "7 % 0", "7.0 / 0", "0 / 0", "7 / 0.0",
    "7 % 0.0", "5 % 0.5", "2 * 3", "2 * 3.0", "2 + 3", "2 - 3.5", "1e3", "1.5e-3 * 2",
    ".5 + 1.", "9223372036854775807 + 1", "-9223372036854775808 - 1",
    "9223372036854775807 * 2", "-9223372036854775808", "9223372036854775808",
    "(-9223372036854775808) / -1", "(-9223372036854775808) % -1", "- -5", "-(-5.5)",
    "0x10", "0x10 + 1", "1 + 2 * 3", "(1 + 2) * 3", "10 - 2 - 3", "100 / 10 / 5",
    "2 * 3 % 4", "-2 * 3", "- 2 - - 3", "+'abc'", "+5", "+NULL",
    # NULL propagation
    "NULL + 1", "1 - NULL", "NULL * NULL", "NULL / 0", "NULL % 2", "-NULL", "NULL || 'a'",
    "NULL = NULL", "NULL != 1", "NULL < 1", "NULL IS NULL", "1 IS NULL", "NULL IS NOT NULL",
    "NULL IS NOT 1", "1 IS 1", "1 IS NOT 1.0", "'a' IS 'a'",
    # three-valued logic
    "NULL AND 0", "NULL AND 1", "0 AND NULL", "NULL OR 1", "NULL OR 0", "1 OR NULL",
    "NOT NULL", "NOT 0", "NOT 1", "NOT 5", "NOT 0.0", "NOT 0.5", "NOT 'abc'", "NOT '1abc'",
    "NOT ''", "1 AND 'x'", "2 AND 3", "0 OR 0.0", "'1' OR 0", "NULL AND NULL",
    "1 = 1 AND 2 = 2 OR 1 = 0", "1 OR 0 AND 0", "NOT 1 = 2", "NOT 1 IS NULL",
    # comparisons across types
    "1 = 1.0", "1 < 1.5", "2 > 1.5", "1 = '1'", "1 < 'a'", "'a' < 'b'", "'a' < 'B'",
    "'abc' = 'ABC'", "'' < 'a'", "'10' < '9'", "10 < 9", "1 <> 2", "1 != 1", "1 == 1",
    "1 <= 1", "1 >= 2", "'a' > 1", "0.5 < 1", "NULL <> NULL",
    # IN / BETWEEN
    "1 IN (1, 2)", "3 IN (1, 2)", "NULL IN (1, 2)", "1 IN (NULL, 1)", "3 IN (NULL, 1)",
    "3 NOT IN (NULL, 1)", "1 NOT IN (NULL, 1)", "1 IN ()", "NULL IN ()", "NULL NOT IN ()",
    "1 IN ('1')", "'a' IN ('A', 'a')", "1.0 IN (1)", "2 IN (1 + 1, 3)",
    "5 BETWEEN 1 AND 10", "5 BETWEEN 10 AND 1", "5 NOT BETWEEN 1 AND 4", "NULL BETWEEN 1 AND 2",
    "1 BETWEEN NULL AND 2", "0 BETWEEN NULL AND -1", "'b' BETWEEN 'a' AND 'c'",
    "2.5 BETWEEN 2 AND 3", "1 BETWEEN 1 AND 1", "5 BETWEEN 1 AND 10 AND 0",
    # LIKE
    "'hello' LIKE 'h%'", "'hello' LIKE 'H%'", "'HELLO' LIKE '%ll%'", "'hello' LIKE 'h_llo'",
    "'hello' LIKE 'h_lo'", "'hello' LIKE ''", "'' LIKE ''", "'' LIKE '%'", "'abc' LIKE 'abc%'",
    "'a%c' LIKE 'a%'", "'abc' LIKE '%b%'", "'abc' NOT LIKE '%b%'", "NULL LIKE 'a'",
    "'a' LIKE NULL", "NULL NOT LIKE 'a'", "123 LIKE '1%'", "12.5 LIKE '%.5'",
    "'äbc' LIKE 'Äbc'", "'äbc' LIKE 'äBC'", "'a.c' LIKE 'a.c'", "'abc' LIKE 'a.c'",
    "'a\nb' LIKE 'a_b'", "'[x]' LIKE '[x]'", "'x+' LIKE 'x+'", "'a_c' LIKE 'a!_c' ESCAPE '!'",
    "'abc' LIKE 'a!_c' ESCAPE '!'", "'Z' LIKE 'z'",
    # string concatenation and conversion
    "'a' || 'b'", "'a' || 1", "1 || 2", "1.5 || 'x'", "2.0 || ''", "1e20 || ''", "0.1 || ''",
    "1e-5 || ''", "(1.0 / 3) || ''", "-0.0 || ''", "100.0 || ''", "123456789012345.0 || ''",
    "1e15 || ''", "'a' || 1 + 2", "'3' + 4", "'3.5' * 2", "'abc' + 1", "'12abc' + 1",
    "' 12 ' + 1", "'1e2' + 0", "'-5' - 1", "-'3'", "-'abc'", "'5' / 2", "'5.0' / 2",
    "'10' % '3'", "'x' * 2",
    # scalar functions and CASE/CAST
    "abs(-5)", "abs(-5.5)", "abs(NULL)", "abs('-3')", "coalesce(NULL, NULL, 3)",
    "coalesce(NULL, 'a')", "ifnull(NULL, 2)", "nullif(1, 1)", "nullif(1, 2)",
    "length('héllo')", "length(12345)", "length(NULL)", "upper('abcé')", "lower('ABCÉ')",
    "typeof(1)", "typeof(1.0)", "typeof('1')", "typeof(NULL)", "typeof(1 / 2)",
    "typeof(1 / 2.0)", "CASE WHEN NULL THEN 1 ELSE 2 END", "CASE WHEN 0 THEN 1 END",
    "CASE 1 WHEN 1.0 THEN 'yes' ELSE 'no' END", "CASE NULL WHEN NULL THEN 1 ELSE 0 END",
    "CASE 'a' WHEN 'A' THEN 1 WHEN 'a' THEN 2 END", "CAST('42' AS INTEGER)",
    "CAST('4.7' AS INTEGER)", "CAST(4.7 AS INTEGER)", "CAST(-4.7 AS INTEGER)",
    "CAST('1e2' AS INTEGER)", "CAST('abc' AS INTEGER)", "CAST(3 AS REAL)", "CAST(3 AS TEXT)",
    "CAST(3.0 AS TEXT)", "CAST(NULL AS INTEGER)", "CAST('  7' AS REAL)", "max(1, 2, 3)",
    "min(1, 'a', 2.5)", "max(1, NULL)",
]


@pytest.mark.parametrize("expr", EXPRESSIONS)
def test_scalar_expressions(both, expr):
    both.check(f"SELECT {expr}")


def test_expressions_over_table_columns(both):
    both.run(
        "CREATE TABLE v (i INTEGER, r REAL, t TEXT)",
        "INSERT INTO v VALUES (1, 1.0, '1'), (2, 2.5, 'abc'), (NULL, NULL, NULL), "
        "(-3, -0.5, '10'), (0, 0.0, ''), (10, 1e10, 'ABC'), (7, 3.5, '7')",
    )
    for expr in EXPRESSIONS:
        both.check(f"SELECT {expr} FROM v")
    columns = ["i", "r", "t", "NULL", "1", "'1'", "2.5", "'abc'"]
    ops = ["=", "<", ">=", "!=", "IS", "IS NOT", "+", "-", "*", "/", "%", "||", "AND", "OR"]
    for a in columns:
        for b in columns:
            for op in ops:
                both.check(f"SELECT i, {a} {op} {b} FROM v")
            both.check(f"SELECT i, {a} IN ({b}, 2), {a} BETWEEN {b} AND 5, {a} LIKE {b} FROM v")


def test_column_affinity_in_comparisons(both):
    both.run(
        "CREATE TABLE a (i INTEGER, r REAL, t TEXT)",
        "INSERT INTO a VALUES (1, 1.0, '1'), (12, 12.5, '12'), (2, 2.0, 'x'), (NULL, NULL, '1.0')",
    )
    for sql in [
        "SELECT * FROM a WHERE t = 1",
        "SELECT * FROM a WHERE t = 12",
        "SELECT * FROM a WHERE t > 5",
        "SELECT * FROM a WHERE i = '1'",
        "SELECT * FROM a WHERE i = '1.0'",
        "SELECT * FROM a WHERE r = '12.5'",
        "SELECT * FROM a WHERE i < 'a'",
        "SELECT * FROM a WHERE i = t",
        "SELECT * FROM a WHERE r = t",
        "SELECT * FROM a WHERE t IN (1, 12)",
        "SELECT * FROM a WHERE i IN ('1', '12')",
        "SELECT * FROM a WHERE 1 IN (t)",
        "SELECT * FROM a WHERE t BETWEEN 1 AND 12",
        "SELECT * FROM a WHERE i BETWEEN '1' AND '5'",
        "SELECT * FROM a WHERE t IS 1",
        "SELECT * FROM a WHERE +t = 1",
        "SELECT * FROM a WHERE +i = '1'",
        "SELECT * FROM a WHERE -t = -1",
        "SELECT * FROM a WHERE t LIKE 1",
        "SELECT i, t, CASE t WHEN 1 THEN 'one' ELSE 'other' END FROM a",
        "SELECT x.i, y.t FROM a x JOIN a y ON x.i = y.t",
        "SELECT x.i, y.t FROM a x LEFT JOIN a y ON y.t = x.r",
    ]:
        both.check(sql)


def test_null_ordering(both):
    both.run(
        "CREATE TABLE n (a INTEGER, b TEXT)",
        "INSERT INTO n VALUES (3, 'c'), (NULL, 'x'), (1, NULL), (2, 'a'), (NULL, NULL)",
    )
    both.check("SELECT a, b FROM n ORDER BY a, b")
    both.check("SELECT a, b FROM n ORDER BY a DESC, b DESC")
    both.check("SELECT b FROM n ORDER BY b DESC")
    both.check("SELECT a FROM n GROUP BY a ORDER BY a DESC")


def test_mixed_type_ordering(both):
    both.run(
        "CREATE TABLE m (x TEXT, y)",
        "INSERT INTO m VALUES ('b', 'b'), ('a', 1), (NULL, 2.5), ('B', NULL), ('10', 10), "
        "('9', 'A'), ('', -1)",
    )
    both.check("SELECT y FROM m ORDER BY y")
    both.check("SELECT y FROM m ORDER BY y DESC")
    both.check("SELECT x FROM m ORDER BY x")
    both.check("SELECT min(y), max(y), min(x), max(x) FROM m")
    both.check("SELECT DISTINCT typeof(y) FROM m ORDER BY 1")


def test_aggregates_over_empty_and_null_inputs(both):
    both.run("CREATE TABLE e (a INTEGER, b REAL, c TEXT)")
    aggs = "count(*), count(a), sum(a), avg(a), min(a), max(a), total(a), sum(b), avg(b), max(c)"
    both.check(f"SELECT {aggs} FROM e")
    both.check(f"SELECT {aggs} FROM e WHERE a > 0")
    both.check(f"SELECT a, {aggs} FROM e GROUP BY a")
    both.run("INSERT INTO e VALUES (NULL, NULL, NULL), (NULL, NULL, NULL)")
    both.check(f"SELECT {aggs} FROM e")
    both.check(f"SELECT a, {aggs} FROM e GROUP BY a")
    both.run("INSERT INTO e VALUES (1, 1.5, 'x'), (2, NULL, 'y'), (2, 2.5, NULL)")
    both.check(f"SELECT {aggs} FROM e")
    both.check(f"SELECT a, {aggs} FROM e GROUP BY a ORDER BY a")
    both.check("SELECT count(DISTINCT a), sum(DISTINCT a), avg(DISTINCT a) FROM e")


def test_sum_and_avg_types(both):
    both.run(
        "CREATE TABLE s (i INTEGER, r REAL)",
        "INSERT INTO s VALUES (1, 0.1), (2, 0.2), (3, 0.3), (4, 1e16), (5, -1e16), (6, 0.7)",
    )
    both.check("SELECT sum(i), avg(i), total(i), sum(r), avg(r), sum(i + r) FROM s")
    both.check("SELECT i % 2, sum(r), avg(r) FROM s GROUP BY i % 2 ORDER BY 1")
    both.check("SELECT sum(i) / count(*), sum(i) * 1.0 / count(*) FROM s")


def test_left_join_unmatched_rows(both):
    both.run(
        "CREATE TABLE l (id INTEGER, v TEXT)",
        "CREATE TABLE r (id INTEGER, w INTEGER)",
        "INSERT INTO l VALUES (1, 'a'), (2, 'b'), (3, 'c'), (NULL, 'n')",
        "INSERT INTO r VALUES (1, 10), (1, 11), (3, NULL), (NULL, 99)",
    )
    both.check("SELECT l.v, r.w FROM l LEFT JOIN r ON l.id = r.id ORDER BY l.v, r.w")
    both.check("SELECT l.v, r.w FROM l LEFT JOIN r ON l.id = r.id WHERE r.w IS NULL")
    both.check("SELECT l.v, count(r.id), count(*), sum(r.w) FROM l LEFT JOIN r "
               "ON l.id = r.id GROUP BY l.v ORDER BY l.v")
    both.check("SELECT * FROM l LEFT JOIN r ON l.id = r.id AND r.w > 10")
    both.check("SELECT * FROM r LEFT JOIN l ON l.id = r.id")
    both.check("SELECT l.v, r.w, x.v FROM l LEFT JOIN r ON l.id = r.id "
               "LEFT JOIN l x ON x.id = r.w")
    both.check("SELECT l.v, r.w FROM l LEFT JOIN r ON l.id = r.id "
               "JOIN l x ON x.id = l.id ORDER BY 1, 2")
    both.check("SELECT l.id, r.id FROM l LEFT JOIN r ON r.id IS l.id")


def test_insert_select_and_update_expressions(both):
    both.run(
        "CREATE TABLE src (a INTEGER, b TEXT)",
        "CREATE TABLE dst (a INTEGER, b TEXT, c REAL)",
        "INSERT INTO src VALUES (1, 'x'), (2, 'y'), (3, NULL)",
        "INSERT INTO dst (a, b) SELECT a * 10, b || '!' FROM src WHERE a < 3",
        "UPDATE dst SET c = a / 3, b = upper(b) WHERE a > 10",
        "UPDATE dst SET a = a + 1",
    )
    both.check("SELECT * FROM dst ORDER BY a")


def test_where_can_use_select_alias(both):
    both.run(
        "CREATE TABLE t (a INTEGER, b INTEGER)",
        "INSERT INTO t VALUES (1, 2), (3, 4), (5, 6)",
    )
    both.check("SELECT a + b AS s FROM t WHERE s > 5")
    both.check("SELECT a AS b FROM t WHERE b > 2")
    both.check("SELECT a * 2 AS d FROM t GROUP BY d HAVING d > 2 ORDER BY d DESC")


def test_bare_columns_follow_min_max(both):
    both.run(
        "CREATE TABLE t (g INTEGER, v INTEGER, name TEXT)",
        "INSERT INTO t VALUES (1, 5, 'a'), (1, 9, 'b'), (1, 7, 'c'), (2, 3, 'd'), (2, 1, 'e')",
    )
    both.check("SELECT g, max(v), name FROM t GROUP BY g ORDER BY g")
    both.check("SELECT g, min(v), name FROM t GROUP BY g ORDER BY g")
    both.check("SELECT max(v), name FROM t")
    both.check("SELECT min(v), name FROM t")
