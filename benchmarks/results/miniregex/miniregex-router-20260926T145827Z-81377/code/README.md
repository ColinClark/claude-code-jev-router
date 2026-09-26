# miniregex

Benchmark task: a regular-expression engine in pure Python.

```python
from miniregex import compile, RegexError

m = compile(r"(\w+)@(\w+)").search("mail bob@example now")
m.groups()  # ('bob', 'example')
```

A backtracking engine (`src/miniregex/`) that reproduces the `re` module's results,
including group values and spans, without using `re`. Supported: literals, `.`, escapes,
`\d \D \w \W \s \S` (Unicode, like `re`), sets, `^ $ \A \Z \b \B`, greedy and lazy
`* + ? {n} {n,} {n,m} {,m}`, `|`, `( )` and `(?: )`.

Development: `uv run pytest` and `uv run ruff check .`
