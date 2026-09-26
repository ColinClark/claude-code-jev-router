"""Exception types for minisql."""


class SQLError(Exception):
    """Raised for any SQL-level error: syntax, unknown names, bad statements."""
