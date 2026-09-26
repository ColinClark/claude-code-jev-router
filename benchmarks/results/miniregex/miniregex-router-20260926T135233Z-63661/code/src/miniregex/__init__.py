"""miniregex: a pure-Python backtracking regular-expression engine.

Semantics follow Python's ``re`` module (no flags) for the supported subset:
literals, ``.``, escapes, ``\\d \\D \\w \\W \\s \\S``, character sets, ``^``
and ``$``, greedy and lazy quantifiers (``* + ? {n} {n,} {n,m} {,m}``),
alternation, capturing and non-capturing groups.
"""

from ._errors import RegexError
from ._pattern import Match, Pattern

__all__ = ["Match", "Pattern", "RegexError", "compile"]


def compile(pattern):  # noqa: A001
    """Compile ``pattern`` into a :class:`Pattern`; raise RegexError if invalid."""
    return Pattern(pattern)
