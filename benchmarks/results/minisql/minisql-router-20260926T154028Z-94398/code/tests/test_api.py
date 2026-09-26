"""Public API, statement results and error handling."""

import pytest

from minisql import Database, SQLError


def test_returns_lists_of_tuples(db):
    assert db.execute("CREATE TABLE t (a INTEGER, b TEXT, c REAL)") == []
    assert db.execute("INSERT INTO t VALUES (1, 'x', 2.5), (2, NULL, 3)") == []
    rows = db.execute("SELECT a, b, c FROM t ORDER BY a")
    assert rows == [(1, "x", 2.5), (2, None, 3.0)]
    assert all(isinstance(r, tuple) for r in rows)
    assert isinstance(rows[1][2], float)
    assert db.execute("UPDATE t SET a = 5") == []
    assert db.execute("DELETE FROM t") == []
    assert db.execute("SELECT * FROM t") == []


def test_omitted_columns_are_null(db):
    db.execute("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
    db.execute("INSERT INTO t (b) VALUES ('only')")
    assert db.execute("SELECT * FROM t") == [(None, "only", None)]


def test_case_insensitive_keywords_and_identifiers(db):
    db.execute("create table MyTable (MyCol integer)")
    db.execute("INSERT into mytable (MYCOL) values (1)")
    assert db.execute("SeLeCt mycol FrOm MYTABLE") == [(1,)]
    assert db.execute("select MyTable.MYCOL from mytable") == [(1,)]


def test_trailing_semicolon_and_comments(db):
    db.execute("CREATE TABLE t (a INTEGER);")
    db.execute("INSERT INTO t VALUES (1) -- comment")
    assert db.execute("SELECT /* hi */ a FROM t;") == [(1,)]


def test_string_escape(db):
    assert db.execute("SELECT 'it''s'") == [("it's",)]


def test_column_types_are_coerced(db):
    db.execute("CREATE TABLE t (i INTEGER, r REAL, s TEXT)")
    db.execute("INSERT INTO t VALUES (3.0, 2, 7)")
    db.execute("INSERT INTO t VALUES ('4', '1.5', 1.5)")
    assert db.execute("SELECT * FROM t") == [(3, 2.0, "7"), (4, 1.5, "1.5")]


@pytest.fixture
def two(db):
    db.execute("CREATE TABLE a (id INTEGER, x TEXT)")
    db.execute("CREATE TABLE b (id INTEGER, y TEXT)")
    db.execute("INSERT INTO a VALUES (1, 'p')")
    return db


@pytest.mark.parametrize(
    "sql",
    [
        "SELEC 1",
        "SELECT",
        "SELECT 1 FROM",
        "SELECT * FROM nope",
        "SELECT nope FROM a",
        "SELECT a.nope FROM a",
        "SELECT z.id FROM a",
        "SELECT id FROM a JOIN b ON a.id = b.id",
        "SELECT id FROM a, b",
        "SELECT * FROM a JOIN a ON 1",
        "SELECT a.id FROM a AS t",
        "SELECT 'unterminated",
        "SELECT (1 + 2",
        "SELECT 1 2 3",
        "INSERT INTO nope VALUES (1)",
        "INSERT INTO a VALUES (1)",
        "INSERT INTO a VALUES (1, 2, 3)",
        "INSERT INTO a (id, nope) VALUES (1, 2)",
        "INSERT INTO a (id) VALUES (1, 2)",
        "INSERT INTO a VALUES (id, 1)",
        "UPDATE nope SET x = 1",
        "UPDATE a SET nope = 1",
        "UPDATE a SET x = nope",
        "DELETE FROM nope",
        "DELETE FROM a WHERE nope = 1",
        "CREATE TABLE a (z INTEGER)",
        "CREATE TABLE c (z INTEGER, Z TEXT)",
        "SELECT * FROM a WHERE count(*) > 1",
        "SELECT id FROM a GROUP BY count(*)",
        "SELECT sum(count(*)) FROM a",
        "SELECT nofunc(1)",
        "SELECT id FROM a ORDER BY 5",
        "SELECT id FROM a GROUP BY 0",
        "SELECT b.* FROM a",
        "SELECT *",
        "SELECT 1; SELECT 2",
        "SELECT 1 LIMIT 'x'",
        "DROP TABLE nope",
    ],
)
def test_errors(two, sql):
    with pytest.raises(SQLError):
        two.execute(sql)


def test_ambiguous_error_even_on_empty_tables(db):
    db.execute("CREATE TABLE a (id INTEGER)")
    db.execute("CREATE TABLE b (id INTEGER)")
    with pytest.raises(SQLError, match="ambiguous"):
        db.execute("SELECT id FROM a JOIN b ON 1")
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM a WHERE nope = 1")


def test_errors_leave_state_unchanged(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1)")
    with pytest.raises(SQLError):
        db.execute("INSERT INTO t VALUES (2), (3, 4)")
    with pytest.raises(SQLError):
        db.execute("UPDATE t SET a = nope")
    assert db.execute("SELECT * FROM t") == [(1,)]


def test_sqlerror_is_exception():
    assert issubclass(SQLError, Exception)


def test_separate_databases_are_independent():
    a, b = Database(), Database()
    a.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(SQLError):
        b.execute("SELECT * FROM t")


def test_where_alias_fallback(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (1), (2), (3)")
    assert db.execute("SELECT a * 10 AS big FROM t WHERE big > 10 ORDER BY big") == [(20,), (30,)]


def test_self_referencing_alias_is_error(db):
    db.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(SQLError):
        db.execute("SELECT b + 1 AS b FROM t")


def test_larger_join_and_group(both):
    both.run("CREATE TABLE f (id INTEGER, k INTEGER, v REAL)")
    both.run("CREATE TABLE g (k INTEGER, name TEXT)")
    vals = ", ".join(f"({i}, {i % 17}, {(i * 7919) % 1000 / 10})" for i in range(600))
    both.run(f"INSERT INTO f VALUES {vals}")
    both.run("INSERT INTO g VALUES " + ", ".join(f"({k}, 'g{k}')" for k in range(0, 20, 2)))
    both.check(
        "SELECT g.name, count(*), sum(f.v), avg(f.v), min(f.v), max(f.v) "
        "FROM f LEFT JOIN g ON f.k = g.k GROUP BY g.name ORDER BY g.name"
    )


def test_fuzz_regressions(both):
    both.run("CREATE TABLE t (a INTEGER, b REAL, c TEXT, n INTEGER)")
    both.run(
        "INSERT INTO t VALUES (0, NULL, '5', 1), (NULL, 0.0, 'x', 2), (NULL, -0.0, '', 3), "
        "(2, 1.5, '1.5', 4), (2, 2.5, 'B', 5)"
    )
    # Integral reals are stored as integers by SQLite: -0.0 reads back as 0.0.
    both.check("SELECT b FROM t ORDER BY n")
    # IN (list) compares using the left operand's affinity only.
    both.check("SELECT c IN (a, '', b), 5 IN (c), a IN ('0', n) FROM t ORDER BY n")
    # Bare columns come from the group's first row, or from the MIN/MAX row.
    both.check("SELECT a, n, count(*) FROM t GROUP BY a ORDER BY 1")
    both.check("SELECT a, n, max(b) FROM t GROUP BY a ORDER BY 1")
    both.check("SELECT coalesce(a, b), n, count(*) FROM t GROUP BY coalesce(a, b) ORDER BY 1")
    # Constant integer ORDER BY/GROUP BY terms are column numbers (and may be out of range).
    both.check("SELECT a FROM t GROUP BY a, (n AND 0)", allow_error=True)
    both.check("SELECT a FROM t ORDER BY -1", allow_error=True)
