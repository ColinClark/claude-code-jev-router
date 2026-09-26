"""Exception shared by the parser and matcher (re-exported by the public API)."""

from __future__ import annotations


class RegexError(Exception):
    """Invalid pattern (or internal matching failure).

    ``msg`` is the bare message, ``pattern`` the offending pattern (if known) and
    ``pos`` the index in the pattern where the problem was detected (if known).
    """

    def __init__(self, msg: str, pattern: str | None = None, pos: int | None = None) -> None:
        self.msg = msg
        self.pattern = pattern
        self.pos = pos
        if pattern is not None and pos is not None:
            msg = f"{msg} at position {pos}"
        super().__init__(msg)
