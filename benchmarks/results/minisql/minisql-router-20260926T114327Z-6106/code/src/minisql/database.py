"""In-memory database entry point."""

from __future__ import annotations

from minisql.errors import SQLError
from minisql.executor import Executor
from minisql.parser import parse


class Database:
    """An in-memory SQL database.

    ``execute`` runs a single statement. SELECT returns a list of row tuples; other
    statements return an empty list. Any problem with the SQL raises :class:`SQLError`.
    """

    def __init__(self) -> None:
        self._executor = Executor()

    def execute(self, sql: str) -> list[tuple]:
        if not isinstance(sql, str):
            raise SQLError("statement must be a string")
        try:
            statement = parse(sql)
            return self._executor.execute(statement)
        except SQLError:
            raise
        except RecursionError as exc:
            raise SQLError("expression too deeply nested") from exc
        except Exception as exc:  # defensive: never leak other exception types
            raise SQLError(f"internal error: {type(exc).__name__}: {exc}") from exc
