"""minisql: a pure-Python in-memory SQL engine."""

from minisql.database import Database
from minisql.errors import SQLError

__all__ = ["Database", "SQLError"]
