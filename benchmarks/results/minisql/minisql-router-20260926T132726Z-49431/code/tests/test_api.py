import minisql
from minisql import Database, SQLError


def test_public_api_exports():
    assert set(minisql.__all__) == {"Database", "SQLError"}
    assert issubclass(SQLError, Exception)


def test_execute_returns_list_of_tuples():
    db = Database()
    assert db.execute("CREATE TABLE t (a INTEGER, b TEXT)") == []
    assert db.execute("INSERT INTO t VALUES (1, 'x'), (2, 'y')") == []
    rows = db.execute("SELECT a, b FROM t ORDER BY a")
    assert rows == [(1, "x"), (2, "y")]
    assert all(type(r) is tuple for r in rows)
    assert db.execute("UPDATE t SET a = 3 WHERE a = 1") == []
    assert db.execute("DELETE FROM t WHERE a = 2") == []
    assert db.execute("SELECT * FROM t") == [(3, "x")]


def test_databases_are_independent():
    a, b = Database(), Database()
    a.execute("CREATE TABLE t (x INTEGER)")
    b.execute("CREATE TABLE t (x INTEGER)")
    a.execute("INSERT INTO t VALUES (1)")
    assert a.execute("SELECT x FROM t") == [(1,)]
    assert b.execute("SELECT x FROM t") == []


def test_trailing_semicolon_and_comments():
    db = Database()
    db.execute("CREATE TABLE t (x INTEGER); ")
    db.execute("INSERT INTO t VALUES (1) -- comment")
    assert db.execute("/* c */ SELECT x FROM t;") == [(1,)]
    assert db.execute("") == []
    assert db.execute("  -- only a comment") == []


def test_package_does_not_use_sqlite3():
    import pathlib

    pkg = pathlib.Path(minisql.__file__).parent
    for path in pkg.glob("*.py"):
        text = path.read_text()
        assert "sqlite3" not in text, path
