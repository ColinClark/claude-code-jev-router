"""Edge cases compared against sqlite3 on purpose-built tables."""

import random
import sqlite3

import pytest

from minisql import Database, SQLError

from .conftest import typed


def both(*statements):
    db, lite = Database(), sqlite3.connect(":memory:")
    for stmt in statements:
        db.execute(stmt)
        lite.execute(stmt)
    return db, lite


def check(db, lite, sql):
    assert typed(db.execute(sql)) == typed(lite.execute(sql).fetchall()), sql


def test_float_sums_match_sqlite_exactly():
    rng = random.Random(1)
    values = ", ".join(
        f"({rng.choice([rng.uniform(-1e6, 1e6), rng.random() / 3, 1e16, -1e16, 0.1])!r}, "
        f"{rng.randrange(-(10**15), 10**15)}, {rng.randrange(5)})"
        for _ in range(400)
    )
    db, lite = both(
        "CREATE TABLE f (x REAL, i INTEGER, g INTEGER)", f"INSERT INTO f VALUES {values}"
    )
    check(db, lite, "SELECT SUM(x), AVG(x), TOTAL(x), SUM(i), AVG(i) FROM f")
    check(db, lite, "SELECT g, SUM(x), AVG(x), SUM(i + x), AVG(i) FROM f GROUP BY g ORDER BY g")
    check(db, lite, "SELECT SUM(x * i), AVG(x / 3) FROM f")


def test_integer_sum_overflow_is_an_error():
    db, lite = both(
        "CREATE TABLE t (a INTEGER)",
        "INSERT INTO t VALUES (9223372036854775807), (1)",
    )
    with pytest.raises(sqlite3.OperationalError):
        lite.execute("SELECT SUM(a) FROM t").fetchall()
    with pytest.raises(SQLError):
        db.execute("SELECT SUM(a) FROM t")
    check(db, lite, "SELECT TOTAL(a), AVG(a), MAX(a) + 1 FROM t")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT s, s LIKE 'é%', s LIKE 'É%', UPPER(s), LOWER(s) FROM u ORDER BY s",
        "SELECT s FROM u WHERE s LIKE '%B%' ORDER BY s",
        "SELECT s, LENGTH(s) FROM u ORDER BY s DESC",
        "SELECT MIN(s), MAX(s) FROM u",
        "SELECT v FROM m ORDER BY v",
        "SELECT v FROM m ORDER BY v DESC",
        "SELECT DISTINCT v FROM m ORDER BY v",
        "SELECT v, COUNT(*) FROM m GROUP BY v ORDER BY v",
        "SELECT MIN(v), MAX(v), COUNT(v), COUNT(DISTINCT v) FROM m",
        "SELECT v, v = 1, v < 'a', v IS NULL, v || '' FROM m ORDER BY v",
    ],
)
def test_text_and_mixed_values(sql):
    db, lite = both(
        "CREATE TABLE u (s TEXT)",
        "INSERT INTO u VALUES ('abc'), ('ABC'), ('éclair'), ('Éclair'), ('b'), ('B'), (''), (NULL)",
        "CREATE TABLE m (v TEXT)",
        "INSERT INTO m VALUES ('1'), ('a'), (NULL), ('10'), ('2'), ('A'), ('-1')",
    )
    check(db, lite, sql)


def test_many_joins():
    stmts = [f"CREATE TABLE t{i} (id INTEGER, v TEXT)" for i in range(4)]
    for i in range(4):
        rows = ", ".join(f"({j}, 't{i}v{j}')" for j in range(i, 6))
        stmts.append(f"INSERT INTO t{i} VALUES {rows}")
    db, lite = both(*stmts)
    check(
        db,
        lite,
        "SELECT t0.id, t1.v, t2.v, t3.v FROM t0 LEFT JOIN t1 ON t1.id = t0.id "
        "JOIN t2 ON t2.id >= t0.id AND t2.id < t0.id + 2 LEFT JOIN t3 ON t3.id = t2.id "
        "ORDER BY t0.id, t2.id",
    )
    check(
        db,
        lite,
        "SELECT a.id, COUNT(b.id), SUM(c.id) FROM t0 a LEFT JOIN t1 b ON b.id > a.id "
        "LEFT JOIN t3 c ON c.id = b.id GROUP BY a.id ORDER BY a.id",
    )


def test_order_by_alias_shadows_column():
    db, lite = both(
        "CREATE TABLE t (a INTEGER, b INTEGER)",
        "INSERT INTO t VALUES (1, 3), (2, 2), (3, 1)",
    )
    check(db, lite, "SELECT a AS b, b AS a FROM t ORDER BY b")
    check(db, lite, "SELECT a AS b FROM t ORDER BY a DESC")
    check(db, lite, "SELECT -a AS a FROM t WHERE a > 1 ORDER BY a")


@pytest.mark.parametrize(
    "on",
    [
        "p.i = q.i",
        "p.i = q.r",
        "q.r = p.i",
        "p.t = q.t",
        "p.i = q.t",
        "p.t = q.r",
        "p.i = q.i AND p.t = q.t",
        "p.i = q.i AND q.r > 1",
        "p.i = q.i OR p.t = q.t",
        "p.i = p.i AND q.i = q.i",
    ],
)
@pytest.mark.parametrize("kind", ["JOIN", "LEFT JOIN"])
def test_equi_joins_with_mixed_types(on, kind):
    db, lite = both(
        "CREATE TABLE p (i INTEGER, t TEXT)",
        "CREATE TABLE q (i INTEGER, r REAL, t TEXT)",
        "INSERT INTO p VALUES (1, '1'), (2, '2.0'), (NULL, NULL), (3, 'x'), (1, 'X'), (4, '4')",
        "INSERT INTO q VALUES (1, 1.0, '1'), (2, 2.5, '2'), (NULL, NULL, 'x'), (3, 3.0, 'X'),"
        " (1, 4.0, '4'), (5, 1.0, NULL)",
    )
    check(db, lite, f"SELECT p.*, q.* FROM p {kind} q ON {on} ORDER BY 1, 2, 3, 4, 5")
