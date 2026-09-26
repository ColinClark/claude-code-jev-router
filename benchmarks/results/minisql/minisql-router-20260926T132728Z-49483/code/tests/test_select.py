"""SELECT execution tests, differential against Python's sqlite3 where possible."""

import sqlite3

import pytest

from minisql import Database, SQLError

SCHEMA = [
    "CREATE TABLE emp (id INTEGER, name TEXT, dept_id INTEGER, salary REAL, manager_id INTEGER)",
    "CREATE TABLE dept (id INTEGER, name TEXT, loc_id INTEGER)",
    "CREATE TABLE loc (id INTEGER, city TEXT)",
    "CREATE TABLE empty (x INTEGER, y TEXT)",
    "CREATE TABLE m (a, b)",
    "CREATE TABLE nums (n INTEGER, f REAL, t TEXT, g TEXT)",
    (
        "INSERT INTO emp VALUES "
        "(1, 'alice', 10, 100.0, NULL), (2, 'bob', 10, 80, 1), (3, 'carol', 20, 120.5, 1), "
        "(4, 'dave', 20, NULL, 3), (5, 'eve', NULL, 60, 3), (6, 'frank', 30, 90, 1), "
        "(7, 'grace', 10, 80, 2)"
    ),
    "INSERT INTO dept VALUES (10, 'eng', 1), (20, 'sales', 2), (30, 'ops', NULL), (40, 'hr', 1)",
    "INSERT INTO loc VALUES (1, 'NYC'), (2, 'SF'), (3, 'LA')",
    (
        "INSERT INTO m VALUES (1, 'x'), (1.0, 'y'), ('1', 'z'), (NULL, 'w'), (NULL, NULL), "
        "(2.5, 'x'), ('abc', 'y'), (-3, NULL)"
    ),
    (
        "INSERT INTO nums VALUES (1, 1.5, '3', 'a'), (2, NULL, 'x', 'a'), (NULL, NULL, NULL, 'b'), "
        "(4, 2.5, '1.5', 'b'), (5, -1.0, NULL, 'c'), (2, 0.5, '2', NULL)"
    ),
]


@pytest.fixture(scope="module")
def dbs():
    db = Database()
    conn = sqlite3.connect(":memory:")
    for sql in SCHEMA:
        db.execute(sql)
        conn.execute(sql)
    return db, conn


def typed(rows):
    return [tuple((type(v).__name__, v) for v in r) for r in rows]


def check(dbs, sql):
    db, conn = dbs
    expected = conn.execute(sql).fetchall()
    got = db.execute(sql)
    assert isinstance(got, list) and all(isinstance(r, tuple) for r in got)
    assert typed(got) == typed(expected), sql
    return got


# ---------------------------------------------------------------------------
# Select list
# ---------------------------------------------------------------------------

SELECT_LIST = [
    "SELECT * FROM emp",
    "SELECT * FROM dept",
    "SELECT e.* FROM emp e",
    "SELECT emp.* FROM emp",
    "SELECT d.*, e.name FROM emp e JOIN dept d ON e.dept_id = d.id ORDER BY e.id",
    "SELECT e.name, d.* FROM emp AS e, dept AS d WHERE e.dept_id = d.id ORDER BY e.id",
    "SELECT *, id * 2 FROM loc",
    "SELECT id, name FROM emp",
    "SELECT name AS n, salary * 2 AS double_pay FROM emp",
    "SELECT name n, salary + 1 FROM emp",
    "SELECT id + 1, upper(name), length(name) || '!' FROM emp",
    "SELECT 1, 'two', 3.0, NULL",
    "SELECT 1 + 1 AS two, 'a' || 'b'",
    "SELECT EMP.NAME, Emp.Id FROM emp",
    "SELECT typeof(a), a, b FROM m",
    "SELECT CASE WHEN salary > 90 THEN 'high' WHEN salary IS NULL THEN 'none' ELSE 'low' END FROM emp",
    "SELECT * FROM empty",
    "SELECT x, y FROM empty",
]


@pytest.mark.parametrize("sql", SELECT_LIST)
def test_select_list(dbs, sql):
    check(dbs, sql)


def test_select_star_expansion_order(dbs):
    db, _ = dbs
    rows = db.execute("SELECT l.*, d.* FROM dept d JOIN loc l ON d.loc_id = l.id ORDER BY d.id")
    assert rows == [(1, "NYC", 10, "eng", 1), (2, "SF", 20, "sales", 2), (1, "NYC", 40, "hr", 1)]


# ---------------------------------------------------------------------------
# WHERE + expressions end-to-end
# ---------------------------------------------------------------------------

WHERE = [
    "SELECT name FROM emp WHERE salary > 85",
    "SELECT name FROM emp WHERE salary > 85 OR dept_id IS NULL",
    "SELECT name FROM emp WHERE NOT (salary > 85)",
    "SELECT name FROM emp WHERE salary IS NULL",
    "SELECT name FROM emp WHERE dept_id IN (10, 30)",
    "SELECT name FROM emp WHERE dept_id NOT IN (10, NULL)",
    "SELECT name FROM emp WHERE salary BETWEEN 80 AND 100",
    "SELECT name FROM emp WHERE name LIKE '%a%' AND salary >= 90",
    "SELECT name FROM emp WHERE name GLOB '[a-c]*'",
    "SELECT name FROM emp WHERE manager_id = 1 AND (dept_id = 10 OR salary > 100)",
    "SELECT name FROM emp WHERE coalesce(salary, 0) < 70",
    "SELECT name FROM emp WHERE salary / 3 > 30",
    "SELECT name FROM emp WHERE id % 2 = 0",
    "SELECT name FROM emp WHERE dept_id = '10'",
    "SELECT name FROM emp WHERE name = 'ALICE'",
    "SELECT name FROM emp WHERE upper(name) = 'ALICE'",
    "SELECT name FROM emp WHERE CASE dept_id WHEN 10 THEN 1 ELSE 0 END",
    "SELECT name FROM emp WHERE NULL",
    "SELECT name FROM emp WHERE 1",
    "SELECT name FROM emp WHERE salary",
    "SELECT a, b FROM m WHERE a = 1",
    "SELECT a, b FROM m WHERE a = '1'",
    "SELECT a, b FROM m WHERE a > 1",
    "SELECT a, b FROM m WHERE a IS NOT NULL AND b IS NULL",
    "SELECT t FROM nums WHERE t > 2",
    "SELECT t FROM nums WHERE t = 3",
    "SELECT n FROM nums WHERE n = '2'",
    "SELECT name, salary * 1.1 AS bonus FROM emp WHERE bonus > 100",
    "SELECT 1 WHERE 0",
    "SELECT 1 WHERE 1",
]


@pytest.mark.parametrize("sql", WHERE)
def test_where(dbs, sql):
    check(dbs, sql)


# ---------------------------------------------------------------------------
# Joins
# ---------------------------------------------------------------------------

JOINS = [
    "SELECT e.name, d.name FROM emp e JOIN dept d ON e.dept_id = d.id ORDER BY e.id",
    "SELECT e.name, d.name FROM emp e INNER JOIN dept d ON e.dept_id = d.id ORDER BY e.id",
    "SELECT e.name, d.name FROM emp e LEFT JOIN dept d ON e.dept_id = d.id ORDER BY e.id",
    "SELECT e.name, d.name FROM emp e LEFT OUTER JOIN dept d ON e.dept_id = d.id ORDER BY e.id",
    "SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id ORDER BY d.id, e.id",
    # LEFT JOIN with no matches at all -> everything NULL-extended
    "SELECT d.name, e.* FROM dept d LEFT JOIN emp e ON e.dept_id = d.id AND 0 ORDER BY d.id",
    "SELECT d.name, x.x, x.y FROM dept d LEFT JOIN empty x ON x.x = d.id ORDER BY d.id",
    # LEFT JOIN where a condition on the right side lives in ON vs WHERE
    (
        "SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id AND e.salary > 85 "
        "ORDER BY d.id, e.id"
    ),
    (
        "SELECT d.name, e.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id WHERE e.salary > 85 "
        "ORDER BY d.id, e.id"
    ),
    "SELECT d.name FROM dept d LEFT JOIN emp e ON e.dept_id = d.id WHERE e.id IS NULL",
    # ON clauses touching NULLs
    "SELECT d.name, l.city FROM dept d LEFT JOIN loc l ON d.loc_id = l.id ORDER BY d.id",
    "SELECT d.name, l.city FROM dept d JOIN loc l ON d.loc_id = l.id ORDER BY d.id",
    "SELECT a.name, b.name FROM emp a JOIN emp b ON a.manager_id = b.id ORDER BY a.id",
    "SELECT a.name, b.name FROM emp a LEFT JOIN emp b ON a.manager_id = b.id ORDER BY a.id",
    (
        "SELECT a.name, b.name FROM emp a JOIN emp b ON a.salary = b.salary AND a.id < b.id "
        "ORDER BY a.id, b.id"
    ),
    (
        "SELECT a.name, b.name FROM emp a LEFT JOIN emp b ON a.salary IS b.salary AND a.id <> b.id "
        "ORDER BY a.id, b.id"
    ),
    "SELECT x.a, y.a FROM m x JOIN m y ON x.a = y.a ORDER BY x.b, y.b",
    "SELECT x.b, y.b FROM m x LEFT JOIN m y ON x.a IS NULL AND y.a IS NULL ORDER BY x.b, y.b",
    # comma / CROSS joins
    "SELECT e.name, l.city FROM emp e, loc l ORDER BY e.id, l.id",
    "SELECT e.name, l.city FROM emp e CROSS JOIN loc l ORDER BY e.id, l.id",
    "SELECT e.name, d.name FROM emp e, dept d WHERE e.dept_id = d.id ORDER BY e.id",
    "SELECT count(*) FROM emp, dept, loc",
    "SELECT * FROM empty, loc",
    "SELECT * FROM loc, empty",
    # multiple joins
    (
        "SELECT e.name, d.name, l.city FROM emp e JOIN dept d ON e.dept_id = d.id "
        "JOIN loc l ON d.loc_id = l.id ORDER BY e.id"
    ),
    (
        "SELECT e.name, d.name, l.city FROM emp e LEFT JOIN dept d ON e.dept_id = d.id "
        "LEFT JOIN loc l ON d.loc_id = l.id ORDER BY e.id"
    ),
    (
        "SELECT e.name, d.name, l.city FROM emp e JOIN dept d ON e.dept_id = d.id "
        "LEFT JOIN loc l ON d.loc_id = l.id ORDER BY e.id"
    ),
    (
        "SELECT l.city, d.name, e.name FROM loc l LEFT JOIN dept d ON d.loc_id = l.id "
        "LEFT JOIN emp e ON e.dept_id = d.id ORDER BY l.id, d.id, e.id"
    ),
    (
        "SELECT e.name, m2.name, d.name FROM emp e LEFT JOIN emp m2 ON e.manager_id = m2.id "
        "JOIN dept d ON d.id = e.dept_id, loc l WHERE l.id = d.loc_id ORDER BY e.id"
    ),
    # unqualified column that is unique across joined tables
    "SELECT city, name FROM loc JOIN dept ON loc_id = loc.id ORDER BY dept.id",
    # same table joined twice under aliases
    "SELECT a.id, b.id FROM loc a JOIN loc b ON a.id < b.id ORDER BY a.id, b.id",
]


@pytest.mark.parametrize("sql", JOINS)
def test_joins(dbs, sql):
    check(dbs, sql)


def test_left_join_null_extension_explicit():
    db = Database()
    db.execute("CREATE TABLE l (k INTEGER, v TEXT)")
    db.execute("CREATE TABLE r (k INTEGER, w TEXT)")
    db.execute("INSERT INTO l VALUES (1, 'a'), (2, 'b'), (NULL, 'c')")
    db.execute("INSERT INTO r VALUES (1, 'x'), (NULL, 'y')")
    assert db.execute("SELECT l.v, r.k, r.w FROM l LEFT JOIN r ON l.k = r.k") == [
        ("a", 1, "x"),
        ("b", None, None),
        ("c", None, None),
    ]
    assert db.execute("SELECT l.v, r.* FROM l LEFT JOIN r ON l.k = r.k WHERE r.w IS NULL") == [
        ("b", None, None),
        ("c", None, None),
    ]
    # inner join: NULL keys never match
    assert db.execute("SELECT l.v, r.w FROM l JOIN r ON l.k = r.k") == [("a", "x")]
    # IS matches NULL with NULL
    assert db.execute("SELECT l.v, r.w FROM l JOIN r ON l.k IS r.k") == [("a", "x"), ("c", "y")]


# ---------------------------------------------------------------------------
# Aggregates and GROUP BY
# ---------------------------------------------------------------------------

AGGREGATES = [
    (
        "SELECT count(*), count(salary), count(dept_id), sum(salary), avg(salary), min(salary), "
        "max(salary) FROM emp"
    ),
    "SELECT sum(id), avg(id), total(id), min(name), max(name) FROM emp",
    "SELECT count(DISTINCT dept_id), count(DISTINCT salary), count(DISTINCT manager_id) FROM emp",
    "SELECT sum(DISTINCT salary), avg(DISTINCT salary) FROM emp",
    "SELECT count(DISTINCT a), count(a), count(*) FROM m",
    "SELECT min(a), max(a), sum(a), avg(a), total(a) FROM m",
    "SELECT sum(n), avg(n), sum(f), avg(f), sum(t), avg(t), total(t) FROM nums",
    "SELECT group_concat(name), group_concat(name, '-') FROM emp",
    "SELECT group_concat(DISTINCT dept_id) FROM emp",
    # empty input
    "SELECT count(*), count(x), sum(x), avg(x), min(x), max(x), total(x) FROM empty",
    "SELECT count(*), sum(salary), avg(salary), min(salary), max(salary) FROM emp WHERE 0",
    "SELECT count(DISTINCT x), group_concat(y) FROM empty",
    # all-NULL input
    (
        "SELECT count(*), count(salary), sum(salary), avg(salary), min(salary), max(salary) "
        "FROM emp WHERE salary IS NULL"
    ),
    "SELECT count(DISTINCT salary) FROM emp WHERE salary IS NULL",
    # aggregates inside expressions
    "SELECT sum(salary) / count(salary), max(salary) - min(salary), count(*) * 2 + 1 FROM emp",
    "SELECT round(avg(salary), 2), coalesce(sum(x), 0) FROM emp, empty",
    "SELECT coalesce(max(x), -1) FROM empty",
    "SELECT sum(salary * 2), avg(id + 0.5), count(salary > 80) FROM emp",
    "SELECT count(*) FROM emp WHERE dept_id = 10",
    # GROUP BY
    "SELECT dept_id, count(*) FROM emp GROUP BY dept_id",
    (
        "SELECT dept_id, count(*), sum(salary), avg(salary), min(salary), max(salary) FROM emp "
        "GROUP BY dept_id"
    ),
    (
        "SELECT dept_id, count(salary), sum(salary), avg(salary) FROM emp GROUP BY dept_id "
        "ORDER BY dept_id"
    ),
    "SELECT a, count(*), group_concat(b) FROM m GROUP BY a",
    "SELECT b, count(*), count(a) FROM m GROUP BY b",
    "SELECT dept_id, manager_id, count(*) FROM emp GROUP BY dept_id, manager_id",
    "SELECT dept_id % 20, count(*) FROM emp GROUP BY dept_id % 20",
    "SELECT dept_id, count(*) FROM emp GROUP BY 1",
    "SELECT dept_id AS d, count(*) FROM emp GROUP BY d",
    "SELECT count(*) FROM emp GROUP BY dept_id",
    "SELECT dept_id, count(DISTINCT salary), count(DISTINCT manager_id) FROM emp GROUP BY dept_id",
    (
        "SELECT d.name, count(e.id), sum(e.salary) FROM dept d LEFT JOIN emp e ON e.dept_id = d.id "
        "GROUP BY d.name"
    ),
    (
        "SELECT d.id, count(*), count(e.id), avg(e.salary) FROM dept d LEFT JOIN emp e "
        "ON e.dept_id = d.id GROUP BY d.id"
    ),
    (
        "SELECT l.city, count(DISTINCT d.id), count(e.id) FROM loc l LEFT JOIN dept d ON d.loc_id = l.id "
        "LEFT JOIN emp e ON e.dept_id = d.id GROUP BY l.city"
    ),
    "SELECT g, sum(n), avg(f), max(t) FROM nums GROUP BY g",
    "SELECT dept_id, count(*) FROM emp WHERE salary > 70 GROUP BY dept_id",
    "SELECT x, count(*) FROM empty GROUP BY x",
    # bare columns in aggregate queries (SQLite's documented min/max rule)
    "SELECT name, max(salary) FROM emp",
    "SELECT name, min(salary) FROM emp",
    "SELECT dept_id, name, max(salary) FROM emp GROUP BY dept_id",
    # HAVING
    "SELECT dept_id, count(*) FROM emp GROUP BY dept_id HAVING count(*) > 1",
    "SELECT dept_id, count(*) AS c FROM emp GROUP BY dept_id HAVING c >= 2",
    "SELECT dept_id, sum(salary) FROM emp GROUP BY dept_id HAVING sum(salary) > 150",
    "SELECT dept_id FROM emp GROUP BY dept_id HAVING max(salary) - min(salary) > 10",
    "SELECT dept_id, count(*) FROM emp GROUP BY dept_id HAVING dept_id IS NOT NULL",
    "SELECT dept_id, avg(salary) FROM emp GROUP BY dept_id HAVING avg(salary) IS NULL",
    "SELECT dept_id FROM emp GROUP BY dept_id HAVING 0",
    "SELECT count(*) FROM emp HAVING count(*) > 3",
    "SELECT count(*) FROM emp HAVING count(*) > 100",
    "SELECT count(*) FROM empty HAVING count(*) = 0",
]


@pytest.mark.parametrize("sql", AGGREGATES)
def test_aggregates(dbs, sql):
    check(dbs, sql)


def test_aggregate_result_types():
    db = Database()
    db.execute("CREATE TABLE t (i INTEGER, r REAL)")
    db.execute("INSERT INTO t VALUES (1, 1.0), (2, 2.0), (4, NULL)")
    ((s, a, c, mn, mx, t),) = db.execute("SELECT sum(i), avg(i), count(i), min(i), max(r), total(i) FROM t")
    assert (s, type(s)) == (7, int)
    assert type(a) is float and a == pytest.approx(7 / 3)
    assert (c, mn, mx) == (3, 1, 2.0) and type(mx) is float
    assert (t, type(t)) == (7.0, float)
    assert db.execute("SELECT sum(r) FROM t") == [(3.0,)]
    assert db.execute("SELECT sum(i), avg(i) FROM t WHERE i > 100") == [(None, None)]
    assert db.execute("SELECT count(*), count(DISTINCT i) FROM t WHERE i > 100") == [(0, 0)]
    assert db.execute("SELECT total(i) FROM t WHERE i > 100") == [(0.0,)]


def test_sum_integer_overflow():
    db = Database()
    db.execute("CREATE TABLE t (i INTEGER)")
    db.execute("INSERT INTO t VALUES (9223372036854775807), (1)")
    with pytest.raises(SQLError):
        db.execute("SELECT sum(i) FROM t")
    assert db.execute("SELECT total(i) FROM t") == [(9.223372036854776e18,)]


def test_count_distinct_ignores_nulls_and_duplicates():
    db = Database()
    db.execute("CREATE TABLE t (v)")
    db.execute("INSERT INTO t VALUES (1), (1), (1.0), (NULL), (NULL), ('1'), ('a'), ('a')")
    assert db.execute("SELECT count(DISTINCT v), count(v), count(*) FROM t") == [(3, 6, 8)]


def test_group_by_nulls_form_one_group():
    db = Database()
    db.execute("CREATE TABLE t (k, v INTEGER)")
    db.execute("INSERT INTO t VALUES (NULL, 1), ('a', 2), (NULL, 3), ('a', 4), (1, 5), (1.0, 6)")
    assert db.execute("SELECT k, sum(v) FROM t GROUP BY k ORDER BY k") == [
        (None, 4),
        (1, 11),
        ("a", 6),
    ]


# ---------------------------------------------------------------------------
# ORDER BY
# ---------------------------------------------------------------------------

ORDER_BY = [
    "SELECT name, salary FROM emp ORDER BY salary",
    "SELECT name, salary FROM emp ORDER BY salary DESC",
    "SELECT name, salary FROM emp ORDER BY salary ASC, name DESC",
    "SELECT name, salary FROM emp ORDER BY salary DESC, name",
    "SELECT name, dept_id FROM emp ORDER BY dept_id, name",
    "SELECT name, dept_id FROM emp ORDER BY dept_id DESC, name DESC",
    "SELECT name AS n FROM emp ORDER BY n",
    "SELECT name AS n FROM emp ORDER BY n DESC",
    "SELECT name, salary AS s FROM emp ORDER BY s DESC, 1",
    "SELECT name, salary FROM emp ORDER BY 2, 1",
    "SELECT name, salary FROM emp ORDER BY 2 DESC, 1 DESC",
    "SELECT * FROM emp ORDER BY 4, 1",
    "SELECT name FROM emp ORDER BY length(name), name",
    "SELECT name FROM emp ORDER BY salary * -1, id",
    "SELECT name FROM emp ORDER BY coalesce(salary, 1000) DESC",
    "SELECT name FROM emp ORDER BY id % 3, id DESC",
    "SELECT name FROM emp ORDER BY dept_id IS NULL, dept_id DESC, id",
    "SELECT id AS a FROM emp ORDER BY -a",
    "SELECT a, b FROM m ORDER BY a, b",
    "SELECT a, b FROM m ORDER BY a DESC, b DESC",
    "SELECT a FROM m ORDER BY b, a",
    "SELECT t FROM nums ORDER BY t",
    "SELECT n, f FROM nums ORDER BY f DESC, n",
    "SELECT name FROM emp ORDER BY 'constant', id",
    # ORDER BY with aggregates
    "SELECT dept_id, count(*) AS c FROM emp GROUP BY dept_id ORDER BY c DESC, dept_id",
    "SELECT dept_id, count(*) FROM emp GROUP BY dept_id ORDER BY 2, 1 DESC",
    "SELECT dept_id, sum(salary) FROM emp GROUP BY dept_id ORDER BY sum(salary) DESC",
    "SELECT dept_id FROM emp GROUP BY dept_id ORDER BY max(salary), dept_id",
    "SELECT dept_id FROM emp GROUP BY dept_id ORDER BY avg(salary) DESC, dept_id",
    "SELECT dept_id, count(*) FROM emp GROUP BY dept_id ORDER BY count(*) * -1, dept_id DESC",
    (
        "SELECT d.name, count(e.id) AS n FROM dept d LEFT JOIN emp e ON e.dept_id = d.id "
        "GROUP BY d.name ORDER BY n DESC, d.name"
    ),
    "SELECT dept_id, count(*) FROM emp GROUP BY dept_id HAVING count(*) > 0 ORDER BY dept_id DESC",
]


@pytest.mark.parametrize("sql", ORDER_BY)
def test_order_by(dbs, sql):
    check(dbs, sql)


def test_order_by_null_placement():
    db = Database()
    db.execute("CREATE TABLE t (v)")
    db.execute("INSERT INTO t VALUES (2), (NULL), ('b'), (1.5), (NULL), ('a')")
    assert db.execute("SELECT v FROM t ORDER BY v") == [(None,), (None,), (1.5,), (2,), ("a",), ("b",)]
    assert db.execute("SELECT v FROM t ORDER BY v DESC") == [
        ("b",), ("a",), (2,), (1.5,), (None,), (None,)
    ]


def test_order_by_alias_shadows_column():
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER, b INTEGER)")
    db.execute("INSERT INTO t VALUES (1, 3), (2, 2), (3, 1)")
    # bare ORDER BY name matches the output alias first, like SQLite
    assert db.execute("SELECT a AS b FROM t ORDER BY b") == [(1,), (2,), (3,)]
    assert db.execute("SELECT a AS b FROM t ORDER BY t.b") == [(3,), (2,), (1,)]


def test_order_by_is_stable_for_ties():
    db = Database()
    db.execute("CREATE TABLE t (k INTEGER, v TEXT)")
    db.execute("INSERT INTO t VALUES (1, 'a'), (0, 'b'), (1, 'c'), (0, 'd')")
    assert db.execute("SELECT v FROM t ORDER BY k") == [("b",), ("d",), ("a",), ("c",)]


# ---------------------------------------------------------------------------
# DISTINCT / LIMIT / OFFSET
# ---------------------------------------------------------------------------

DISTINCT_LIMIT = [
    "SELECT DISTINCT dept_id FROM emp",
    "SELECT DISTINCT dept_id FROM emp ORDER BY dept_id DESC",
    "SELECT DISTINCT salary FROM emp ORDER BY 1",
    "SELECT DISTINCT dept_id, manager_id FROM emp ORDER BY 1, 2",
    "SELECT DISTINCT a FROM m",
    "SELECT DISTINCT b FROM m",
    "SELECT DISTINCT a IS NULL FROM m",
    "SELECT DISTINCT count(*) FROM emp GROUP BY dept_id",
    "SELECT DISTINCT d.loc_id FROM dept d LEFT JOIN emp e ON e.dept_id = d.id ORDER BY 1",
    "SELECT ALL dept_id FROM emp",
    "SELECT name FROM emp LIMIT 3",
    "SELECT name FROM emp LIMIT 3 OFFSET 2",
    "SELECT name FROM emp LIMIT 2, 3",
    "SELECT name FROM emp ORDER BY name DESC LIMIT 2",
    "SELECT name FROM emp ORDER BY name LIMIT 2 OFFSET 5",
    "SELECT name FROM emp LIMIT 0",
    "SELECT name FROM emp LIMIT 10 OFFSET 100",
    "SELECT name FROM emp LIMIT 100",
    "SELECT name FROM emp LIMIT -1 OFFSET 4",
    "SELECT name FROM emp LIMIT 1 + 1",
    "SELECT DISTINCT dept_id FROM emp ORDER BY dept_id LIMIT 2 OFFSET 1",
    "SELECT dept_id, count(*) FROM emp GROUP BY dept_id ORDER BY 2 DESC, 1 LIMIT 2",
    "SELECT count(*) FROM emp LIMIT 0",
    "SELECT * FROM empty LIMIT 5",
]


@pytest.mark.parametrize("sql", DISTINCT_LIMIT)
def test_distinct_limit(dbs, sql):
    check(dbs, sql)


def test_distinct_treats_nulls_equal():
    db = Database()
    db.execute("CREATE TABLE t (a, b)")
    db.execute("INSERT INTO t VALUES (NULL, 1), (NULL, 1), (NULL, NULL), (NULL, NULL), ('1', 1)")
    assert db.execute("SELECT DISTINCT a, b FROM t") == [(None, 1), (None, None), ("1", 1)]


def test_limit_offset_edge_cases(dbs):
    db, _ = dbs
    assert db.execute("SELECT id FROM emp LIMIT 0") == []
    assert db.execute("SELECT id FROM emp LIMIT 5 OFFSET 7") == []
    assert db.execute("SELECT id FROM emp LIMIT 2") == [(1,), (2,)]
    assert db.execute("SELECT id FROM emp ORDER BY id DESC LIMIT 1 OFFSET 1") == [(6,)]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

ERRORS = [
    "SELECT * FROM nope",
    "SELECT nope FROM emp",
    "SELECT emp.nope FROM emp",
    "SELECT x.name FROM emp",
    "SELECT e.name FROM emp",  # table referenced under its alias only when aliased
    "SELECT name FROM emp e JOIN dept d ON e.dept_id = d.id",  # ambiguous
    "SELECT id FROM emp, dept",  # ambiguous
    "SELECT * FROM emp e JOIN dept d ON id = 1",  # ambiguous in ON
    "SELECT * FROM emp JOIN nope ON 1",
    "SELECT * FROM emp e LEFT JOIN dept d ON e.nope = d.id",
    "SELECT name FROM emp WHERE nope = 1",
    "SELECT name FROM emp WHERE count(*) > 1",
    "SELECT name FROM emp GROUP BY count(*)",
    "SELECT name FROM emp GROUP BY nope",
    "SELECT dept_id FROM emp GROUP BY dept_id HAVING nope > 1",
    "SELECT name FROM emp ORDER BY nope",
    "SELECT name FROM emp ORDER BY 2",
    "SELECT name FROM emp ORDER BY 0",
    "SELECT name FROM emp GROUP BY 3",
    "SELECT nope.* FROM emp",
    "SELECT *",
    "SELECT sum(count(*)) FROM emp",
    "SELECT nosuchfn(id) FROM emp",
    "SELECT * FROM empty WHERE nope",  # errors even when the table has no rows
    "SELECT name FROM emp LIMIT 'abc'",
    "SELECT * FROM emp e JOIN emp e ON 1",  # duplicate alias makes e.* ambiguous below
]


@pytest.mark.parametrize("sql", ERRORS)
def test_errors(dbs, sql):
    db, conn = dbs
    if sql == "SELECT * FROM emp e JOIN emp e ON 1":
        sql = "SELECT e.id FROM emp e JOIN emp e ON 1"
    with pytest.raises(SQLError):
        db.execute(sql)
    with pytest.raises(sqlite3.Error):
        conn.execute(sql).fetchall()


def test_ambiguous_column_message():
    db = Database()
    db.execute("CREATE TABLE a (id INTEGER, x INTEGER)")
    db.execute("CREATE TABLE b (id INTEGER, y INTEGER)")
    with pytest.raises(SQLError, match="ambiguous column name: id"):
        db.execute("SELECT id FROM a JOIN b ON a.id = b.id")
    with pytest.raises(SQLError, match="no such table: c"):
        db.execute("SELECT * FROM c")
    with pytest.raises(SQLError, match="no such column: z"):
        db.execute("SELECT z FROM a")
    # qualified references resolve the ambiguity
    db.execute("INSERT INTO a VALUES (1, 10)")
    db.execute("INSERT INTO b VALUES (1, 20)")
    assert db.execute("SELECT a.id, b.id, x, y FROM a JOIN b ON a.id = b.id") == [(1, 1, 10, 20)]


# ---------------------------------------------------------------------------
# End-to-end: DML followed by SELECT
# ---------------------------------------------------------------------------


def test_dml_then_select_matches_sqlite():
    script = [
        "CREATE TABLE inv (sku TEXT, qty INTEGER, price REAL, cat TEXT)",
        "INSERT INTO inv VALUES ('a1', 10, 2.5, 'x'), ('a2', '5', '1.25', 'x'), ('b1', NULL, 3, 'y')",
        "INSERT INTO inv (sku, cat) VALUES ('c1', NULL)",
        "INSERT INTO inv VALUES ('b2', 7, 4.0, 'y'), ('b3', 0, NULL, 'y')",
        "UPDATE inv SET qty = qty * 2 WHERE cat = 'y' AND qty IS NOT NULL",
        "UPDATE inv SET price = price + 0.5 WHERE price < 3",
        "DELETE FROM inv WHERE qty = 0",
    ]
    db = Database()
    conn = sqlite3.connect(":memory:")
    for sql in script:
        db.execute(sql)
        conn.execute(sql)
    queries = [
        "SELECT * FROM inv",
        "SELECT sku, qty * price AS value FROM inv WHERE value IS NOT NULL ORDER BY value DESC",
        "SELECT cat, count(*), sum(qty), total(qty * price), avg(price) FROM inv GROUP BY cat",
        "SELECT cat, sum(qty) s FROM inv GROUP BY cat HAVING s > 10 ORDER BY s",
        "SELECT sku FROM inv WHERE (qty > 5 OR price IS NULL) AND sku LIKE '_1' ORDER BY sku",
        "SELECT DISTINCT cat FROM inv ORDER BY cat DESC LIMIT 2",
        "SELECT typeof(qty), typeof(price), count(*) FROM inv GROUP BY 1, 2 ORDER BY 1, 2",
        (
            "SELECT a.sku, b.sku FROM inv a JOIN inv b ON a.cat = b.cat AND a.sku < b.sku "
            "ORDER BY 1, 2"
        ),
        (
            "SELECT a.sku, count(b.sku) FROM inv a LEFT JOIN inv b ON b.qty > a.qty "
            "GROUP BY a.sku ORDER BY 2 DESC, 1"
        ),
    ]
    for q in queries:
        check((db, conn), q)


def test_select_returns_fresh_list_and_does_not_mutate(dbs):
    db, _ = dbs
    before = list(db.tables["emp"].rows)
    rows = db.execute("SELECT * FROM emp")
    rows.clear()
    assert db.tables["emp"].rows == before
    assert db.execute("SELECT count(*) FROM emp") == [(7,)]
