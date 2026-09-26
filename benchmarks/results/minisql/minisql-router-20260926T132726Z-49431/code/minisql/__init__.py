"""minisql: an in-memory SQL database engine in pure Python."""

from minisql.errors import SQLError
from minisql.executor import Database

__all__ = ["Database", "SQLError"]
