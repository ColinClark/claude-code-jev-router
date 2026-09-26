"""Differential tests for statements: DDL/DML, affinity, SELECT features, joins, aggregates."""

from __future__ import annotations

import pytest

from minisql import Database
from tests.conftest import Diff

# ----------------------------------------------------------------------------
# CREATE / INSERT / UPDATE / DELETE and column affinity
# ----------------------------------------------------------------------------


def test_create_insert_select_star(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (a INTEGER, b REAL, c TEXT)", "INSERT INTO t VALUES (1, 2.5, 'x')")
    assert diff.run("SELECT * FROM t") == [(1, 2.5, "x")]
    assert diff.db.execute("INSERT INTO t VALUES (2, 3.5, 'y')") == []
    assert diff.db.execute("CREATE TABLE u (a INTEGER)") == []


def test_insert_multiple_rows_and_column_list(diff: Diff) -> None:
    diff.setup(
        "CREATE TABLE t (a INTEGER, b REAL, c TEXT)",
        "INSERT INTO t (c, a) VALUES ('x', 1), ('y', 2)",
        "INSERT INTO t (b) VALUES (9.5)",
        "INSERT INTO t VALUES (3, 4, 'z'), (NULL, NULL, NULL)",
        "insert into t (A, C) values (4, 'upper')",
    )
    diff.run("SELECT * FROM t ORDER BY a")
    diff.run("SELECT a, b, c FROM t WHERE b IS NULL ORDER BY a")


def test_insert_expressions(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (a INTEGER, b REAL, c TEXT)",
               "INSERT INTO t VALUES (1 + 1, -2.5 * 2, 'a' || 'b'), (-3, 1 / 4, NULL)")
    diff.run("SELECT * FROM t ORDER BY a")


@pytest.mark.parametrize(
    "literal",
    ["1", "1.0", "'2'", "'2.0'", "'2.5'", "'1e3'", "' 7 '", "'abc'", "''", "'0x10'", "3.5",
     "1e20", "'9223372036854775808'", "'12abc'", "-0.0", "'-0.0'", "' '", "'+5'", "'.5'", "'5.'",
     "NULL", "-1", "2.0 * 2", "'3' + 1", "1 = 1", "'1.5e1'", "' 1.5 '", "'1 2'", "'1e400'",
     "1e400", "'-9223372036854775808'", "'9223372036854775807'", "'0'", "0.5"],
)
def test_column_affinity_on_insert(diff: Diff, literal: str) -> None:
    diff.setup("CREATE TABLE t (i INTEGER, r REAL, s TEXT, n, num NUMERIC, v VARCHAR(10))")
    values = ", ".join([literal] * 6)
    diff.run(f"INSERT INTO t VALUES ({values})")
    diff.run("SELECT i, typeof(i), r, typeof(r), s, typeof(s), n, typeof(n), num, typeof(num),"
             " v, typeof(v) FROM t")


def test_affinity_on_update(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (i INTEGER, r REAL, s TEXT)", "INSERT INTO t VALUES (1, 1, 1)")
    diff.run("UPDATE t SET i = 2.0, r = 3, s = 1.5")
    diff.run("SELECT i, typeof(i), r, typeof(r), s, typeof(s) FROM t")
    diff.run("UPDATE t SET i = '7', r = '2.5', s = 42")
    diff.run("SELECT i, typeof(i), r, typeof(r), s, typeof(s) FROM t")
    diff.run("UPDATE t SET i = 'x', r = 'y', s = NULL")
    diff.run("SELECT i, typeof(i), r, typeof(r), s, typeof(s) FROM t")


def test_update_uses_old_row_for_all_set_expressions(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (a INTEGER, b INTEGER)", "INSERT INTO t VALUES (1, 10), (2, 20)")
    diff.run("UPDATE t SET a = b, b = a")
    diff.run("SELECT * FROM t ORDER BY a")
    diff.run("UPDATE t SET a = a + 100 WHERE b = 2")
    diff.run("SELECT * FROM t ORDER BY a")
    diff.run("UPDATE t SET a = NULL WHERE a > 100")
    diff.run("SELECT * FROM t ORDER BY a")
    diff.run("UPDATE t SET a = 0 WHERE a IS NULL")
    diff.run("SELECT * FROM t ORDER BY a")
    diff.run("UPDATE t SET b = -b WHERE b")
    diff.run("SELECT * FROM t ORDER BY a")


def test_update_where_null_condition_matches_nothing(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (a INTEGER)", "INSERT INTO t VALUES (1), (NULL)")
    diff.run("UPDATE t SET a = 5 WHERE a = NULL")
    diff.run("UPDATE t SET a = 6 WHERE NULL")
    diff.run("SELECT * FROM t")
    diff.run("UPDATE t SET a = 7 WHERE t.a IS NULL")
    diff.run("SELECT * FROM t")


def test_delete(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (a INTEGER, s TEXT)",
               "INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, NULL), (NULL, 'd')")
    diff.run("DELETE FROM t WHERE a = 2")
    diff.run("SELECT * FROM t")
    diff.run("DELETE FROM t WHERE a > 1")
    diff.run("SELECT * FROM t")
    diff.run("DELETE FROM t WHERE s IS NULL OR a IS NULL")
    diff.run("SELECT * FROM t")
    diff.run("DELETE FROM t")
    diff.run("SELECT * FROM t")
    diff.run("SELECT COUNT(*) FROM t")


def test_tables_are_case_insensitive(diff: Diff) -> None:
    diff.setup("CREATE TABLE Items (Id INTEGER, Name TEXT)",
               "INSERT INTO items (ID, NAME) VALUES (1, 'x')")
    diff.run("SELECT id, ITEMS.name, iTeMs.* FROM ITEMS")
    diff.run("UPDATE ITEMS SET NAME = 'y' WHERE ID = 1")
    diff.run("SELECT * FROM items")
    diff.run("DELETE FROM iTEMS WHERE nAME = 'y'")
    diff.run("SELECT COUNT(*) FROM items")


# ----------------------------------------------------------------------------
# SELECT: projection, WHERE, aliases, DISTINCT, LIMIT/OFFSET
# ----------------------------------------------------------------------------


def test_projection_and_aliases(people: Diff) -> None:
    people.run("SELECT name, age + 1 AS next_age, score * 2 doubled FROM people ORDER BY id")
    people.run("SELECT people.name, people.age FROM people ORDER BY people.id")
    people.run("SELECT p.name, p.age FROM people p ORDER BY p.id")
    people.run("SELECT p.name FROM people AS p ORDER BY id")
    people.run("SELECT *, id FROM people ORDER BY id")
    people.run("SELECT people.* FROM people ORDER BY id")
    people.run("SELECT p.*, p.id * 2 FROM people p ORDER BY 1")
    people.run("SELECT 1, 'const', NULL, id FROM people ORDER BY id")


def test_where_clauses(people: Diff) -> None:
    people.run("SELECT id FROM people WHERE age > 26")
    people.run("SELECT id FROM people WHERE age >= 25 AND score < 80")
    people.run("SELECT id FROM people WHERE age = 25 OR dept = 'ops'")
    people.run("SELECT id FROM people WHERE NOT age = 25")
    people.run("SELECT id FROM people WHERE age IS NULL")
    people.run("SELECT id FROM people WHERE age IS NOT NULL AND dept IS NULL")
    people.run("SELECT id FROM people WHERE name LIKE 'a%'")
    people.run("SELECT id FROM people WHERE name LIKE '%E'")
    people.run("SELECT id FROM people WHERE name NOT LIKE '%a%'")
    people.run("SELECT id FROM people WHERE name LIKE '_l%'")
    people.run("SELECT id FROM people WHERE age IN (25, 41)")
    people.run("SELECT id FROM people WHERE age NOT IN (25, 41)")
    people.run("SELECT id FROM people WHERE age NOT IN (25, NULL)")
    people.run("SELECT id FROM people WHERE age IN (25, NULL)")
    people.run("SELECT id FROM people WHERE dept IN ('eng', 'hr')")
    people.run("SELECT id FROM people WHERE age BETWEEN 25 AND 30")
    people.run("SELECT id FROM people WHERE age NOT BETWEEN 25 AND 30")
    people.run("SELECT id FROM people WHERE score BETWEEN 70 AND 90 OR score IS NULL")
    people.run("SELECT id FROM people WHERE age")
    people.run("SELECT id FROM people WHERE age - 25")
    people.run("SELECT id FROM people WHERE score / 0 IS NULL")
    people.run("SELECT id FROM people WHERE 1")
    people.run("SELECT id FROM people WHERE 0")
    people.run("SELECT id FROM people WHERE NULL")
    people.run("SELECT id FROM people WHERE 'yes'")
    people.run("SELECT id FROM people WHERE age = 25 AND dept = 'eng' OR id = 6")
    people.run("SELECT id FROM people WHERE age = 25 AND (dept = 'eng' OR id = 6)")
    people.run("SELECT id FROM people WHERE age % 2 = 0")
    people.run("SELECT id FROM people WHERE name || dept = 'Aliceeng'")
    people.run("SELECT id FROM people WHERE id IN (1 + 1, 3 * 1)")


def test_comparison_affinity_with_columns(people: Diff) -> None:
    people.setup("CREATE TABLE t (i INTEGER, r REAL, s TEXT, n)",
                 "INSERT INTO t VALUES (5, 1.0, '5', 5), (7, 2.5, 'abc', '7'),"
                 " (NULL, NULL, NULL, NULL), (1, 1.0, '10', 1.0), (10, 10.0, '10', '10')")
    people.run("SELECT i = '5', i = '5abc', i < '5abc', r = '1', s = 5, s = '5', s > 3, s < 3,"
               " i = ' 5 ', i = '5.0', i + 0 = '5', (i) = '5', +i = '5', n = '7', n = 7"
               " FROM t ORDER BY i")
    people.run("SELECT s IN (5, 10), i IN ('5', '7'), r IN ('1', 2.5), n IN (7, '5'),"
               " i IN (5.0), s IN (10), i NOT IN ('5'), s NOT IN (5) FROM t ORDER BY i")
    people.run("SELECT i BETWEEN '1' AND '10', s BETWEEN 1 AND 9, r BETWEEN '0' AND '2',"
               " i BETWEEN r AND s FROM t ORDER BY i")
    people.run("SELECT i IS '5', i IS NOT '5', s IS 5, s IS NOT 10, r IS 1 FROM t ORDER BY i")
    people.run("SELECT i < s, s > i, r < s, i = r, i = n, s = n, i < 'a', s < 'a', s = i || ''"
               " FROM t ORDER BY i")
    people.run("SELECT s LIKE '1%', i LIKE '%5', r LIKE '1%', n LIKE '%', i LIKE '5'"
               " FROM t ORDER BY i")
    people.run("SELECT i FROM t WHERE i = '5'")
    people.run("SELECT i FROM t WHERE s = 10")
    people.run("SELECT i FROM t WHERE r > '1'")
    people.run("SELECT i FROM t WHERE i > 'a'")
    people.run("SELECT i FROM t WHERE i < 'a'")
    people.run("SELECT i, s FROM t WHERE i = s")
    people.run("SELECT i, r FROM t WHERE i = r")
    people.run("SELECT i FROM t WHERE i IN ('5', '7', 'x')")
    people.run("SELECT i FROM t WHERE '5' = i")
    people.run("SELECT i FROM t WHERE 5 = s")
    people.run("SELECT i FROM t WHERE i * 1 = '5'")
    people.run("SELECT i FROM t WHERE i + 1 > '5'")


def test_distinct(people: Diff) -> None:
    people.run("SELECT DISTINCT dept FROM people")
    people.run("SELECT DISTINCT age FROM people")
    people.run("SELECT DISTINCT age, dept FROM people")
    people.run("SELECT DISTINCT score FROM people ORDER BY score")
    people.run("SELECT DISTINCT age FROM people ORDER BY age DESC")
    people.run("SELECT DISTINCT 1 FROM people")
    people.run("SELECT DISTINCT age > 26 FROM people")
    people.run("SELECT DISTINCT dept FROM people WHERE dept IS NOT NULL ORDER BY dept")
    people.setup("CREATE TABLE m (v)",
                 "INSERT INTO m VALUES (1), (1.0), ('1'), (NULL), (NULL), (2), (2.0), ('a'), ('A')")
    people.run("SELECT DISTINCT v FROM m")
    people.run("SELECT DISTINCT typeof(v) FROM m")
    people.run("SELECT COUNT(DISTINCT v) FROM m")
    people.run("SELECT v, COUNT(*) FROM m GROUP BY v ORDER BY v")


def test_limit_offset(people: Diff) -> None:
    people.run("SELECT id FROM people ORDER BY id LIMIT 3")
    people.run("SELECT id FROM people ORDER BY id LIMIT 3 OFFSET 2")
    people.run("SELECT id FROM people ORDER BY id LIMIT 0")
    people.run("SELECT id FROM people ORDER BY id LIMIT 100")
    people.run("SELECT id FROM people ORDER BY id LIMIT 100 OFFSET 5")
    people.run("SELECT id FROM people ORDER BY id LIMIT 2 OFFSET 100")
    people.run("SELECT id FROM people ORDER BY id LIMIT -1")
    people.run("SELECT id FROM people ORDER BY id LIMIT -1 OFFSET 2")
    people.run("SELECT id FROM people ORDER BY id LIMIT 1 + 1 OFFSET 1 * 2")
    people.run("SELECT id FROM people ORDER BY id DESC LIMIT 2, 3")
    people.run("SELECT id FROM people ORDER BY id LIMIT 2 OFFSET -1")
    assert len(people.run("SELECT id FROM people LIMIT 2", ordered=False)) == 2
    people.run("SELECT DISTINCT age FROM people ORDER BY age LIMIT 2 OFFSET 1")
    people.run("SELECT dept, COUNT(*) FROM people GROUP BY dept ORDER BY 2 DESC, 1 LIMIT 2")


# ----------------------------------------------------------------------------
# ORDER BY
# ----------------------------------------------------------------------------


def test_order_by_nulls_and_directions(people: Diff) -> None:
    people.run("SELECT id, age FROM people ORDER BY age")
    people.run("SELECT id, age FROM people ORDER BY age ASC, id")
    people.run("SELECT id, age FROM people ORDER BY age DESC, id")
    people.run("SELECT id, age FROM people ORDER BY age DESC, id DESC")
    people.run("SELECT id, age, score FROM people ORDER BY age, score DESC, id")
    people.run("SELECT id, age, score FROM people ORDER BY age DESC, score, id DESC")
    people.run("SELECT id, dept, name FROM people ORDER BY dept, name")
    people.run("SELECT id, dept, name FROM people ORDER BY dept DESC, name DESC")
    people.run("SELECT id FROM people ORDER BY name")
    people.run("SELECT id FROM people ORDER BY score DESC")


def test_order_by_mixed_types(diff: Diff) -> None:
    diff.setup("CREATE TABLE m (id INTEGER, v)",
               "INSERT INTO m VALUES (1, 3), (2, 'b'), (3, NULL), (4, 2.5), (5, 'B'), (6, ''),"
               " (7, -1), (8, 'a'), (9, 10), (10, '10'), (11, NULL), (12, 2), (13, 'é'), (14, 'z')")
    diff.run("SELECT id, v FROM m ORDER BY v, id")
    diff.run("SELECT id, v FROM m ORDER BY v DESC, id")
    diff.run("SELECT id, v FROM m ORDER BY v DESC, id DESC")
    diff.run("SELECT v FROM m ORDER BY typeof(v), v")


def test_order_by_expressions_aliases_positions(people: Diff) -> None:
    people.run("SELECT id, age * -1 AS neg FROM people ORDER BY neg, id")
    people.run("SELECT id, age * -1 AS neg FROM people ORDER BY neg DESC, id")
    people.run("SELECT id, age FROM people ORDER BY age * -1, id")
    people.run("SELECT id, name FROM people ORDER BY 2, 1")
    people.run("SELECT id, name FROM people ORDER BY 2 DESC, 1 DESC")
    people.run("SELECT name, id FROM people ORDER BY 2 DESC")
    people.run("SELECT id, score FROM people ORDER BY score IS NULL, score DESC, id")
    people.run("SELECT id FROM people ORDER BY age IS NULL DESC, age, id")
    people.run("SELECT id, name FROM people ORDER BY name LIKE 'a%' DESC, id")
    people.run("SELECT id, name FROM people ORDER BY length(name), name")
    people.run("SELECT id AS k FROM people ORDER BY k DESC")
    people.run("SELECT age AS id, id AS age FROM people ORDER BY id, age")
    people.run("SELECT age + 0 AS age FROM people ORDER BY age, id")
    people.run("SELECT id, id + 1 AS id2 FROM people ORDER BY id2 DESC")
    people.run("SELECT id FROM people ORDER BY people.age, people.id")
    people.run("SELECT p.id FROM people p ORDER BY p.age DESC, p.id")
    people.run("SELECT id FROM people ORDER BY age + score, id")
    people.run("SELECT id FROM people ORDER BY 1 + 1, id")
    people.run("SELECT dept, COUNT(*) AS n FROM people GROUP BY dept ORDER BY n DESC, dept")
    people.run("SELECT dept, COUNT(*) FROM people GROUP BY dept ORDER BY COUNT(*) DESC, dept")
    people.run("SELECT dept, COUNT(*) FROM people GROUP BY dept ORDER BY 2 DESC, 1 DESC")
    people.run("SELECT dept FROM people GROUP BY dept ORDER BY SUM(age) DESC, dept")
    people.run("SELECT dept, MAX(score) AS m FROM people GROUP BY dept ORDER BY m, dept")
    people.run("SELECT dept, AVG(age) FROM people GROUP BY dept ORDER BY AVG(age) IS NULL, 2, 1")
    people.run("SELECT DISTINCT age FROM people ORDER BY age")
    people.run("SELECT DISTINCT dept, age FROM people ORDER BY dept DESC, age")


def test_order_by_is_stable_for_multi_key(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (a INTEGER, b INTEGER, c INTEGER)")
    values = ", ".join(f"({i % 3}, {i % 4}, {i})" for i in range(40))
    diff.setup(f"INSERT INTO t VALUES {values}")
    diff.run("SELECT * FROM t ORDER BY a, b, c")
    diff.run("SELECT * FROM t ORDER BY a DESC, b, c DESC")
    diff.run("SELECT * FROM t ORDER BY b, a DESC, c")
    diff.run("SELECT * FROM t ORDER BY a % 2, b DESC, c")


# ----------------------------------------------------------------------------
# Aggregates and GROUP BY / HAVING
# ----------------------------------------------------------------------------


def test_aggregates_without_group_by(people: Diff) -> None:
    people.run("SELECT COUNT(*), COUNT(age), COUNT(score), COUNT(dept), COUNT(DISTINCT age),"
               " COUNT(DISTINCT dept), COUNT(NULL), COUNT(1) FROM people")
    people.run("SELECT SUM(age), SUM(score), AVG(age), AVG(score), MIN(age), MAX(age),"
               " MIN(score), MAX(score), MIN(name), MAX(name), MIN(dept), MAX(dept) FROM people")
    people.run("SELECT SUM(age) + SUM(score), SUM(age) * 1.0, AVG(age) * COUNT(*),"
               " MAX(age) - MIN(age), COUNT(*) || ' rows', typeof(SUM(age)), typeof(SUM(score)),"
               " typeof(AVG(age)), typeof(COUNT(*)) FROM people")
    people.run("SELECT SUM(age * 2), AVG(age + score), MAX(age * score), MIN(score / age),"
               " COUNT(age + score), SUM(age) / COUNT(age), SUM(score) / COUNT(*) FROM people")
    people.run("SELECT SUM(age) FROM people WHERE age > 30")
    people.run("SELECT sum(AGE), Count(*), MIN(Name) FROM people")
    people.run("SELECT COUNT(*) FROM people WHERE dept = 'eng' AND age > 26")
    people.run("SELECT MAX(age), MIN(age) FROM people WHERE dept = 'ops'")
    people.run("SELECT COUNT(DISTINCT age), COUNT(DISTINCT score), COUNT(DISTINCT name) FROM"
               " people")
    people.run("SELECT SUM(DISTINCT age), AVG(DISTINCT age), MIN(DISTINCT age) FROM people")


def test_aggregates_on_empty_and_all_null(diff: Diff) -> None:
    diff.setup("CREATE TABLE e (a INTEGER, r REAL, s TEXT)")
    diff.run("SELECT COUNT(*), COUNT(a), SUM(a), SUM(r), AVG(a), MIN(a), MAX(a), MIN(s), MAX(s),"
             " COUNT(DISTINCT a) FROM e")
    diff.run("SELECT COUNT(*) FROM e WHERE a > 1")
    diff.run("SELECT a, COUNT(*) FROM e")
    diff.run("SELECT a, COUNT(*) FROM e GROUP BY a")
    diff.run("SELECT COUNT(*) FROM e GROUP BY a")
    diff.run("SELECT SUM(a) FROM e HAVING COUNT(*) > 0")
    diff.run("SELECT SUM(a) FROM e HAVING COUNT(*) = 0")
    diff.setup("INSERT INTO e VALUES (NULL, NULL, NULL), (NULL, NULL, NULL)")
    diff.run("SELECT COUNT(*), COUNT(a), SUM(a), SUM(r), AVG(a), MIN(a), MAX(a), MIN(s), MAX(s),"
             " COUNT(DISTINCT a) FROM e")
    diff.run("SELECT a, COUNT(*) FROM e GROUP BY a")
    diff.run("SELECT typeof(SUM(a)), typeof(AVG(a)), typeof(COUNT(a)) FROM e")


def test_aggregate_result_types(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (i INTEGER, r REAL, s TEXT, n)",
               "INSERT INTO t VALUES (1, 1.5, '5', 1), (2, 2.5, 'abc', 2.5), (3, NULL, '10', '7'),"
               " (NULL, 0.25, NULL, NULL), (4, 4.0, '2.5', 'x')")
    diff.run("SELECT SUM(i), SUM(r), SUM(s), SUM(n), AVG(i), AVG(r), AVG(s), AVG(n) FROM t")
    diff.run("SELECT MIN(i), MAX(i), MIN(r), MAX(r), MIN(s), MAX(s), MIN(n), MAX(n) FROM t")
    diff.run("SELECT typeof(SUM(i)), typeof(SUM(r)), typeof(SUM(s)), typeof(AVG(i)),"
             " typeof(MIN(n)), typeof(MAX(n)) FROM t")
    diff.run("SELECT COUNT(DISTINCT n), COUNT(DISTINCT i), COUNT(DISTINCT s) FROM t")
    diff.run("SELECT SUM(i + r), SUM(i * 2), SUM(i / 2), SUM(i / 2.0), AVG(i / 2) FROM t")
    diff.run("SELECT SUM(i) FROM t WHERE r > 1")
    diff.run("SELECT SUM(i) FROM t WHERE i IS NULL")
    diff.run("SELECT MAX(i) - MIN(r), MIN(s) || MAX(s) FROM t")


def test_group_by_and_having(people: Diff) -> None:
    people.run("SELECT dept, COUNT(*) FROM people GROUP BY dept")
    people.run("SELECT dept, COUNT(*), SUM(age), AVG(score), MIN(name), MAX(name) FROM people"
               " GROUP BY dept ORDER BY dept")
    people.run("SELECT age, COUNT(*) FROM people GROUP BY age ORDER BY age")
    people.run("SELECT dept, age, COUNT(*) FROM people GROUP BY dept, age ORDER BY dept, age")
    people.run("SELECT age, dept, COUNT(*) FROM people GROUP BY dept, age ORDER BY 1, 2")
    people.run("SELECT dept, COUNT(*) FROM people GROUP BY dept HAVING COUNT(*) > 1 ORDER BY dept")
    people.run("SELECT dept, COUNT(*) FROM people GROUP BY dept HAVING COUNT(*) > 1 AND dept IS"
               " NOT NULL")
    people.run("SELECT dept, SUM(age) FROM people GROUP BY dept HAVING SUM(age) >= 55 ORDER BY"
               " dept")
    people.run("SELECT dept, AVG(score) FROM people GROUP BY dept HAVING AVG(score) > 80 ORDER"
               " BY dept")
    people.run("SELECT dept FROM people GROUP BY dept HAVING dept IS NULL")
    people.run("SELECT dept FROM people GROUP BY dept HAVING MAX(age) IS NULL")
    people.run("SELECT dept, COUNT(*) AS n FROM people GROUP BY dept HAVING n >= 2 ORDER BY n,"
               " dept")
    people.run("SELECT dept AS d, COUNT(*) FROM people GROUP BY d ORDER BY d")
    people.run("SELECT dept, COUNT(*) FROM people GROUP BY 1 ORDER BY 1")
    people.run("SELECT age > 26 AS senior, COUNT(*) FROM people GROUP BY senior ORDER BY senior")
    people.run("SELECT age > 26, COUNT(*) FROM people GROUP BY age > 26 ORDER BY 1")
    people.run("SELECT age % 2, COUNT(*), SUM(score) FROM people GROUP BY age % 2 ORDER BY 1")
    people.run("SELECT dept, COUNT(*) FROM people WHERE age IS NOT NULL GROUP BY dept ORDER BY"
               " dept")
    people.run("SELECT dept || '!' AS tag, COUNT(*) FROM people GROUP BY dept || '!' ORDER BY tag")
    people.run("SELECT COUNT(*) FROM people GROUP BY dept ORDER BY 1")
    people.run("SELECT COUNT(*), COUNT(DISTINCT age) FROM people GROUP BY dept ORDER BY 1, 2")
    people.run("SELECT dept, MIN(age), MAX(age), MAX(age) - MIN(age) FROM people GROUP BY dept"
               " ORDER BY dept")
    people.run("SELECT dept, COUNT(*) FROM people GROUP BY dept HAVING COUNT(*) > 100")
    people.run("SELECT dept FROM people GROUP BY dept HAVING NULL")
    people.run("SELECT dept FROM people GROUP BY dept HAVING 1 ORDER BY dept")
    people.run("SELECT COUNT(*) FROM people HAVING COUNT(*) > 3")
    people.run("SELECT COUNT(*) FROM people HAVING COUNT(*) > 30")
    people.run("SELECT p.dept, COUNT(p.id) FROM people p GROUP BY p.dept ORDER BY p.dept")
    people.run("SELECT dept, SUM(score) FROM people GROUP BY dept HAVING SUM(score) IS NULL")
    people.run("SELECT dept, MAX(score) FROM people GROUP BY dept HAVING MAX(score) > MIN(score)"
               " ORDER BY dept")


def test_group_by_null_and_numeric_equivalence(diff: Diff) -> None:
    diff.setup("CREATE TABLE g (k, v INTEGER)",
               "INSERT INTO g VALUES (1, 1), (1.0, 2), ('1', 3), (NULL, 4), (NULL, 5), (2, 6),"
               " ('a', 7), ('A', 8), (2.0, 9)")
    diff.run("SELECT k, COUNT(*), SUM(v) FROM g GROUP BY k ORDER BY k")
    diff.run("SELECT typeof(k), COUNT(*) FROM g GROUP BY typeof(k) ORDER BY 1")
    diff.run("SELECT COUNT(DISTINCT k), COUNT(k), COUNT(*) FROM g")
    diff.run("SELECT DISTINCT k FROM g")
    diff.run("SELECT k, v FROM g GROUP BY k ORDER BY k")


def test_bare_columns_in_aggregate_queries(diff: Diff) -> None:
    diff.setup("CREATE TABLE u (id INTEGER, g TEXT, v INTEGER)",
               "INSERT INTO u VALUES (1,'a',10),(2,'a',30),(3,'b',30),(4,'b',20),(5,'a',30),"
               "(6,'b',5)")
    diff.run("SELECT id, MAX(v) FROM u")
    diff.run("SELECT id, MIN(v) FROM u")
    diff.run("SELECT id, MAX(v), COUNT(*) FROM u")
    diff.run("SELECT id, MAX(v) + 1 FROM u")
    diff.run("SELECT id, g, MAX(v) FROM u GROUP BY g ORDER BY g")
    diff.run("SELECT id, g, MIN(v) FROM u GROUP BY g ORDER BY g")
    diff.run("SELECT id, COUNT(*) FROM u")
    diff.run("SELECT id, SUM(v) FROM u")
    diff.run("SELECT g, id, COUNT(*) FROM u GROUP BY g ORDER BY g")
    diff.run("SELECT id, v, COUNT(*) FROM u GROUP BY g ORDER BY g")
    diff.run("SELECT id FROM u GROUP BY g ORDER BY g")
    diff.run("SELECT id, MAX(v) FROM u WHERE v < 0")
    diff.run("SELECT id, g FROM u GROUP BY g HAVING MAX(v) > 25 ORDER BY g")
    diff.run("SELECT g, id FROM u GROUP BY g ORDER BY MAX(v), g")
    diff.run("SELECT * FROM u GROUP BY g ORDER BY g")
    diff.run("SELECT g, MAX(v), id FROM u GROUP BY g HAVING COUNT(*) > 0 ORDER BY 3")


# ----------------------------------------------------------------------------
# Joins
# ----------------------------------------------------------------------------


def test_inner_joins(people: Diff) -> None:
    people.run("SELECT people.name, depts.title FROM people JOIN depts ON people.dept = depts.code"
               " ORDER BY people.id")
    people.run("SELECT p.name, d.title FROM people p INNER JOIN depts d ON p.dept = d.code"
               " ORDER BY p.id")
    people.run("SELECT p.name, d.title FROM people AS p JOIN depts AS d ON p.dept = d.code"
               " ORDER BY p.id")
    people.run("SELECT * FROM people JOIN depts ON people.dept = depts.code ORDER BY people.id")
    people.run("SELECT p.*, d.floor FROM people p JOIN depts d ON p.dept = d.code ORDER BY p.id")
    people.run("SELECT d.*, p.id FROM people p JOIN depts d ON p.dept = d.code ORDER BY p.id")
    people.run("SELECT name, title, floor FROM people JOIN depts ON dept = code ORDER BY id")
    people.run("SELECT name, badge FROM people JOIN badges ON id = person_id ORDER BY id, badge")
    people.run("SELECT p.name, d.title, b.badge FROM people p JOIN depts d ON p.dept = d.code"
               " JOIN badges b ON b.person_id = p.id ORDER BY p.id, b.badge")
    people.run("SELECT COUNT(*) FROM people JOIN depts ON people.dept = depts.code")
    people.run("SELECT COUNT(*) FROM people JOIN depts")
    people.run("SELECT COUNT(*) FROM people, depts")
    people.run("SELECT COUNT(*) FROM people CROSS JOIN depts")
    people.run("SELECT a.id, b.id FROM people a JOIN people b ON a.age = b.age AND a.id < b.id"
               " ORDER BY 1, 2")
    people.run("SELECT a.id, b.id FROM people a JOIN people b ON a.id = b.id - 1 ORDER BY 1")
    people.run("SELECT a.name, b.name FROM people a JOIN people b ON a.dept = b.dept"
               " WHERE a.id <> b.id ORDER BY a.id, b.id")
    people.run("SELECT d.title, COUNT(*), SUM(p.age) FROM people p JOIN depts d ON p.dept = d.code"
               " GROUP BY d.title ORDER BY d.title")
    people.run("SELECT p.id FROM people p JOIN depts d ON p.dept = d.code WHERE d.floor > 1"
               " ORDER BY p.id")
    people.run("SELECT p.id FROM people p JOIN depts d ON p.dept = d.code AND d.floor > 1"
               " ORDER BY p.id")
    people.run("SELECT p.id FROM people p JOIN depts d ON 1 ORDER BY p.id, d.code")
    people.run("SELECT p.id FROM people p JOIN depts d ON NULL")
    people.run("SELECT p.id, d.code FROM people p JOIN depts d ON p.age > d.floor * 10"
               " ORDER BY p.id, d.code")


def test_left_joins(people: Diff) -> None:
    people.run("SELECT p.name, d.title FROM people p LEFT JOIN depts d ON p.dept = d.code"
               " ORDER BY p.id")
    people.run("SELECT p.name, d.title FROM people p LEFT OUTER JOIN depts d ON p.dept = d.code"
               " ORDER BY p.id")
    people.run("SELECT * FROM people p LEFT JOIN depts d ON p.dept = d.code ORDER BY p.id")
    people.run("SELECT p.id FROM people p LEFT JOIN depts d ON p.dept = d.code WHERE d.code IS NULL"
               " ORDER BY p.id")
    people.run("SELECT p.id, d.floor FROM people p LEFT JOIN depts d ON p.dept = d.code"
               " WHERE d.floor IS NULL OR d.floor > 1 ORDER BY p.id")
    people.run("SELECT p.id, b.badge FROM people p LEFT JOIN badges b ON b.person_id = p.id"
               " ORDER BY p.id, b.badge")
    people.run("SELECT p.id, d.title, b.badge FROM people p LEFT JOIN depts d ON p.dept = d.code"
               " LEFT JOIN badges b ON b.person_id = p.id ORDER BY p.id, b.badge")
    people.run("SELECT d.code, p.id FROM depts d LEFT JOIN people p ON p.dept = d.code"
               " ORDER BY d.code, p.id")
    people.run("SELECT d.code, COUNT(p.id), COUNT(*) FROM depts d LEFT JOIN people p"
               " ON p.dept = d.code GROUP BY d.code ORDER BY d.code")
    people.run("SELECT d.code, SUM(p.age), AVG(p.score), MAX(p.name) FROM depts d"
               " LEFT JOIN people p ON p.dept = d.code GROUP BY d.code ORDER BY d.code")
    people.run("SELECT p.id, d.title FROM people p LEFT JOIN depts d ON p.dept = d.code"
               " AND d.floor > 1 ORDER BY p.id")
    people.run("SELECT p.id, d.title FROM people p LEFT JOIN depts d ON 0 ORDER BY p.id")
    people.run("SELECT p.id, d.title FROM people p LEFT JOIN depts d ON NULL ORDER BY p.id")
    people.run("SELECT p.id, d.code, b.badge FROM people p LEFT JOIN depts d ON p.dept = d.code"
               " LEFT JOIN badges b ON b.badge = d.title ORDER BY p.id")
    people.run("SELECT b.badge, p.name, d.title FROM badges b LEFT JOIN people p"
               " ON p.id = b.person_id LEFT JOIN depts d ON d.code = p.dept ORDER BY b.badge, p.id")
    people.run("SELECT b.badge, p.name, d.title FROM badges b LEFT JOIN people p"
               " ON p.id = b.person_id JOIN depts d ON d.code = p.dept ORDER BY b.badge, p.id")
    people.run("SELECT COUNT(*) FROM people p LEFT JOIN badges b ON b.person_id = p.id")
    people.run("SELECT a.id, b.id, c.id FROM people a LEFT JOIN people b ON b.id = a.id + 10"
               " LEFT JOIN people c ON c.id = b.id + 1 ORDER BY a.id")
    people.run("SELECT a.id, b.id, c.id FROM people a LEFT JOIN people b ON b.id = a.id + 1"
               " LEFT JOIN people c ON c.id = b.id + 1 ORDER BY a.id")


def test_join_scope_and_aliases(people: Diff) -> None:
    people.run("SELECT id, code FROM people JOIN depts ON dept = code ORDER BY id")
    people.run("SELECT p.id FROM people p JOIN depts ON p.dept = code ORDER BY 1")
    people.run("SELECT people.id FROM people JOIN depts d ON people.dept = d.code ORDER BY 1")
    people.run("SELECT x.id, y.id FROM people x, people y WHERE x.id = y.id ORDER BY x.id")
    people.run("SELECT x.id, y.id FROM people x JOIN people y ON x.id = y.id ORDER BY x.id")
    people.run("SELECT x.*, y.name FROM people x JOIN people y ON x.id = y.id ORDER BY x.id")
    people.run("SELECT x.name FROM people x JOIN people y ON x.id = y.id WHERE y.age > 26"
               " ORDER BY x.name")


# ----------------------------------------------------------------------------
# Database API
# ----------------------------------------------------------------------------


def test_api_return_types() -> None:
    db = Database()
    assert db.execute("CREATE TABLE t (a INTEGER, b TEXT)") == []
    assert db.execute("INSERT INTO t VALUES (1, 'x'), (2, 'y');") == []
    rows = db.execute("SELECT * FROM t ORDER BY a")
    assert rows == [(1, "x"), (2, "y")]
    assert all(type(r) is tuple for r in rows)
    assert db.execute("UPDATE t SET b = 'z' WHERE a = 1") == []
    assert db.execute("DELETE FROM t WHERE a = 2") == []
    assert db.execute("SELECT * FROM t") == [(1, "z")]
    assert db.execute("  SELECT 1 ;  ") == [(1,)]
    assert db.execute("SELECT 1 -- comment") == [(1,)]
    assert db.execute("SELECT /* block */ 2") == [(2,)]


def test_databases_are_independent() -> None:
    a = Database()
    b = Database()
    a.execute("CREATE TABLE t (x INTEGER)")
    a.execute("INSERT INTO t VALUES (1)")
    b.execute("CREATE TABLE t (x INTEGER)")
    assert a.execute("SELECT COUNT(*) FROM t") == [(1,)]
    assert b.execute("SELECT COUNT(*) FROM t") == [(0,)]


def test_result_rows_do_not_alias_storage() -> None:
    db = Database()
    db.execute("CREATE TABLE t (x INTEGER)")
    db.execute("INSERT INTO t VALUES (1)")
    before = db.execute("SELECT * FROM t")
    db.execute("UPDATE t SET x = 2")
    assert before == [(1,)]
    assert db.execute("SELECT * FROM t") == [(2,)]


def test_create_table_with_constraints_and_other_type_names(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (id INT PRIMARY KEY, name VARCHAR(20) NOT NULL, amount DOUBLE,"
               " flag BOOLEAN, data BLOB, note CHARACTER VARYING(5), f FLOAT DEFAULT 1.5)",
               "INSERT INTO t VALUES (1.0, 5, '2', '3', 4, 5.5, '6')")
    diff.run("SELECT id, typeof(id), name, typeof(name), amount, typeof(amount), flag,"
             " typeof(flag), data, typeof(data), note, typeof(note), f, typeof(f) FROM t")


# ----------------------------------------------------------------------------
# SQLite quirks discovered by the randomized differential tests
# ----------------------------------------------------------------------------


def test_empty_in_list_is_a_boolean_constant(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (id INTEGER, name TEXT)", "INSERT INTO t VALUES (1, 'a'), (2, NULL)")
    diff.run("SELECT 1 IN () + 1, typeof(1 NOT IN ()), 1 NOT IN () || 'x', -(1 IN ()), NULL IN ()")
    diff.run("SELECT id, name IN (), name NOT IN (), (name IN ()) IS 0, NOT (name IN ()) FROM t")
    diff.run("SELECT id FROM t WHERE '00' IS NOT (name IN ())")
    diff.run("SELECT id FROM t WHERE 1 IS NOT (name IN ())")
    diff.run("SELECT id FROM t WHERE name IN () IS 0")


def test_is_true_false_boolean_tests(diff: Diff) -> None:
    diff.run("SELECT NULL IS TRUE, NULL IS NOT TRUE, NULL IS FALSE, NULL IS NOT FALSE")
    diff.run("SELECT 'a' IS TRUE, 'a' IS FALSE, '00' IS NOT FALSE, 0.5 IS TRUE, 2 IS TRUE,"
             " '1' IS TRUE, 0.0 IS FALSE, -1 IS TRUE")
    diff.run("SELECT 1 IS TRUE = 1, 'a' IS (2 IN ()), 'a' IS (2 NOT IN ()), 'a' IS TRUE IS TRUE")
    diff.run("SELECT TRUE, FALSE, typeof(TRUE), TRUE + 1, TRUE = 1, NOT TRUE, 1 IS TRUE + 1")


def test_grammar_edge_cases(diff: Diff) -> None:
    diff.run("SELECT 5 BETWEEN 1 = 1 AND 10, 5 BETWEEN NOT 1 AND 10, 5 BETWEEN 1 AND 2 = 0")
    diff.run("SELECT 1 IN (1) + 1, 1 IN (1) * 2 + 3, 2 * 1 IN (1) * 3, 1 IN (1) || 'x',"
             " 1 IN (1) < 2")
    diff.run("SELECT 1 IS NULL * 2, 1 IS NOT NULL * 2, NULL IS NULL * 2, 1 IS NULL || 'x'")
    diff.run("SELECT 1 = NOT 2 = 3, 1 + NOT 1 AND 0, - NOT 1, NOT - 1, 1 * NOT 2 * 3")
    diff.run("SELECT 'a' LIKE 'A' LIKE 1, 1 LIKE 1 * 2, 1 IN (1) IN (1),"
             " 5 BETWEEN 1 AND 10 BETWEEN 0 AND 1")
    diff.run("SELECT 1 IN (1) IS 1, 1 IS 1 IN (1), 1 IS NULL IN (0), 1 IS NOT 1 LIKE 0,"
             " -1 IN (-1), - 1 IN (1)")
    diff.run("SELECT NULL IS NOT NULL IS NULL, NOT NULL IS NULL, 1 NOT IN (2) NOT IN (0)")
    diff.run("SELECT 'x' NOT LIKE 'y' NOT LIKE 1, 1 IS NOT 2 IS NOT 1, 3 - 2 BETWEEN 1 AND 1")
    diff.run("SELECT -9223372036854775808, typeof(-9223372036854775808), -(-9223372036854775808)")
    diff.run("SELECT 9223372036854775808, typeof(9223372036854775808), - -5, -(-5), +-5")


def test_positional_terms_fold_unary_signs(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (a INTEGER, b INTEGER)", "INSERT INTO t VALUES (1, 2), (3, 1)")
    diff.run("SELECT a, b FROM t ORDER BY -(-2), 1")
    diff.run("SELECT a, b FROM t ORDER BY +2 DESC")
    diff.run("SELECT a, COUNT(*) FROM t GROUP BY -(-1) ORDER BY 1")
    diff.run("SELECT a, b FROM t ORDER BY 2.0, a")
    diff.error("SELECT a FROM t ORDER BY -1")
    diff.error("SELECT a FROM t ORDER BY -(-2)")
    diff.error("SELECT a, COUNT(*) FROM t GROUP BY 2")
    diff.error("SELECT a, COUNT(*) FROM t GROUP BY -(-2)")
    diff.error("SELECT a FROM t GROUP BY 0")


def test_alias_resolution_rules(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (a INTEGER, b TEXT)", "INSERT INTO t VALUES (1, 'x'), (2, '5')",
               "CREATE TABLE u (a INTEGER, c TEXT)", "INSERT INTO u VALUES (1, 'y')")
    diff.run("SELECT a AS x FROM t WHERE x = 1")
    diff.run("SELECT a + 1 AS a FROM t WHERE a = 2 ORDER BY a")
    diff.run("SELECT t.a AS a FROM t JOIN u ON 1 ORDER BY a")
    diff.run("SELECT t.a AS z FROM t JOIN u ON 1 GROUP BY z")
    diff.run("SELECT a AS x FROM t GROUP BY x HAVING x = 1")
    diff.run("SELECT b AS x FROM t ORDER BY x")
    diff.run("SELECT a AS b, b AS a FROM t ORDER BY a, b")
    diff.run("SELECT a AS b, b AS a FROM t WHERE a = 1")
    diff.error("SELECT a AS x FROM t WHERE t.x = 1")
    diff.error("SELECT t.a FROM t JOIN u ON 1 ORDER BY a")
    diff.error("SELECT t.a FROM t JOIN u ON 1 GROUP BY a")
    diff.error("SELECT t.a FROM t JOIN u ON 1 WHERE a = 1")
    diff.error("SELECT a FROM t x ORDER BY t.a")


def test_left_join_without_on(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (a INTEGER)", "INSERT INTO t VALUES (1), (2)",
               "CREATE TABLE u (b INTEGER)", "INSERT INTO u VALUES (10), (20)")
    diff.run("SELECT * FROM t LEFT JOIN u ORDER BY a, b")
    diff.run("SELECT COUNT(*) FROM t LEFT JOIN u")
    diff.run("SELECT * FROM t JOIN u ORDER BY a, b")
    diff.run("SELECT * FROM t LEFT JOIN u LEFT JOIN t AS v ORDER BY 1, 2, 3")


def test_blob_affinity_column_comparisons(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (a INTEGER, b TEXT, n)",
               "INSERT INTO t VALUES (1, 'x', 5), (2, '5', NULL), (5, '5', '5'), (7, '7', 7.0)")
    diff.run("SELECT b = n, b < n, n = b, b IN (n), n IN (b), n = 5, n = '5', b = 5, a = n, n = a,"
             " n = 1.0, typeof(n), n IS b, n BETWEEN b AND b, n LIKE b FROM t ORDER BY a")
    diff.run("SELECT a FROM t WHERE n = '5'")
    diff.run("SELECT a FROM t WHERE n = 5")
    diff.run("SELECT a FROM t WHERE n = b")
    diff.run("SELECT a FROM t WHERE n = a")
    diff.run("SELECT n FROM t ORDER BY n")


def test_bare_columns_follow_last_min_max(diff: Diff) -> None:
    diff.setup("CREATE TABLE t1 (id INTEGER, a INTEGER, b REAL, c TEXT)",
               "INSERT INTO t1 VALUES (1, 5, 1.5, 'abc'), (2, -3, 0.0, 'ABC'),"
               " (3, NULL, 2.25, 'b')",
               "CREATE TABLE n (id INTEGER, v)",
               "INSERT INTO n VALUES (1, NULL), (2, NULL), (3, 5), (4, NULL), (5, 7), (6, 7)")
    diff.run("SELECT id, b, MIN(b), MIN(a), MAX(b) FROM t1")
    diff.run("SELECT id, b, MIN(a), MIN(b) FROM t1")
    diff.run("SELECT id, b, MIN(a), MAX(a) FROM t1 GROUP BY 1 = 1 ORDER BY MIN(b)")
    diff.run("SELECT id, b, MIN(a), MAX(a) FROM t1 HAVING MIN(b) < 1")
    diff.run("SELECT id, b, MIN(a) FROM t1 HAVING MAX(b) > 1")
    diff.run("SELECT id, b, COUNT(*) FROM t1 ORDER BY MAX(b)")
    diff.run("SELECT id, MIN(a) FROM t1 HAVING MAX(b) > 0 ORDER BY MIN(b)")
    diff.run("SELECT id, MIN(a) FROM t1 ORDER BY MIN(b) DESC")
    diff.run("SELECT id, MAX(a), MIN(b), MAX(a) FROM t1")
    diff.run("SELECT id, MIN(b), MAX(a), MIN(b) FROM t1")
    diff.run("SELECT id, MAX(a) + MIN(b) FROM t1")
    diff.run("SELECT id, MIN(b) + MAX(a) FROM t1")
    diff.run("SELECT id, MAX(a) FROM t1 GROUP BY 1 = 1 HAVING MIN(b) < 1")
    diff.run("SELECT id, COUNT(*) FROM t1 ORDER BY MIN(b), MAX(b)")
    diff.run("SELECT id, COUNT(*) FROM t1 ORDER BY MAX(b), MIN(b)")
    diff.run("SELECT id, c, MAX(b) FROM t1 GROUP BY 1 = 1 ORDER BY MIN(b)")
    diff.run("SELECT id, MAX(v) FROM n")
    diff.run("SELECT id, MIN(v) FROM n")
    diff.run("SELECT id, MAX(v) FROM n WHERE id < 3")
    diff.run("SELECT id, COUNT(v) FROM n WHERE id < 3")
    diff.run("SELECT id, MAX(v), MIN(v) FROM n")
    diff.run("SELECT id, v FROM n GROUP BY v IS NULL ORDER BY 2")


def test_sum_uses_compensated_float_summation(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (x REAL, i INTEGER, s TEXT)")
    values = ", ".join(f"({v}, {k}, '{v}')" for k, v in enumerate(
        ["0.1", "0.2", "0.3", "1e16", "1.0", "-1e16", "0.7", "3.3", "1e-10", "2.2", "0.1"] * 3))
    diff.setup(f"INSERT INTO t VALUES {values}")
    diff.run("SELECT SUM(x), AVG(x), SUM(x * 3), AVG(x / 7), SUM(x + i), SUM(s), AVG(s) FROM t")
    diff.run("SELECT SUM(i), AVG(i), SUM(i * 1.0), SUM(i / 3.0), typeof(SUM(i)), typeof(SUM(s))"
             " FROM t")
    diff.run("SELECT SUM(x) FROM t WHERE i % 2 = 0")
    diff.setup("CREATE TABLE m (v)",
               "INSERT INTO m VALUES ('5'), ('10'), (2), ('2.5'), ('abc'), ('3x')")
    diff.run("SELECT SUM(v), typeof(SUM(v)), AVG(v) FROM m")
    diff.run("SELECT SUM(v), typeof(SUM(v)) FROM m WHERE v IN ('5', '10', 2)")
    diff.run("SELECT SUM(v), typeof(SUM(v)) FROM m WHERE v = '2.5'")


def test_and_with_false_literal_folds_at_parse_time(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (id INTEGER, a INTEGER)", "INSERT INTO t VALUES (1, 5), (2, NULL)")
    diff.run("SELECT 0 AND id, id AND 0, id AND FALSE, 'b' AND 0, NULL AND 0, 0.0 AND id FROM t"
             " ORDER BY id")
    diff.run("SELECT 0 AND nope, (0 AND nope) + 1, 1 AND (nope IN ())")
    diff.run("SELECT id FROM t WHERE 1 AND NOT (0 AND nope) ORDER BY id")
    diff.error("SELECT id, a, COUNT(*) FROM t GROUP BY 0 AND id")
    diff.error("SELECT id FROM t ORDER BY a AND (id IN ())")
    diff.run("SELECT id, a, COUNT(*) FROM t GROUP BY 1 AND id ORDER BY id")
    diff.run("SELECT id FROM t ORDER BY 0.0 AND id, id")
    diff.error("SELECT 1 AND nope")
    diff.error("SELECT 0 OR nope")


def test_negation_and_negative_zero(diff: Diff) -> None:
    diff.setup("CREATE TABLE t (r REAL, n, i INTEGER, s TEXT)",
               "INSERT INTO t VALUES (-0.0, -0.0, -0.0, -0.0), (0.0, 0.0, 0, '0'),"
               " (-(0.0), -(0.0), 1, 'x')",
               "INSERT INTO t (r, n) VALUES (1e20, 1e20), (-2.5, -2.5), (2.0, 2.0),"
               " (-0.0 * 1, -0.0 * 1)")
    diff.run("SELECT -0.0 || '', -(0.0) || '', -(1 - 1.0) || '', 0.0 * -1 || '', typeof(-0.0)")
    diff.run("SELECT r || '', n || '', i, s, typeof(r), typeof(n), typeof(i), typeof(s) FROM t"
             " ORDER BY r, n, i, s")
    diff.run("SELECT DISTINCT r || '' FROM t")
    diff.run("SELECT DISTINCT n || '' FROM t")
    diff.run("SELECT -r || '', -n || '', -(-r) || '', -'3abc', -'', -(-9223372036854775808) FROM t"
             " ORDER BY r, n")
    diff.run("SELECT -(-5), -(+5), +(-5), -(5.5), -(-0.0) || '', - - 1, -(1 IN (1))")
