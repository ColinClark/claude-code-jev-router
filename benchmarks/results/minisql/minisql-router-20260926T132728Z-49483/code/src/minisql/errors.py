"""Exception types for minisql."""


class SQLError(Exception):
    """Raised for any SQL error: syntax, unknown table/column, ambiguity, misuse."""
