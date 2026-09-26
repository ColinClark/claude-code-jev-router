"""CREATE / INSERT / UPDATE / DELETE compared against SQLite."""

from tests.conftest import Pair


def test_insert_with_column_list_and_nulls():
    p = Pair("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    p.run("INSERT INTO t (b) VALUES ('only b')")
    p.run("INSERT INTO t (c, a) VALUES (2.5, 7), (NULL, 8)")
    p.run("INSERT INTO t VALUES (1, 'x', 1.0), (2, NULL, NULL)")
    p.check("SELECT * FROM t")
    p.check("SELECT a, typeof(a), b, typeof(b), c, typeof(c) FROM t")


def test_insert_expressions():
    p = Pair("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    p.run("INSERT INTO t VALUES (1 + 2 * 3, 'a' || 'b', 10 / 4), (-5, upper('x'), 1.0 / 3)")
    p.check("SELECT * FROM t")


def test_type_affinity_on_insert():
    p = Pair("CREATE TABLE t (i INTEGER, r REAL, s TEXT)")
    p.run("INSERT INTO t VALUES (3.0, 3, 3), ('12', '2.5', 2.5), (4.5, '1e2', -1)")
    p.run("INSERT INTO t VALUES ('abc', 'xyz', NULL), (' 42 ', '7', 1e20)")
    p.check("SELECT i, typeof(i), r, typeof(r), s, typeof(s) FROM t")


def test_update():
    p = Pair(
        "CREATE TABLE t (id INTEGER, name TEXT, score REAL)",
        "INSERT INTO t VALUES (1, 'a', 1.0), (2, 'b', NULL), (3, 'c', 3.5), (4, NULL, 4.0)",
    )
    p.run("UPDATE t SET score = score * 2 WHERE id > 1")
    p.check("SELECT * FROM t")
    p.run("UPDATE t SET name = name || '!', id = id + 10")
    p.check("SELECT * FROM t")
    p.run("UPDATE t SET score = 0 WHERE score IS NULL")
    p.check("SELECT id, score, typeof(score) FROM t")
    p.run("UPDATE t SET id = score, score = id WHERE name = 'c!'")
    p.check("SELECT * FROM t")
    p.run("UPDATE t SET name = NULL WHERE NULL")
    p.check("SELECT * FROM t")


def test_delete():
    p = Pair(
        "CREATE TABLE t (id INTEGER, v TEXT)",
        "INSERT INTO t VALUES (1, 'a'), (2, NULL), (3, 'c'), (4, 'd')",
    )
    p.run("DELETE FROM t WHERE v IS NULL")
    p.check("SELECT * FROM t")
    p.run("DELETE FROM t WHERE v = NULL")
    p.check("SELECT * FROM t")
    p.run("DELETE FROM t WHERE id IN (1, 4)")
    p.check("SELECT * FROM t")
    p.run("DELETE FROM t")
    p.check("SELECT * FROM t")
    p.check("SELECT COUNT(*) FROM t")


def test_insert_select_and_drop():
    p = Pair(
        "CREATE TABLE src (a INTEGER, b TEXT)",
        "INSERT INTO src VALUES (1, 'x'), (2, 'y'), (3, 'z')",
        "CREATE TABLE dst (b TEXT, a INTEGER)",
    )
    p.run("INSERT INTO dst SELECT b, a * 10 FROM src WHERE a > 1")
    p.run("INSERT INTO dst (a) SELECT a FROM src WHERE a = 1")
    p.check("SELECT * FROM dst")
    p.run("DROP TABLE src")
    p.run("CREATE TABLE IF NOT EXISTS dst (z INTEGER)")
    p.run("DROP TABLE IF EXISTS nope")
    p.check("SELECT * FROM dst")


def test_case_insensitive_identifiers_in_dml():
    p = Pair("CREATE TABLE Things (Id INTEGER, Label TEXT)")
    p.run("INSERT INTO THINGS (ID, label) VALUES (1, 'x')")
    p.run("UPDATE things SET LABEL = 'y' WHERE id = 1")
    p.check("SELECT things.LABEL, T.id FROM Things t JOIN things ON t.id = things.id")
