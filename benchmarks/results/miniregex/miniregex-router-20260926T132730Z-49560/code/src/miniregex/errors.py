"""Exception type raised for malformed patterns."""

from __future__ import annotations


class RegexError(Exception):
    """Raised when a pattern cannot be compiled.

    Attributes:
        msg: the unformatted error message.
        pattern: the pattern being compiled (may be None).
        pos: index into the pattern where the error was detected (may be None).
    """

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None) -> None:
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)
