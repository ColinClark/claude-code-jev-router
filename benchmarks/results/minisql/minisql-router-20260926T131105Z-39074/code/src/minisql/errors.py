"""Exception types raised by minisql."""


class SQLError(Exception):
    """Raised for invalid SQL, unknown tables/columns and other statement errors."""
