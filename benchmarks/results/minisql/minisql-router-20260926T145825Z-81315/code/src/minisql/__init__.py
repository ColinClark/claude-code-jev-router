"""minisql: an in-memory SQL database engine in pure Python."""

from minisql.database import Database
from minisql.errors import SQLError

__all__ = ["Database", "SQLError"]
