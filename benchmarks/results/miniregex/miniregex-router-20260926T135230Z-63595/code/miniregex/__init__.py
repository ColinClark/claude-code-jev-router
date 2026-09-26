"""miniregex: a pure-Python regular-expression engine compatible with ``re``.

Only the standard library is used, and the ``re`` module is not.
"""

from ._errors import RegexError
from ._pattern import Match, Pattern, compile

__all__ = ["Match", "Pattern", "RegexError", "compile"]
