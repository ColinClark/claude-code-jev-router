from minisql import Database, SQLError


def test_imports() -> None:
    assert Database is not None
    assert issubclass(SQLError, Exception)
