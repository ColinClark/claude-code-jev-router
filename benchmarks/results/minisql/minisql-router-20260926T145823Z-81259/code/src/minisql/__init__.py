"""minisql: an in-memory SQL database engine with SQLite-compatible semantics."""

from .engine import Database
from .errors import SQLError

__all__ = ["Database", "SQLError"]
