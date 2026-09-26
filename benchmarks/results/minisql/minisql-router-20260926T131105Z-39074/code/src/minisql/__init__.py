"""minisql: a small in-memory SQL database engine with SQLite-compatible semantics."""

from .database import Database
from .errors import SQLError

__all__ = ["Database", "SQLError"]
