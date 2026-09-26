"""miniregex: a small regex engine compatible with a subset of Python's ``re``."""

from __future__ import annotations

from ._errors import RegexError
from ._matcher import MatchResult, Program, compile_pattern
from ._parser import parse

__all__ = ["Match", "Pattern", "RegexError", "compile"]


class Match:
    """Result of a successful match."""

    def __init__(self, text: str, result: MatchResult) -> None:
        self.string = text
        self._res = result

    def _span(self, n: int) -> tuple[int, int]:
        if n == 0:
            return (self._res.start, self._res.end)
        if not isinstance(n, int) or n < 0 or n > len(self._res.spans):
            raise IndexError("no such group")
        s = self._res.spans[n - 1]
        return (-1, -1) if s is None else s

    def group(self, n: int = 0) -> str | None:
        a, b = self._span(n)
        if a == -1:
            return None
        return self.string[a:b]

    def groups(self) -> tuple[str | None, ...]:
        return tuple(self.group(i) for i in range(1, len(self._res.spans) + 1))

    def span(self, n: int = 0) -> tuple[int, int]:
        return self._span(n)

    def start(self, n: int = 0) -> int:
        return self._span(n)[0]

    def end(self, n: int = 0) -> int:
        return self._span(n)[1]

    def __repr__(self) -> str:
        return f"<miniregex.Match object; span={self.span()!r}, match={self.group()!r}>"


class Pattern:
    """Compiled regular expression."""

    def __init__(self, program: Program) -> None:
        self._prog = program
        self.pattern = program.pattern.source
        self.groups = program.groups

    def _run(self, text: str, mode: str) -> Match | None:
        r = self._prog.run(text, mode=mode)
        return None if r is None else Match(text, r)

    def fullmatch(self, text: str) -> Match | None:
        return self._run(text, "fullmatch")

    def match(self, text: str) -> Match | None:
        return self._run(text, "match")

    def search(self, text: str) -> Match | None:
        return self._run(text, "search")

    def findall(self, text: str) -> list:
        out: list = []
        pos = 0
        must_advance = False
        n = len(text)
        while pos <= n:
            r = self._prog.run(text, pos, mode="search", must_advance=must_advance)
            if r is None:
                break
            if self.groups == 0:
                out.append(text[r.start : r.end])
            else:
                vals = tuple("" if s is None else text[s[0] : s[1]] for s in r.spans)
                out.append(vals[0] if self.groups == 1 else vals)
            must_advance = r.end == r.start
            pos = r.end
        return out

    def __repr__(self) -> str:
        return f"miniregex.compile({self.pattern!r})"


def compile(pattern: str) -> Pattern:
    """Parse and compile ``pattern``; raises ``RegexError`` if invalid."""
    return Pattern(compile_pattern(parse(pattern)))
