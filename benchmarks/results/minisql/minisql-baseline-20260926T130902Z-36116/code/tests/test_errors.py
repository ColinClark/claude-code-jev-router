import pytest

from minisql import Database, SQLError


@pytest.fixture
def db():
    database = Database()
    database.execute("CREATE TABLE a (id INTEGER, name TEXT)")
    database.execute("CREATE TABLE b (id INTEGER, a_id INTEGER, val INTEGER)")
    database.execute("INSERT INTO a VALUES (1, 'x')")
    database.execute("INSERT INTO b VALUES (1, 1, 10)")
    return database


def test_invalid_sql_raises(db):
    with pytest.raises(SQLError):
        db.execute("SELEKT * FROM a")


def test_unknown_table_raises(db):
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM nope")


def test_unknown_column_raises(db):
    with pytest.raises(SQLError):
        db.execute("SELECT nope FROM a")


def test_unknown_column_in_where_raises(db):
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM a WHERE nope = 1")


def test_ambiguous_column_raises(db):
    with pytest.raises(SQLError):
        db.execute("SELECT id FROM a JOIN b ON a.id = b.a_id")


def test_ambiguous_column_in_where_raises(db):
    with pytest.raises(SQLError):
        db.execute("SELECT a.name FROM a JOIN b ON a.id = b.a_id WHERE id = 1")


def test_qualified_column_resolves_ambiguity(db):
    result = db.execute("SELECT a.id FROM a JOIN b ON a.id = b.a_id")
    assert result == [(1,)]


def test_unknown_table_alias_in_star_raises(db):
    with pytest.raises(SQLError):
        db.execute("SELECT z.* FROM a")


def test_malformed_create_table_raises(db):
    with pytest.raises(SQLError):
        db.execute("CREATE TABLE c (id WEIRDTYPE)")


def test_insert_unknown_column_raises(db):
    with pytest.raises(SQLError):
        db.execute("INSERT INTO a (nope) VALUES (1)")


def test_update_unknown_column_raises(db):
    with pytest.raises(SQLError):
        db.execute("UPDATE a SET nope = 1")


def test_trailing_garbage_raises(db):
    with pytest.raises(SQLError):
        db.execute("SELECT * FROM a; garbage")


def test_unclosed_paren_raises(db):
    with pytest.raises(SQLError):
        db.execute("SELECT (1 + 2 FROM a")
