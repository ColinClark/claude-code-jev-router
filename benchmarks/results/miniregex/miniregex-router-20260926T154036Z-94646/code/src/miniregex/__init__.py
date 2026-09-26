"""miniregex: a small regular-expression engine compatible with a subset of ``re``."""

from ._api import Match, Pattern, RegexError, compile

__all__ = ["Match", "Pattern", "RegexError", "compile"]
