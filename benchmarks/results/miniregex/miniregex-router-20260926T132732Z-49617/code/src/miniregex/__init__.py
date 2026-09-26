"""miniregex: a small pure-Python regular-expression engine.

Public API::

    from miniregex import compile, RegexError
"""

from .errors import RegexError
from .pattern import compile

__all__ = ["compile", "RegexError"]
