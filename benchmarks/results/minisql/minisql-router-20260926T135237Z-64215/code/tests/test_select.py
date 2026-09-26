"""SELECT features: joins, grouping, aggregates, ordering, limits, distinct."""

import pytest


@pytest.fixture
def emp(pair):
    pair.run(
        "CREATE TABLE dept (id INTEGER, name TEXT, budget REAL)",
        "INSERT INTO dept VALUES (1, 'eng', 1000.5), (2, 'sales', 500), (3, 'hr', NULL), "
        "(4, 'empty', 10)",
        "CREATE TABLE emp (id INTEGER, name TEXT, dept_id INTEGER, salary INTEGER, bonus REAL)",
        "INSERT INTO emp VALUES "
        "(1, 'alice', 1, 100, 1.5), (2, 'bob', 1, 80, NULL), (3, 'carol', 2, 90, 2.0), "
        "(4, 'dave', 2, NULL, 0.5), (5, 'eve', NULL, 70, NULL), (6, 'Frank', 3, 60, 3.25), "
        "(7, 'grace', 9, 75, 1.0)",
        "CREATE TABLE proj (id INTEGER, emp_id INTEGER, title TEXT)",
        "INSERT INTO proj VALUES (1, 1, 'db'), (2, 1, 'ui'), (3, 3, 'crm'), (4, 99, 'ghost')",
        "CREATE TABLE empty_t (x INTEGER, y TEXT)",
    )
    return pair


# -- basic projection ---------------------------------------------------------


def test_select_star_and_columns(emp):
    emp.check("SELECT * FROM emp")
    emp.check("SELECT name, salary FROM emp")
    emp.check("SELECT salary * 2 AS double_pay, name AS n FROM emp")
    emp.check("SELECT salary * 2 double_pay, name n FROM emp")
    emp.check("SELECT e.* FROM emp AS e")
    emp.check("SELECT e.*, d.name FROM emp e JOIN dept d ON e.dept_id = d.id")
    emp.check("SELECT d.*, e.* FROM emp e JOIN dept d ON e.dept_id = d.id")
    emp.check("SELECT *, id FROM dept")
    emp.check("SELECT emp.name FROM emp")
    emp.check("SELECT 1, 'x', NULL FROM dept")


def test_select_without_from(pair):
    pair.check("SELECT 1 + 1, 'a' || 'b'")


def test_empty_table(emp):
    emp.check("SELECT * FROM empty_t")
    emp.check("SELECT x + 1 FROM empty_t WHERE x > 0 ORDER BY x")
    emp.check("SELECT COUNT(*), COUNT(x), SUM(x), AVG(x), MIN(x), MAX(y), TOTAL(x) FROM empty_t")
    emp.check("SELECT x, COUNT(*) FROM empty_t GROUP BY x")
    emp.check("SELECT COUNT(*) FROM empty_t HAVING COUNT(*) > 0")
    emp.check("SELECT DISTINCT x FROM empty_t")
    emp.check("SELECT * FROM emp LEFT JOIN empty_t ON 1")
    emp.check("SELECT * FROM empty_t LEFT JOIN emp ON 1")


# -- WHERE ------------------------------------------------------------------


@pytest.mark.parametrize(
    "cond",
    [
        "salary > 75", "salary IS NULL", "salary IS NOT NULL", "bonus IS NULL OR salary < 80",
        "dept_id IN (1, 3)", "dept_id NOT IN (1, 3)", "dept_id NOT IN (1, NULL)",
        "salary BETWEEN 70 AND 90", "salary NOT BETWEEN 70 AND 90", "name LIKE '%a%'",
        "name LIKE 'F%'", "name NOT LIKE '_o%'", "salary", "bonus", "NULL", "NOT salary > 80",
        "salary > 75 AND bonus > 1", "salary / 0 IS NULL", "name = 'ALICE'", "name > 'd'",
        "salary = '100'", "bonus = '1.5'", "name = 1", "salary % 20 = 0", "-salary < -80",
        "(salary > 90 OR bonus > 2) AND NOT dept_id = 3",
    ],
)
def test_where(emp, cond):
    emp.check(f"SELECT id FROM emp WHERE {cond}")


# -- joins ------------------------------------------------------------------


def test_inner_join(emp):
    emp.check("SELECT e.name, d.name FROM emp e JOIN dept d ON e.dept_id = d.id")
    emp.check("SELECT e.name, d.name FROM emp e INNER JOIN dept AS d ON d.id = e.dept_id")
    emp.check("SELECT emp.name, dept.name FROM emp JOIN dept ON emp.dept_id = dept.id")
    emp.check(
        "SELECT e.name, d.name FROM emp e JOIN dept d ON e.dept_id = d.id AND d.budget > 600"
    )
    emp.check("SELECT e.name, d.name FROM emp e JOIN dept d ON 1 WHERE e.id < 3")
    emp.check("SELECT e.name, d.name FROM emp e, dept d WHERE e.dept_id = d.id")
    emp.check("SELECT e.name, d.name FROM emp e CROSS JOIN dept d WHERE e.id = 1")


def test_left_join(emp):
    emp.check("SELECT e.name, d.name FROM emp e LEFT JOIN dept d ON e.dept_id = d.id")
    emp.check("SELECT e.name, d.name FROM emp e LEFT OUTER JOIN dept d ON e.dept_id = d.id")
    emp.check("SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id")
    emp.check("SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON 0")
    emp.check(
        "SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id "
        "WHERE e.id IS NULL"
    )
    emp.check(
        "SELECT d.name, e.name FROM dept d LEFT JOIN emp e "
        "ON e.dept_id = d.id AND e.salary > 85"
    )
    emp.check("SELECT * FROM dept d LEFT JOIN emp e ON e.dept_id = d.id")


def test_multi_join(emp):
    emp.check(
        "SELECT e.name, d.name, p.title FROM emp e "
        "JOIN dept d ON e.dept_id = d.id JOIN proj p ON p.emp_id = e.id"
    )
    emp.check(
        "SELECT e.name, d.name, p.title FROM emp e "
        "LEFT JOIN dept d ON e.dept_id = d.id LEFT JOIN proj p ON p.emp_id = e.id"
    )
    emp.check(
        "SELECT p.title, e.name, d.name FROM proj p "
        "LEFT JOIN emp e ON p.emp_id = e.id JOIN dept d ON d.id = e.dept_id"
    )
    emp.check(
        "SELECT a.name, b.name FROM emp a JOIN emp b ON a.dept_id = b.dept_id AND a.id < b.id"
    )
    emp.check(
        "SELECT d.name, COUNT(p.id) FROM dept d LEFT JOIN emp e ON e.dept_id = d.id "
        "LEFT JOIN proj p ON p.emp_id = e.id GROUP BY d.name ORDER BY d.name"
    )


def test_join_unqualified_unique_column(emp):
    emp.check("SELECT title, salary FROM emp JOIN proj ON emp_id = emp.id")


# -- aggregates ---------------------------------------------------------------


def test_aggregates_without_group_by(emp):
    emp.check(
        "SELECT COUNT(*), COUNT(salary), COUNT(bonus), SUM(salary), SUM(bonus), AVG(salary), "
        "AVG(bonus), MIN(salary), MAX(salary), MIN(name), MAX(name), TOTAL(salary) FROM emp"
    )
    emp.check("SELECT COUNT(DISTINCT dept_id), COUNT(DISTINCT salary) FROM emp")
    emp.check("SELECT SUM(salary) + 1, MAX(salary) - MIN(salary), COUNT(*) * 2 FROM emp")
    emp.check("SELECT SUM(salary) FROM emp WHERE salary IS NULL")
    emp.check("SELECT AVG(salary), MIN(salary), COUNT(*) FROM emp WHERE 0")
    emp.check("SELECT SUM(DISTINCT dept_id), AVG(DISTINCT dept_id) FROM emp")
    emp.check("SELECT MAX(bonus), MIN(bonus) FROM emp")
    emp.check("SELECT SUM(1), SUM(1.0), COUNT(1), COUNT(NULL) FROM emp")


def test_sum_types(pair):
    pair.run(
        "CREATE TABLE t (g INTEGER, i INTEGER, r REAL, s TEXT, n)",
        "INSERT INTO t VALUES (1, 1, 1.5, '2', 1), (1, 2, 2.5, '3.5', 2.0), (2, 3, NULL, 'x', 'y'),"
        " (2, NULL, 0.1, NULL, NULL), (3, NULL, NULL, NULL, NULL)",
    )
    pair.check("SELECT g, SUM(i), SUM(r), SUM(s), SUM(n), AVG(i), AVG(s) FROM t GROUP BY g")
    pair.check("SELECT g, typeof(SUM(i)), typeof(AVG(i)), TOTAL(i) FROM t GROUP BY g")
    pair.check("SELECT MIN(n), MAX(n), MIN(s), MAX(s) FROM t")


def test_sum_many_reals(pair):
    pair.run("CREATE TABLE t (r REAL)")
    values = ", ".join(f"({0.1 * k})" for k in range(1, 60))
    pair.run(f"INSERT INTO t VALUES {values}, (1e16), (-1e16), (3.3)")
    pair.check("SELECT SUM(r), AVG(r), TOTAL(r) FROM t")


def test_sum_integer_overflow(pair):
    pair.run(
        "CREATE TABLE t (a INTEGER)",
        "INSERT INTO t VALUES (9223372036854775807), (1)",
    )
    pair.check_error("SELECT SUM(a) FROM t")
    pair.check("SELECT AVG(a), TOTAL(a) FROM t")


def test_group_by(emp):
    emp.check("SELECT dept_id, COUNT(*) FROM emp GROUP BY dept_id")
    emp.check("SELECT dept_id, COUNT(*), SUM(salary), AVG(bonus) FROM emp GROUP BY dept_id")
    emp.check("SELECT COUNT(*) FROM emp GROUP BY dept_id")
    emp.check("SELECT dept_id, salary > 75 AS hi, COUNT(*) FROM emp GROUP BY dept_id, hi")
    emp.check("SELECT dept_id % 2, COUNT(*) FROM emp GROUP BY dept_id % 2")
    emp.check("SELECT dept_id, COUNT(*) FROM emp GROUP BY 1")
    emp.check("SELECT d.name, SUM(e.salary) FROM emp e JOIN dept d ON e.dept_id = d.id "
              "GROUP BY d.name")
    emp.check("SELECT dept_id, MAX(salary), name FROM emp GROUP BY dept_id")
    emp.check("SELECT dept_id, MIN(salary), name FROM emp GROUP BY dept_id")
    emp.check("SELECT dept_id, COUNT(DISTINCT bonus IS NULL) FROM emp GROUP BY dept_id")


def test_group_by_nulls_are_equal(pair):
    pair.run(
        "CREATE TABLE t (a INTEGER, b TEXT)",
        "INSERT INTO t VALUES (NULL, 'x'), (NULL, 'y'), (1, NULL), (1, NULL), (2, 'x')",
    )
    pair.check("SELECT a, COUNT(*) FROM t GROUP BY a")
    pair.check("SELECT a, b, COUNT(*) FROM t GROUP BY a, b")
    pair.check("SELECT b, COUNT(b), COUNT(*) FROM t GROUP BY b")


def test_having(emp):
    emp.check("SELECT dept_id, COUNT(*) FROM emp GROUP BY dept_id HAVING COUNT(*) > 1")
    emp.check("SELECT dept_id FROM emp GROUP BY dept_id HAVING SUM(salary) > 100")
    emp.check("SELECT dept_id, AVG(salary) AS a FROM emp GROUP BY dept_id HAVING a > 70")
    emp.check("SELECT dept_id FROM emp GROUP BY dept_id HAVING dept_id IS NOT NULL")
    emp.check("SELECT dept_id FROM emp GROUP BY dept_id HAVING MAX(bonus) IS NULL")
    emp.check("SELECT COUNT(*) FROM emp HAVING COUNT(*) > 3")
    emp.check("SELECT COUNT(*) FROM emp HAVING COUNT(*) > 30")


def test_group_by_having_order_by_aggregate(emp):
    emp.check(
        "SELECT dept_id, SUM(salary) AS total FROM emp WHERE dept_id IS NOT NULL "
        "GROUP BY dept_id HAVING COUNT(*) >= 1 ORDER BY SUM(salary) DESC"
    )
    emp.check(
        "SELECT dept_id, COUNT(*) AS c FROM emp GROUP BY dept_id ORDER BY c DESC, dept_id"
    )
    emp.check("SELECT dept_id FROM emp GROUP BY dept_id ORDER BY MAX(bonus), dept_id")
    emp.check("SELECT dept_id, MAX(salary) FROM emp GROUP BY dept_id ORDER BY 2 DESC, 1")


# -- ORDER BY -----------------------------------------------------------------


def test_order_by(emp):
    emp.check("SELECT name FROM emp ORDER BY name")
    emp.check("SELECT name FROM emp ORDER BY name DESC")
    emp.check("SELECT name, salary FROM emp ORDER BY salary, name")
    emp.check("SELECT name, salary FROM emp ORDER BY salary DESC, name")
    emp.check("SELECT name, salary FROM emp ORDER BY salary ASC, name DESC")
    emp.check("SELECT name, bonus FROM emp ORDER BY bonus DESC, id")
    emp.check("SELECT name FROM emp ORDER BY salary * -1, id")
    emp.check("SELECT name, salary AS s FROM emp ORDER BY s, name")
    emp.check("SELECT name, salary AS s FROM emp ORDER BY s DESC, 1")
    emp.check("SELECT name, salary FROM emp ORDER BY 2, 1")
    emp.check("SELECT name, salary FROM emp ORDER BY 2 DESC, 1 DESC")
    emp.check("SELECT name FROM emp ORDER BY dept_id, id")
    emp.check("SELECT name FROM emp ORDER BY lower(name)")
    emp.check("SELECT e.name, d.name FROM emp e LEFT JOIN dept d ON e.dept_id = d.id "
              "ORDER BY d.name, e.name")
    emp.check("SELECT name, salary FROM emp ORDER BY salary IS NULL, salary")
    emp.check("SELECT name AS salary, id FROM emp ORDER BY salary")


def test_order_by_mixed_types(pair):
    pair.run(
        "CREATE TABLE t (v)",
        "INSERT INTO t VALUES (3), ('b'), (NULL), (1.5), ('A'), (-2), (''), ('10'), (10)",
    )
    pair.check("SELECT v FROM t ORDER BY v")
    pair.check("SELECT v FROM t ORDER BY v DESC")
    pair.check("SELECT typeof(v), v FROM t ORDER BY 2")


def test_nulls_first_last(emp):
    emp.check("SELECT name, salary FROM emp ORDER BY salary NULLS LAST, name")
    emp.check("SELECT name, salary FROM emp ORDER BY salary DESC NULLS FIRST, name")


# -- LIMIT / OFFSET -----------------------------------------------------------


@pytest.mark.parametrize(
    "clause",
    ["LIMIT 3", "LIMIT 0", "LIMIT 3 OFFSET 2", "LIMIT 100 OFFSET 5", "LIMIT -1 OFFSET 4",
     "LIMIT 2 OFFSET 100", "LIMIT 1 + 1", "LIMIT 2, 3"],
)
def test_limit_offset(emp, clause):
    emp.check(f"SELECT id, name FROM emp ORDER BY id {clause}")


def test_limit_with_group(emp):
    emp.check("SELECT dept_id, COUNT(*) FROM emp GROUP BY dept_id ORDER BY dept_id LIMIT 2")


# -- DISTINCT -----------------------------------------------------------------


def test_distinct(emp):
    emp.check("SELECT DISTINCT dept_id FROM emp")
    emp.check("SELECT DISTINCT dept_id, salary > 80 FROM emp")
    emp.check("SELECT DISTINCT bonus IS NULL FROM emp")
    emp.check("SELECT DISTINCT dept_id FROM emp ORDER BY dept_id DESC")
    emp.check("SELECT DISTINCT dept_id FROM emp ORDER BY dept_id LIMIT 2 OFFSET 1")
    emp.check("SELECT ALL dept_id FROM emp")


def test_distinct_nulls_and_numeric_equality(pair):
    pair.run(
        "CREATE TABLE t (a, b)",
        "INSERT INTO t VALUES (NULL, NULL), (NULL, NULL), (1, 'x'), (1.0, 'x'), ('1', 'x')",
    )
    pair.check("SELECT DISTINCT a, b FROM t")
    pair.check("SELECT COUNT(DISTINCT a) FROM t")


def test_alias_in_where(emp):
    emp.check("SELECT salary * 2 AS dbl FROM emp WHERE dbl > 150")
