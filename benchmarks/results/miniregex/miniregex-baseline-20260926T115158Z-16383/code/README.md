# miniregex

Benchmark task: a regular-expression engine in pure Python.

`miniregex` is a backtracking regex engine written in pure Python (standard library only, no
`re`). Its compiler and matcher follow CPython's `_sre` design, so match spans and capture
groups are identical to `re` for the supported syntax: literals, `.`, escapes, `\d \D \w \W
\s \S`, character sets, `^`/`$`, greedy and lazy `* + ? {n} {n,} {n,m} {,m}`, `|`, `( )` and
`(?: )`.

```python
from miniregex import compile, RegexError

m = compile(r"(\w+)@(\w+)\.com").search("mail bob@example.com")
m.group(1), m.span(2)  # ('bob', (9, 16))
compile(r"(\d)(x)?").findall("1x2")  # [('1', 'x'), ('2', '')]
```

Development: `uv run pytest` and `uv run ruff check .`.
