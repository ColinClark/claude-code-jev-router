"""Exception types for minisql."""


class SQLError(Exception):
    """Raised for invalid SQL, unknown tables/columns and other query errors."""
