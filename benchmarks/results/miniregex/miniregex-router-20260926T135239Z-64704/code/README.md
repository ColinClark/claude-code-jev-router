# miniregex

Benchmark task: a regular-expression engine in pure Python.

## Usage

```python
from miniregex import compile, RegexError

m = compile(r"(\w+)@(\w+)\.com").search("mail bob@example.com")
m.group(1), m.span(2)          # ('bob', (9, 16))
compile(r"\d+").findall("a1b22")  # ['1', '22']
```

Supported syntax: literals, `.`, escapes, `\d \D \w \W \s \S` (ASCII), sets `[...]`/`[^...]`,
`^`/`$`, greedy and lazy `* + ? {n} {n,} {,m} {n,m}`, `|`, `( )` and `(?: )`. Results (spans,
groups, last-iteration captures, `findall` empty-match handling) match Python's `re` with no flags.
Constructs outside this subset that `re` accepts (lookarounds, named groups, backreferences,
`\b`, possessive quantifiers, ...) raise `RegexError` with an "unsupported ..." message.

The engine is a backtracking VM (`src/miniregex/_engine.py`) that mirrors CPython's `sre`
repeat/backtracking rules, using an explicit stack so long inputs do not hit the recursion limit.

## Development

```sh
uv run pytest
uv run ruff check .
```
