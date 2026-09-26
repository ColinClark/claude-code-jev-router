"""Exception types for miniregex."""


class RegexError(Exception):
    """Raised when a pattern cannot be compiled."""

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None) -> None:
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)
