# miniregex

Benchmark task: a regular-expression engine in pure Python.

## Usage

```python
from miniregex import compile, RegexError

p = compile(r"(\w+)@(\w+)\.com")
m = p.search("mail bob@example.com now")
m.group(1), m.span(2)          # ('bob', (9, 16))
p.findall("a@b.com c@d.com")   # [('a', 'b'), ('c', 'd')]
```

`Pattern` offers `match`, `fullmatch`, `search`, `findall` and `finditer`; `Match` offers
`group`, `groups`, `span`, `start` and `end`. Results are identical to Python's `re` module
(no flags) for all supported syntax: literals and escapes, `.`, `\d \D \w \W \s \S`
(Unicode semantics, as in `re`), sets, anchors `^ $ \A \Z \b \B`, greedy and lazy quantifiers,
alternation, capturing and non-capturing groups and backreferences. Lookarounds, named groups,
inline flags, atomic groups and possessive quantifiers raise `RegexError`.

The engine is a backtracking matcher compiled to closures that mirrors CPython's `_sre`
semantics (including capture bookkeeping and empty-iteration handling). The `re` module is
never imported by the package.

## Development

```sh
uv sync
uv run pytest -q
uv run ruff check .
```
