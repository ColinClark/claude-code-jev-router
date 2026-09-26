"""SELECT behaviour on shared fixture data, compared against sqlite3."""

import pytest

QUERIES = [
    # projection and filtering
    "SELECT * FROM people",
    "SELECT p.* FROM people p",
    "SELECT name, age FROM people WHERE age > 28",
    "SELECT name FROM people WHERE age IS NULL",
    "SELECT name FROM people WHERE age IS NOT NULL AND city IS NOT NULL",
    "SELECT name FROM people WHERE NOT (age > 28)",
    "SELECT name FROM people WHERE age > 28 OR city = 'Berlin'",
    "SELECT name FROM people WHERE city IN ('Paris', 'Berlin')",
    "SELECT name FROM people WHERE city NOT IN ('Paris', 'Berlin')",
    "SELECT name FROM people WHERE city NOT IN ('Paris', NULL)",
    "SELECT name FROM people WHERE age BETWEEN 25 AND 30",
    "SELECT name FROM people WHERE age NOT BETWEEN 25 AND 30",
    "SELECT name FROM people WHERE name LIKE '%a%'",
    "SELECT name FROM people WHERE name NOT LIKE 'a%'",
    "SELECT name FROM people WHERE city LIKE 'PARIS'",
    "SELECT name FROM people WHERE score",
    "SELECT name, age * 2 AS double_age, score / 2, age / 2, age % 7 FROM people",
    "SELECT name || ' (' || city || ')' FROM people",
    "SELECT id, -score, age + score FROM people",
    "SELECT DISTINCT city FROM people",
    "SELECT DISTINCT age, city FROM people",
    "SELECT DISTINCT age FROM people ORDER BY age",
    "SELECT DISTINCT age % 2 FROM people ORDER BY 1 DESC",
    # ORDER BY
    "SELECT name, age FROM people ORDER BY age, name",
    "SELECT name, age FROM people ORDER BY age DESC, name",
    "SELECT name, age FROM people ORDER BY age ASC, name DESC",
    "SELECT name, score FROM people ORDER BY score DESC, id",
    "SELECT name, city FROM people ORDER BY city, id",
    "SELECT name, city FROM people ORDER BY city DESC, id",
    "SELECT name FROM people ORDER BY name",
    "SELECT name AS n FROM people ORDER BY n DESC",
    "SELECT name, age + 1 AS a1 FROM people ORDER BY a1 DESC, name",
    "SELECT name, age FROM people ORDER BY 2 DESC, 1",
    "SELECT name FROM people ORDER BY -age, id",
    "SELECT name FROM people ORDER BY age IS NULL, age, id",
    "SELECT name, age AS x FROM people ORDER BY x * -1, id",
    "SELECT id FROM people ORDER BY city || name",
    "SELECT name AS age FROM people ORDER BY age",
    "SELECT id, name FROM people WHERE id > 2 ORDER BY people.name",
    # LIMIT / OFFSET
    "SELECT id FROM people ORDER BY id LIMIT 3",
    "SELECT id FROM people ORDER BY id LIMIT 3 OFFSET 2",
    "SELECT id FROM people ORDER BY id LIMIT 2, 3",
    "SELECT id FROM people ORDER BY id LIMIT 0",
    "SELECT id FROM people ORDER BY id LIMIT -1 OFFSET 5",
    "SELECT id FROM people ORDER BY id LIMIT 10 OFFSET 100",
    "SELECT id FROM people ORDER BY id LIMIT 1 + 1",
    # aggregates without GROUP BY
    "SELECT COUNT(*) FROM people",
    "SELECT COUNT(age), COUNT(city), COUNT(score) FROM people",
    "SELECT COUNT(DISTINCT age), COUNT(DISTINCT city) FROM people",
    "SELECT SUM(age), AVG(age), MIN(age), MAX(age) FROM people",
    "SELECT SUM(score), AVG(score), MIN(score), MAX(score) FROM people",
    "SELECT MIN(name), MAX(name), MIN(city), MAX(city) FROM people",
    "SELECT SUM(DISTINCT age), AVG(DISTINCT age) FROM people",
    "SELECT COUNT(*), SUM(age), AVG(age), MIN(age), MAX(age), TOTAL(age) FROM people "
    "WHERE id > 100",
    "SELECT COUNT(age), SUM(age), AVG(score) FROM people WHERE age IS NULL",
    "SELECT SUM(age) + 1, MAX(age) - MIN(age), COUNT(*) * 2 FROM people",
    "SELECT SUM(age * score), AVG(age / 2), SUM(age / 2.0) FROM people",
    "SELECT COUNT(*) FROM people WHERE city = 'Paris'",
    "SELECT MAX(age), name FROM people",
    "SELECT MIN(score), name FROM people",
    # GROUP BY / HAVING
    "SELECT city, COUNT(*) FROM people GROUP BY city",
    "SELECT city, COUNT(*), AVG(age), SUM(score) FROM people GROUP BY city ORDER BY city",
    "SELECT age, COUNT(*) FROM people GROUP BY age ORDER BY age DESC",
    "SELECT city, COUNT(*) AS n FROM people GROUP BY city HAVING n > 1",
    "SELECT city, COUNT(*) FROM people GROUP BY city HAVING COUNT(*) > 1 ORDER BY city",
    "SELECT city FROM people GROUP BY city HAVING MAX(age) > 30",
    "SELECT city, MAX(age) FROM people GROUP BY city HAVING MAX(age) IS NULL",
    "SELECT city, COUNT(*) FROM people GROUP BY city ORDER BY COUNT(*) DESC, city",
    "SELECT city, SUM(score) AS s FROM people GROUP BY city ORDER BY s DESC",
    "SELECT age % 2 AS parity, COUNT(*) FROM people GROUP BY age % 2",
    "SELECT age % 2 AS parity, COUNT(*) FROM people GROUP BY parity",
    "SELECT city, age, COUNT(*) FROM people GROUP BY city, age",
    "SELECT city, COUNT(*) FROM people GROUP BY 1 ORDER BY 2 DESC, 1",
    "SELECT COUNT(*) FROM people GROUP BY city HAVING city LIKE 'p%'",
    "SELECT city FROM people GROUP BY city",
    "SELECT COUNT(*) FROM people WHERE id > 100 GROUP BY city",
    "SELECT city, COUNT(DISTINCT age) FROM people GROUP BY city",
    "SELECT city, MIN(name), MAX(name) FROM people GROUP BY city",
    "SELECT 1 FROM people GROUP BY city",
    "SELECT COUNT(*) FROM people HAVING COUNT(*) > 3",
    "SELECT COUNT(*) FROM people HAVING COUNT(*) > 30",
    "SELECT city, AVG(score) FROM people GROUP BY city HAVING AVG(score) > 70 ORDER BY AVG(score)",
    # joins
    "SELECT p.name, o.item FROM people p JOIN orders o ON p.id = o.pid",
    "SELECT p.name, o.item FROM people p INNER JOIN orders o ON p.id = o.pid",
    "SELECT name, item FROM people JOIN orders ON id = pid",
    "SELECT people.name, orders.item FROM people JOIN orders ON people.id = orders.pid",
    "SELECT p.name, o.item, o.amount FROM people p LEFT JOIN orders o ON p.id = o.pid",
    "SELECT p.name, o.item FROM people AS p LEFT OUTER JOIN orders AS o ON p.id = o.pid "
    "ORDER BY p.id, o.oid",
    "SELECT p.name FROM people p LEFT JOIN orders o ON p.id = o.pid WHERE o.oid IS NULL",
    "SELECT p.name, o.item FROM people p LEFT JOIN orders o ON p.id = o.pid AND o.amount > 10",
    "SELECT p.name, o.item FROM people p JOIN orders o ON p.id = o.pid AND o.amount > 10",
    "SELECT o.item, p.name FROM orders o LEFT JOIN people p ON p.id = o.pid",
    "SELECT * FROM people p JOIN orders o ON p.id = o.pid",
    "SELECT o.*, p.name FROM people p JOIN orders o ON p.id = o.pid",
    "SELECT p.name, COUNT(o.oid), SUM(o.amount) FROM people p LEFT JOIN orders o "
    "ON p.id = o.pid GROUP BY p.id, p.name ORDER BY p.id",
    "SELECT p.city, COUNT(*) FROM people p JOIN orders o ON p.id = o.pid GROUP BY p.city",
    "SELECT a.name, b.name FROM people a JOIN people b ON a.age = b.age AND a.id < b.id",
    "SELECT a.name, b.name FROM people a LEFT JOIN people b ON a.age < b.age AND b.city = 'Paris'",
    "SELECT p.name, o.item, q.name FROM people p JOIN orders o ON p.id = o.pid "
    "LEFT JOIN people q ON q.age = p.age AND q.id <> p.id",
    "SELECT p.name, o1.item, o2.item FROM people p LEFT JOIN orders o1 ON o1.pid = p.id "
    "LEFT JOIN orders o2 ON o2.pid = p.id AND o2.oid > o1.oid",
    "SELECT p.name, o.item FROM people p, orders o WHERE p.id = o.pid",
    "SELECT COUNT(*) FROM people CROSS JOIN orders",
    "SELECT p.name, o.item FROM people p JOIN orders o ON 1",
    "SELECT p.name FROM people p LEFT JOIN orders o ON p.id = o.pid "
    "GROUP BY p.name HAVING COUNT(o.oid) = 0",
    "SELECT o.item, COUNT(*), MAX(p.age) FROM orders o LEFT JOIN people p ON p.id = o.pid "
    "GROUP BY o.item ORDER BY o.item",
    "SELECT p.name, o.amount FROM people p LEFT JOIN orders o ON p.id = o.pid "
    "ORDER BY o.amount DESC, p.name",
    # aliases in WHERE / GROUP BY (SQLite extension)
    "SELECT age * 2 AS twice FROM people WHERE twice > 60",
    "SELECT city AS c, COUNT(*) FROM people GROUP BY c ORDER BY c",
    # expressions with NULLs in comparisons
    "SELECT name FROM people WHERE city = NULL",
    "SELECT name FROM people WHERE city <> 'Paris'",
    "SELECT name FROM people WHERE age > 25 AND score > 70",
    "SELECT name FROM people WHERE age > 25 OR score > 70",
    "SELECT name, age > 25, score > 70, age > 25 AND score > 70 FROM people",
    "SELECT id, city = 'Paris', city LIKE 'paris', city IN ('Paris', NULL) FROM people",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_select(people, sql):
    people.check(sql)


def test_order_by_nulls_first_and_last(both):
    both.run(
        "CREATE TABLE n (x INTEGER, y TEXT)",
        "INSERT INTO n VALUES (3, 'c'), (NULL, 'a'), (1, NULL), (NULL, NULL), (2, 'b')",
    )
    both.check("SELECT x FROM n ORDER BY x")
    both.check("SELECT x FROM n ORDER BY x DESC")
    both.check("SELECT y FROM n ORDER BY y")
    both.check("SELECT y FROM n ORDER BY y DESC")
    both.check("SELECT x, y FROM n ORDER BY y DESC, x")


def test_text_ordering_is_binary(both):
    both.run(
        "CREATE TABLE s (v TEXT)",
        "INSERT INTO s VALUES ('b'), ('B'), ('a'), ('A'), ('é'), ('_'), ('10'), ('9'), ('')",
    )
    both.check("SELECT v FROM s ORDER BY v")
    both.check("SELECT MIN(v), MAX(v) FROM s")


def test_aggregates_on_empty_table(both):
    both.run("CREATE TABLE e (x INTEGER, y REAL, z TEXT)")
    both.check("SELECT COUNT(*), COUNT(x), SUM(x), AVG(x), MIN(x), MAX(z), TOTAL(y) FROM e")
    both.check("SELECT x, COUNT(*) FROM e GROUP BY x")
    both.check("SELECT COUNT(*) FROM e HAVING COUNT(*) = 0")
    both.check("SELECT COUNT(*), MAX(x) FROM e HAVING MAX(x) IS NULL")
    both.check("SELECT x FROM e ORDER BY x")
    both.check("SELECT SUM(x) IS NULL, COUNT(*) = 0 FROM e")


def test_sum_int_vs_real(both):
    both.run(
        "CREATE TABLE s (i INTEGER, r REAL)",
        "INSERT INTO s VALUES (1, 0.1), (2, 0.2), (3, 0.3), (NULL, NULL)",
    )
    both.check("SELECT SUM(i), SUM(r), AVG(i), AVG(r), TOTAL(i), SUM(i + r) FROM s")
    both.check("SELECT SUM(i) / 2, SUM(r) / 2, AVG(i) * 2 FROM s")


def test_float_summation_precision(both):
    both.run("CREATE TABLE f (r REAL)")
    values = ", ".join(f"({v})" for v in ["1e16", "1.0", "-1e16", "0.1", "0.7", "1e-3", "3.3"])
    both.run(f"INSERT INTO f VALUES {values}")
    both.check("SELECT SUM(r), AVG(r), TOTAL(r) FROM f")


def test_integer_sum_overflow_is_error(both):
    from minisql import SQLError

    both.run(
        "CREATE TABLE big (i INTEGER)",
        "INSERT INTO big VALUES (9223372036854775807), (1)",
    )
    with pytest.raises(SQLError):
        both.db.execute("SELECT SUM(i) FROM big")
    both.check("SELECT AVG(i), TOTAL(i) FROM big")


def test_left_join_multiple_levels(both):
    both.run(
        "CREATE TABLE a (id INTEGER, v TEXT)",
        "CREATE TABLE b (id INTEGER, aid INTEGER, w REAL)",
        "CREATE TABLE c (bid INTEGER, z TEXT)",
        "INSERT INTO a VALUES (1, 'x'), (2, 'y'), (3, NULL)",
        "INSERT INTO b VALUES (10, 1, 1.5), (11, 1, NULL), (12, 2, 2.5)",
        "INSERT INTO c VALUES (10, 'p'), (12, 'q'), (12, 'r')",
    )
    both.check(
        "SELECT a.id, b.id, c.z FROM a LEFT JOIN b ON b.aid = a.id "
        "LEFT JOIN c ON c.bid = b.id ORDER BY a.id, b.id, c.z"
    )
    both.check(
        "SELECT a.id, COUNT(b.id), COUNT(c.z), SUM(b.w) FROM a LEFT JOIN b ON b.aid = a.id "
        "LEFT JOIN c ON c.bid = b.id GROUP BY a.id ORDER BY a.id"
    )
    both.check("SELECT a.v, b.w FROM a LEFT JOIN b ON b.aid = a.id WHERE b.w IS NULL ORDER BY a.id")
    both.check("SELECT a.id, b.id FROM a JOIN b ON b.aid = a.id JOIN c ON c.bid = b.id")


def test_update_and_delete_match_sqlite(people):
    people.run(
        "UPDATE people SET age = age + 1, city = 'Rome' WHERE city IS NULL OR age > 34",
        "UPDATE people SET score = score * 2 WHERE score BETWEEN 70 AND 90",
        "DELETE FROM people WHERE name LIKE '%e'",
        "UPDATE orders SET amount = NULL WHERE item = 'pen'",
        "UPDATE orders SET item = item || '!'",
    )
    people.check("SELECT * FROM people ORDER BY id")
    people.check("SELECT * FROM orders ORDER BY oid")


def test_update_affinity(both):
    both.run(
        "CREATE TABLE u (i INTEGER, r REAL, t TEXT)",
        "INSERT INTO u VALUES (1, 1.0, 'a')",
        "UPDATE u SET i = '42', r = 3, t = 2.5",
    )
    both.check("SELECT i, r, t FROM u")
    both.run("UPDATE u SET i = i / 4.0, r = r / 2, t = t || 1")
    both.check("SELECT i, r, t FROM u")


def test_ambiguous_column_raises(people):
    from minisql import SQLError

    people.run("CREATE TABLE other (id INTEGER, name TEXT)")
    with pytest.raises(SQLError):
        people.db.execute("SELECT name FROM people JOIN other ON people.id = other.id")
    with pytest.raises(SQLError):
        people.db.execute("SELECT * FROM people JOIN other ON id = id")
    people.check("SELECT people.name, other.name FROM people JOIN other ON people.id = other.id")


def test_join_on_mixed_affinity_columns(both):
    both.run(
        "CREATE TABLE l (i INTEGER, r REAL, t TEXT)",
        "CREATE TABLE rr (i INTEGER, r REAL, t TEXT)",
        "INSERT INTO l VALUES (1, 1.0, '1'), (2, 2.5, '2.5'), (3, NULL, 'x'), (NULL, 0.0, '0')",
        "INSERT INTO rr VALUES (1, 1.5, '1'), (2, 2.5, '2.50'), (0, 3.0, '3'), (NULL, 1.0, NULL)",
    )
    for a in ("i", "r", "t"):
        for b in ("i", "r", "t"):
            for kind in ("JOIN", "LEFT JOIN"):
                both.check(f"SELECT l.i, l.r, l.t, rr.i FROM l {kind} rr ON l.{a} = rr.{b}")
                both.check(f"SELECT l.i, rr.i FROM l {kind} rr ON rr.{b} = l.{a} + 0")


def test_like_with_column_pattern(both):
    both.run(
        "CREATE TABLE p (s TEXT, pat TEXT)",
        "INSERT INTO p VALUES ('hello', 'h%'), ('hello', 'H_LLO'), ('x', NULL), (NULL, '%'), "
        "('50%', '50\\%'), ('abc', '%b%')",
    )
    both.check("SELECT s, pat, s LIKE pat, s NOT LIKE pat FROM p")
    both.check("SELECT s, pat FROM p WHERE s LIKE pat ESCAPE '\\'")


def test_group_by_with_null_keys_and_text_numbers(both):
    both.run(
        "CREATE TABLE g (k TEXT, n INTEGER, v REAL)",
        "INSERT INTO g VALUES ('1', 1, 1.0), ('1', 1, 2.0), (NULL, NULL, 3.0), (NULL, 2, NULL), "
        "('a', 2, 0.5), ('A', 2, 0.25)",
    )
    both.check("SELECT k, COUNT(*), SUM(v), AVG(v) FROM g GROUP BY k ORDER BY k")
    both.check("SELECT n, COUNT(v), MIN(k), MAX(k) FROM g GROUP BY n ORDER BY n DESC")
    both.check("SELECT k, n, COUNT(*) FROM g GROUP BY k, n ORDER BY k, n")
    both.check("SELECT COUNT(DISTINCT k), COUNT(DISTINCT n), COUNT(DISTINCT v) FROM g")
    both.check("SELECT DISTINCT k, n FROM g ORDER BY 1, 2")
