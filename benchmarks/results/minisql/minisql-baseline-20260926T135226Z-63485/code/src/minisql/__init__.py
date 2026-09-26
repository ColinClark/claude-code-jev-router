"""minisql: an in-memory SQL database engine in pure Python."""

from .engine import Database
from .errors import SQLError

__all__ = ["Database", "SQLError"]
