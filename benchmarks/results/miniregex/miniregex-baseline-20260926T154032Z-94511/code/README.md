# miniregex

Benchmark task: a regular-expression engine in pure Python.

A backtracking regular-expression engine in pure Python (standard library only, no `re`),
whose results match Python's `re` module (no flags) for the supported syntax.

```python
from miniregex import compile, RegexError

m = compile(r"(\w+)@(\w+)\.com").search("mail bob@example.com")
m.group(1), m.span(2)          # ('bob', (9, 16))
compile(r"(\d)(x)?").findall("1x2")   # [('1', 'x'), ('2', '')]
```

Supported: literals, `.`, escapes, `\d \D \w \W \s \S` (Unicode, as in `re`), `\A \Z \b \B`,
sets `[...]`/`[^...]` with ranges, anchors `^ $`, greedy and lazy `* + ? {n} {n,} {n,m} {,m}`,
alternation, capturing and non-capturing groups. Backreferences, lookarounds, named groups,
inline flags and possessive quantifiers raise `RegexError`.

Development: `uv run pytest` and `uv run ruff check .`. The test suite includes differential
fuzzing against `re`.
