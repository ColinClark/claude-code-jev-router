from minisql import Database, SQLError


def test_import() -> None:
    assert Database is not None


def test_sqlerror_is_exception() -> None:
    assert issubclass(SQLError, Exception)
