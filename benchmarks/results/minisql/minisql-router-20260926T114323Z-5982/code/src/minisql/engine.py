"""Core engine for minisql: the public :class:`Database` entry point."""

from __future__ import annotations

from minisql.errors import SQLError
from minisql.executor import Executor
from minisql.parser import parse

__all__ = ["Database", "SQLError"]

# Python-level failures that indicate a SQL-level problem must surface as SQLError.
_INTERNAL_ERRORS = (ArithmeticError, TypeError, ValueError, IndexError, KeyError, RecursionError)


class Database:
    """An in-memory SQL database."""

    def __init__(self) -> None:
        self._executor = Executor()

    def execute(self, sql: str) -> list[tuple]:
        """Execute a single SQL statement. SELECT returns rows; other statements return []."""
        if not isinstance(sql, str):
            raise SQLError("SQL must be a string")
        try:
            stmt = parse(sql)
            return self._executor.execute(stmt)
        except SQLError:
            raise
        except _INTERNAL_ERRORS as exc:
            raise SQLError(f"{type(exc).__name__}: {exc}") from exc
