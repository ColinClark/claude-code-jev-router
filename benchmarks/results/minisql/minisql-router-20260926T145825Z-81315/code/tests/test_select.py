"""SELECT features compared against sqlite3 on a shared fixture dataset."""

import pytest

QUERIES = [
    # projection
    "SELECT * FROM people",
    "SELECT name, age FROM people",
    "SELECT p.* FROM people p",
    "SELECT people.name FROM people",
    "SELECT id * 2 AS doubled, name || '!' AS shout FROM people",
    "SELECT id, id FROM people",
    "SELECT 1, 'x', NULL FROM people",
    "SELECT name nm FROM people",
    "SELECT DISTINCT city FROM people",
    "SELECT DISTINCT age, city FROM people",
    "SELECT DISTINCT score FROM people",
    "SELECT ALL city FROM people",
    # where
    "SELECT name FROM people WHERE age > 25",
    "SELECT name FROM people WHERE age >= 25 AND city = 'Paris'",
    "SELECT name FROM people WHERE city IS NULL OR age IS NULL",
    "SELECT name FROM people WHERE name LIKE 'a%'",
    "SELECT name FROM people WHERE name NOT LIKE '%e'",
    "SELECT name FROM people WHERE age IN (25, 30)",
    "SELECT name FROM people WHERE age NOT IN (25, 30)",
    "SELECT name FROM people WHERE age NOT IN (25, NULL)",
    "SELECT name FROM people WHERE score BETWEEN 50 AND 90",
    "SELECT name FROM people WHERE NOT (age > 25)",
    "SELECT name FROM people WHERE age",
    "SELECT name FROM people WHERE score",
    "SELECT name FROM people WHERE people.id = 3",
    # order by
    "SELECT name, age FROM people ORDER BY age, id",
    "SELECT name, age FROM people ORDER BY age DESC, id",
    "SELECT name, age FROM people ORDER BY age ASC, name DESC, id",
    "SELECT name FROM people ORDER BY name",
    "SELECT name FROM people ORDER BY name DESC",
    "SELECT city, id FROM people ORDER BY city, id DESC",
    "SELECT score, id FROM people ORDER BY score DESC, id",
    "SELECT name AS n, id FROM people ORDER BY n, id",
    "SELECT id, age * -1 AS neg FROM people ORDER BY neg, id",
    "SELECT name, id FROM people ORDER BY 2 DESC",
    "SELECT name, id FROM people ORDER BY 1, 2",
    "SELECT id FROM people ORDER BY age * 2 + id",
    "SELECT id FROM people ORDER BY score IS NULL, score, id",
    "SELECT id FROM people ORDER BY city NULLS LAST, id",
    "SELECT id FROM people ORDER BY city DESC NULLS FIRST, id",
    "SELECT id AS age, age AS id FROM people ORDER BY age",
    "SELECT DISTINCT city FROM people ORDER BY city",
    "SELECT DISTINCT city FROM people ORDER BY city DESC",
    "SELECT id, name FROM people ORDER BY lower(name), id",
    # limit / offset
    "SELECT id FROM people ORDER BY id LIMIT 3",
    "SELECT id FROM people ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT id FROM people ORDER BY id LIMIT 0",
    "SELECT id FROM people ORDER BY id LIMIT -1 OFFSET 5",
    "SELECT id FROM people ORDER BY id LIMIT 100 OFFSET 7",
    "SELECT id FROM people ORDER BY id LIMIT 2, 3",
    "SELECT id FROM people ORDER BY id LIMIT 1 + 1",
    "SELECT id FROM people ORDER BY id DESC LIMIT 2 OFFSET 20",
    # aggregates without group by
    "SELECT COUNT(*) FROM people",
    "SELECT COUNT(age), COUNT(city), COUNT(DISTINCT age), COUNT(DISTINCT city) FROM people",
    "SELECT SUM(age), AVG(age), MIN(age), MAX(age) FROM people",
    "SELECT SUM(score), AVG(score), MIN(score), MAX(score) FROM people",
    "SELECT MIN(name), MAX(name), MIN(city), MAX(city) FROM people",
    "SELECT SUM(DISTINCT age), AVG(DISTINCT age), COUNT(DISTINCT score) FROM people",
    "SELECT COUNT(*), SUM(age), AVG(age), MIN(age), MAX(age) FROM people WHERE age > 100",
    "SELECT COUNT(age), COUNT(DISTINCT age), total(age) FROM people WHERE age > 100",
    "SELECT SUM(age) + 1, COUNT(*) * 2, MAX(age) - MIN(age) FROM people",
    "SELECT SUM(age) / COUNT(age), AVG(age) * 2 FROM people",
    "SELECT COUNT(*) FROM people WHERE city = 'Paris'",
    "SELECT MAX(score), name FROM people",
    "SELECT MIN(age), name, id FROM people",
    "SELECT SUM(id % 2 = 0), SUM(age IS NULL) FROM people",
    "SELECT AVG(id) FROM people",
    "SELECT SUM(qty), SUM(amount), AVG(qty) FROM orders",
    "SELECT COUNT(*) FROM people HAVING COUNT(*) > 3",
    "SELECT COUNT(*) FROM people HAVING COUNT(*) > 30",
    # group by
    "SELECT city, COUNT(*) FROM people GROUP BY city",
    "SELECT city, COUNT(*), AVG(age), SUM(score) FROM people GROUP BY city ORDER BY city",
    "SELECT age, COUNT(*) FROM people GROUP BY age ORDER BY COUNT(*) DESC, age",
    "SELECT city, MAX(age) FROM people GROUP BY city HAVING MAX(age) > 30",
    "SELECT city, COUNT(*) AS c FROM people GROUP BY city HAVING c >= 2 ORDER BY c DESC, city",
    "SELECT city FROM people GROUP BY city HAVING COUNT(*) = 1",
    "SELECT city, COUNT(*) FROM people GROUP BY 1 ORDER BY 1",
    "SELECT lower(city) AS lc, COUNT(*) FROM people GROUP BY lc ORDER BY lc",
    "SELECT age > 28, COUNT(*) FROM people GROUP BY age > 28 ORDER BY 1",
    "SELECT city, age, COUNT(*) FROM people GROUP BY city, age ORDER BY city, age",
    "SELECT city, SUM(age) FROM people WHERE age < 40 GROUP BY city ORDER BY SUM(age), city",
    "SELECT city, MIN(name), MAX(name) FROM people GROUP BY city ORDER BY city",
    "SELECT city, COUNT(DISTINCT age) FROM people GROUP BY city ORDER BY city",
    "SELECT city, AVG(score) FROM people GROUP BY city ORDER BY AVG(score) DESC, city",
    "SELECT COUNT(*) FROM people GROUP BY city ORDER BY 1",
    "SELECT city, COUNT(*) FROM people WHERE age > 100 GROUP BY city",
    "SELECT city, MAX(score), name FROM people GROUP BY city ORDER BY city",
    "SELECT DISTINCT COUNT(*) FROM people GROUP BY city",
    "SELECT city, COUNT(*) FROM people GROUP BY city ORDER BY city LIMIT 2 OFFSET 1",
    "SELECT item, SUM(qty) FROM orders GROUP BY item HAVING SUM(qty) IS NULL OR SUM(qty) > 3",
    "SELECT city, SUM(age) * 1.0 / COUNT(*) FROM people GROUP BY city ORDER BY city",
    # joins
    "SELECT p.name, o.item FROM people p JOIN orders o ON o.person_id = p.id",
    "SELECT p.name, o.item FROM people AS p INNER JOIN orders AS o ON o.person_id = p.id",
    "SELECT people.name, orders.item FROM people JOIN orders ON orders.person_id = people.id",
    "SELECT p.name, o.item FROM people p LEFT JOIN orders o ON o.person_id = p.id",
    "SELECT p.name, o.item FROM people p LEFT OUTER JOIN orders o ON o.person_id = p.id",
    "SELECT p.id, o.id FROM people p LEFT JOIN orders o ON o.person_id = p.id WHERE o.id IS NULL",
    "SELECT p.id, o.id FROM people p LEFT JOIN orders o ON o.person_id = p.id AND o.qty > 2",
    "SELECT p.id, o.id FROM people p LEFT JOIN orders o ON o.person_id = p.id WHERE o.qty > 2",
    "SELECT * FROM people p JOIN orders o ON p.id = o.person_id",
    "SELECT * FROM people p LEFT JOIN orders o ON p.id = o.person_id",
    "SELECT o.*, p.name FROM orders o LEFT JOIN people p ON p.id = o.person_id",
    "SELECT p.name, c.country, o.item FROM people p JOIN cities c ON c.name = p.city "
    "JOIN orders o ON o.person_id = p.id",
    "SELECT p.name, c.country, o.item FROM people p LEFT JOIN cities c ON c.name = p.city "
    "LEFT JOIN orders o ON o.person_id = p.id",
    "SELECT p.name, c.pop FROM people p LEFT JOIN cities c ON lower(c.name) = lower(p.city)",
    "SELECT a.name, b.name FROM people a JOIN people b ON a.age = b.age AND a.id < b.id",
    "SELECT a.id, b.id FROM people a LEFT JOIN people b ON a.city = b.city AND a.id <> b.id",
    "SELECT p.id, o.id FROM people p JOIN orders o ON 1",
    "SELECT p.id, c.name FROM people p CROSS JOIN cities c",
    "SELECT p.id, c.name FROM people p, cities c WHERE p.city = c.name",
    "SELECT name, item FROM people JOIN orders ON person_id = people.id",
    "SELECT p.name, COUNT(o.id), SUM(o.amount) FROM people p LEFT JOIN orders o "
    "ON o.person_id = p.id GROUP BY p.id, p.name ORDER BY p.id",
    "SELECT p.city, COUNT(*) FROM people p JOIN orders o ON o.person_id = p.id "
    "GROUP BY p.city ORDER BY p.city",
    "SELECT c.name, COUNT(p.id) AS n FROM cities c LEFT JOIN people p ON p.city = c.name "
    "GROUP BY c.name ORDER BY n DESC, c.name",
    "SELECT p.name, o.amount FROM people p JOIN orders o ON o.person_id = p.id "
    "ORDER BY o.amount DESC, p.name LIMIT 3",
    "SELECT DISTINCT p.city FROM people p JOIN orders o ON o.person_id = p.id ORDER BY 1",
    "SELECT p.id, o.id, c.name FROM people p LEFT JOIN orders o ON o.person_id = p.id "
    "LEFT JOIN cities c ON c.name = p.city AND o.qty > 1 ORDER BY p.id, o.id",
    "SELECT o.item, p.name FROM orders o LEFT JOIN people p ON p.id = o.person_id "
    "WHERE p.name IS NULL ORDER BY o.id",
    "SELECT COUNT(*), COUNT(o.id), SUM(o.qty) FROM people p LEFT JOIN orders o "
    "ON o.person_id = p.id",
    # no FROM
    "SELECT 1 + 1, 'a' || 'b'",
    "SELECT COUNT(*), SUM(1), MAX(NULL)",
    # misc
    "SELECT name FROM people WHERE name = 'Alice' AND age = (22)",
    "SELECT UPPER(name), LENGTH(name) FROM people",
    "SELECT CASE WHEN age < 30 THEN 'young' WHEN age >= 30 THEN 'old' ELSE 'n/a' END FROM people",
    "SELECT item FROM orders WHERE item LIKE 'APPLE'",
    "SELECT id, amount / qty, amount % 3, qty / 2, qty % 3 FROM orders",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_select_matches_sqlite(people, sql):
    people.check(sql)


def test_ambiguous_column_raises(people):
    from minisql import SQLError

    with pytest.raises(SQLError):
        people.db.execute("SELECT id FROM people JOIN orders ON person_id = people.id")
    with pytest.raises(SQLError):
        people.db.execute("SELECT name FROM people JOIN cities ON 1")


def test_order_by_alias_and_expression(people):
    people.check("SELECT id, score * 2 AS s FROM people ORDER BY s DESC, id")
    people.check("SELECT id, age FROM people ORDER BY age + id DESC")


def test_update_and_delete_match_sqlite(people):
    people.exec(
        "UPDATE people SET age = age + 1 WHERE city = 'Paris'",
        "UPDATE people SET score = NULL, city = 'Nowhere' WHERE age IS NULL",
        "UPDATE people SET name = upper(name)",
        "UPDATE people SET score = score / 2 WHERE score > 80",
        "DELETE FROM people WHERE age > 34",
        "DELETE FROM orders WHERE amount IS NULL OR qty = 0",
        "UPDATE orders SET qty = '7' WHERE item = 'fig'",
        "UPDATE orders SET amount = 3 WHERE item = 'fig'",
    )
    people.check("SELECT * FROM people ORDER BY id")
    people.check("SELECT * FROM orders ORDER BY id")
    people.exec("DELETE FROM orders")
    people.check("SELECT COUNT(*), SUM(qty) FROM orders")


def test_insert_type_affinity_matches_sqlite(pair):
    pair.exec(
        "CREATE TABLE t (i INTEGER, r REAL, s TEXT)",
        "INSERT INTO t VALUES (1, 1, 1), (2.0, 2.5, 2.5), ('3', '3', '3'), (NULL, NULL, NULL)",
        "INSERT INTO t (s, i) VALUES ('x', 4), (1e20, -5)",
        "INSERT INTO t VALUES (1 + 1, 7 / 2, 'a' || 'b'), (-0.0, 1e-5, 0.5)",
    )
    pair.check("SELECT i, r, s, typeof(i), typeof(r), typeof(s) FROM t")


def test_insert_select(pair):
    pair.exec(
        "CREATE TABLE a (x INTEGER, y TEXT)",
        "INSERT INTO a VALUES (1, 'one'), (2, 'two'), (3, 'three')",
        "CREATE TABLE b (y TEXT, x REAL)",
        "INSERT INTO b SELECT y, x * 2 FROM a WHERE x > 1",
    )
    pair.check("SELECT * FROM b ORDER BY x")


def test_null_ordering_and_mixed_types(pair):
    pair.exec(
        "CREATE TABLE m (v TEXT, n REAL)",
        "INSERT INTO m VALUES ('b', 2), (NULL, NULL), ('a', -1), ('B', 1.5), ('', 0), ('10', 10),"
        " ('9', 9), (NULL, 3)",
    )
    pair.check("SELECT v FROM m ORDER BY v")
    pair.check("SELECT v FROM m ORDER BY v DESC")
    pair.check("SELECT n FROM m ORDER BY n")
    pair.check("SELECT n FROM m ORDER BY n DESC")
    pair.check("SELECT v, n FROM m ORDER BY n IS NULL, v DESC, n")
    pair.check("SELECT MIN(v), MAX(v), MIN(n), MAX(n) FROM m")


def test_empty_table_aggregates(pair):
    pair.exec("CREATE TABLE e (a INTEGER, b REAL, c TEXT)")
    pair.check("SELECT COUNT(*), COUNT(a), SUM(a), AVG(a), MIN(a), MAX(a), total(a) FROM e")
    pair.check("SELECT SUM(b), AVG(b), MIN(c), MAX(c), COUNT(DISTINCT c) FROM e")
    pair.check("SELECT a, COUNT(*) FROM e GROUP BY a")
    pair.check("SELECT a, COUNT(*) FROM e")
    pair.check("SELECT * FROM e")
    pair.check("SELECT e1.a, e2.a FROM e e1 LEFT JOIN e e2 ON e1.a = e2.a")


def test_all_null_aggregates(pair):
    pair.exec(
        "CREATE TABLE n (a INTEGER, b TEXT)",
        "INSERT INTO n VALUES (NULL, 'x'), (NULL, 'y')",
    )
    pair.check("SELECT COUNT(*), COUNT(a), SUM(a), AVG(a), MIN(a), MAX(a), total(a) FROM n")
    pair.check("SELECT b, SUM(a), COUNT(a) FROM n GROUP BY b ORDER BY b")


def test_sum_int_vs_real_and_precision(pair):
    pair.exec(
        "CREATE TABLE s (i INTEGER, r REAL)",
        "INSERT INTO s VALUES (1, 0.1), (2, 0.2), (3, 0.3), (4, 1e16), (5, -1e16), (6, 0.7)",
    )
    pair.check("SELECT SUM(i), SUM(r), AVG(i), AVG(r), total(i) FROM s")
    pair.check("SELECT SUM(i) / 4, SUM(i) / 4.0, SUM(i) % 4 FROM s")


def test_integer_overflow_in_sum_raises(pair):
    from minisql import SQLError

    pair.exec(
        "CREATE TABLE big (i INTEGER)",
        "INSERT INTO big VALUES (9223372036854775807), (1)",
    )
    with pytest.raises(SQLError):
        pair.db.execute("SELECT SUM(i) FROM big")
    pair.check("SELECT AVG(i), total(i) FROM big")


def test_group_by_null_and_numeric_equality(pair):
    pair.exec(
        "CREATE TABLE g (k REAL, v INTEGER)",
        "INSERT INTO g VALUES (1, 1), (1.0, 2), (NULL, 3), (NULL, 4), (2.5, 5)",
    )
    pair.check("SELECT k, COUNT(*), SUM(v) FROM g GROUP BY k ORDER BY k")
    pair.check("SELECT DISTINCT k FROM g ORDER BY k")
    pair.check("SELECT COUNT(DISTINCT k) FROM g")


def test_left_join_chain_with_no_matches(pair):
    pair.exec(
        "CREATE TABLE a (id INTEGER)",
        "CREATE TABLE b (id INTEGER, a_id INTEGER)",
        "CREATE TABLE c (id INTEGER, b_id INTEGER)",
        "INSERT INTO a VALUES (1), (2), (3)",
        "INSERT INTO b VALUES (10, 1), (11, 1), (12, 2)",
        "INSERT INTO c VALUES (100, 10), (101, 12)",
    )
    pair.check(
        "SELECT a.id, b.id, c.id FROM a LEFT JOIN b ON b.a_id = a.id "
        "LEFT JOIN c ON c.b_id = b.id ORDER BY a.id, b.id, c.id"
    )
    pair.check(
        "SELECT a.id, b.id, c.id FROM a LEFT JOIN b ON b.a_id = a.id "
        "JOIN c ON c.b_id = b.id ORDER BY a.id"
    )
    pair.check(
        "SELECT a.id, COUNT(b.id), COUNT(c.id) FROM a LEFT JOIN b ON b.a_id = a.id "
        "LEFT JOIN c ON c.b_id = b.id GROUP BY a.id ORDER BY a.id"
    )


def test_like_case_rules(pair):
    pair.exec(
        "CREATE TABLE w (s TEXT)",
        "INSERT INTO w VALUES ('Apple'), ('apple'), ('APPLE'), ('ÄPPLE'), ('äpple'), ('a_b'),"
        " ('a%b'), ('axb'), (NULL), ('')",
    )
    for pattern in ["'apple'", "'a%'", "'%PL%'", "'äpple'", "'Äpple'", "'a_b'", "'_'",
                    "'%'", "''", "'%b'", "NULL"]:
        pair.check(f"SELECT s FROM w WHERE s LIKE {pattern}")
        pair.check(f"SELECT s FROM w WHERE s NOT LIKE {pattern}")


BARE_COLUMN_QUERIES = [
    "SELECT g, a FROM b GROUP BY g",
    "SELECT g, a, COUNT(*), SUM(c) FROM b GROUP BY g",
    "SELECT a, COUNT(*) FROM b",
    "SELECT g, a, MAX(c) FROM b GROUP BY g",
    "SELECT g, a, MIN(c) FROM b GROUP BY g",
    "SELECT a, MAX(c) FROM b",
    "SELECT a, MIN(c), MAX(c) FROM b",
    "SELECT g, a, MIN(c), MAX(c) FROM b GROUP BY g",
    "SELECT COUNT(*) AS c FROM b HAVING c > 0",
    "SELECT a AS c FROM b GROUP BY a HAVING c > 1",
    "SELECT SUM(a) AS c FROM b GROUP BY c HAVING c > 1",
    "SELECT a + 10 AS c FROM b WHERE c > 0",
    "SELECT a AS c, COUNT(*) FROM b GROUP BY c",
    "SELECT a * 10 AS c FROM b ORDER BY c DESC",
    "SELECT a * 10 AS c FROM b ORDER BY c + 0 DESC, a",
    "SELECT a + 1 AS x FROM b WHERE x > 25",
    "SELECT a % 20 AS m, COUNT(*) FROM b GROUP BY m ORDER BY m",
]


@pytest.mark.parametrize("sql", BARE_COLUMN_QUERIES)
def test_bare_columns_and_alias_resolution(pair, sql):
    pair.exec(
        "CREATE TABLE b (g INTEGER, a INTEGER, c REAL)",
        "INSERT INTO b VALUES (1, 10, 5.0), (2, 20, -1.0), (1, 30, 7.0), (2, 40, 3.0), "
        "(1, 50, 6.0)",
    )
    pair.check(sql)


def test_aggregate_only_in_order_by_is_error(people):
    from minisql import SQLError

    with pytest.raises(SQLError):
        people.db.execute("SELECT name FROM people ORDER BY COUNT(*)")
