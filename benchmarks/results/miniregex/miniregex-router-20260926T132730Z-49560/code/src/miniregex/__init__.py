"""miniregex: a pure-Python backtracking regex engine compatible with a subset of ``re``.

Public API::

    from miniregex import compile, RegexError
"""

from .errors import RegexError
from .matcher import Match, Pattern, compile

__all__ = ["compile", "Match", "Pattern", "RegexError"]
