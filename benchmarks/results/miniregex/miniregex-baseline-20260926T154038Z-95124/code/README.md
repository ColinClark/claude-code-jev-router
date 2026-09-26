# miniregex

A regular-expression engine in pure Python (standard library only, no `re`), producing the
same results as Python's `re` module (no flags) for the supported syntax.

```python
from miniregex import compile, RegexError

m = compile(r"(\w+)@(\w+)").search("mail bob@example now")
m.group(0), m.groups(), m.span(2)   # ('bob@example', ('bob', 'example'), (9, 16))
compile(r"(\w)=(\d)?").findall("a=1 b=")   # [('a', '1'), ('b', '')]
```

## Supported syntax

- Literals, `.`, escapes of metacharacters, `\n \t \r \f \v \a`, classes `\d \D \w \W \s \S` (ASCII)
- Sets `[...]`, `[^...]` with ranges, escapes and classes; `]` first and `-` first/last are literal
- Anchors `^` and `$` (`$` also matches before a final `\n`)
- Quantifiers `* + ? {n} {n,} {n,m} {,m}` plus lazy `?` variants; a `{` that is not a valid
  quantifier is a literal, as in `re`
- Alternation `|`, capturing `( )` and non-capturing `(?: )` groups

Anything else (lookarounds, backreferences, named groups, `\b`, possessive quantifiers, flags)
raises `RegexError`.

## Design

- `_parser.py` follows CPython's `re._parser` rules for the subset, including its errors.
- `_engine.py` compiles to a small instruction set run by a backtracking VM with an explicit
  choice-point stack and an undo trail (no recursion, so long inputs are fine). Repeats follow
  `_sre`'s order and zero-width-iteration rules, so group values and spans match `re` exactly.

## Development

```sh
uv run pytest        # unit tests + differential fuzzing against re
uv run ruff check .
```
