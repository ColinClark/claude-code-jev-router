"""miniregex: a pure-Python regex engine with CPython ``re``-compatible semantics.

    >>> from miniregex import compile, RegexError
    >>> m = compile(r"(a|b)*c").match("abc")
    >>> m.span(), m.group(1)
    ((0, 3), 'b')
"""

from ._engine import Match, Pattern, compile
from ._errors import RegexError

__all__ = ["Match", "Pattern", "RegexError", "compile"]
