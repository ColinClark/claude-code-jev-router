# miniregex

Benchmark task: a regular-expression engine in pure Python.

A backtracking regex engine (standard library only, no `re`) whose results — match spans,
group values and group spans — are identical to Python's `re` for the supported syntax.

```python
from miniregex import compile, RegexError

m = compile(r"(\w+)@(\w+)").search("mail bob@example now")
m.groups()   # ('bob', 'example')
m.span(2)    # (9, 16)
```

Supported: literals, `.`, escapes, `\d \D \w \W \s \S` (ASCII), sets `[...]`/`[^...]`, `^`, `$`,
`* + ? {n} {n,} {,m} {n,m}` (plus lazy `?` variants), `|`, `( )`, `(?: )`.
Anything else (lookarounds, backreferences, `\b`, flags, named groups, possessive quantifiers)
raises `RegexError`.

Design: `_parser.py` builds a syntax tree shaped like CPython's `re._parser` output;
`_engine.py` compiles it to `_sre`-style opcodes and runs a backtracking matcher that reproduces
`_sre`'s capture-save/restore and zero-width-iteration rules, using an explicit context stack so
long inputs don't hit Python's recursion limit.

```sh
uv run pytest          # includes seeded differential fuzzing against re
uv run ruff check .
```
