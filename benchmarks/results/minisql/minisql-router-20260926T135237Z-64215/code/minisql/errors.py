"""Exception types for minisql."""


class SQLError(Exception):
    """Raised for any SQL error: syntax errors, unknown tables/columns, misuse, etc."""
