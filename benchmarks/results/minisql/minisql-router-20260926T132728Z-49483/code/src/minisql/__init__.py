"""minisql: an in-memory SQL engine with SQLite-compatible semantics."""

from .engine import Database
from .errors import SQLError

__all__ = ["Database", "SQLError"]
