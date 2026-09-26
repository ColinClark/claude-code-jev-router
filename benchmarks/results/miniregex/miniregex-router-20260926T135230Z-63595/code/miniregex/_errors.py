"""Exception type raised for invalid patterns."""

from __future__ import annotations


class RegexError(Exception):
    """Raised when a pattern is not a valid regular expression."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None) -> None:
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pattern is not None and pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)
