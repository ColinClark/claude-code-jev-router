"""miniregex: a small regular-expression engine, pure Python, no `re`."""

from ._engine import Match, Pattern, compile
from ._errors import RegexError

__all__ = ["compile", "RegexError", "Pattern", "Match"]
