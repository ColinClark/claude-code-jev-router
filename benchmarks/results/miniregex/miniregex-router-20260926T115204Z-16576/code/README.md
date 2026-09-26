# miniregex

Benchmark task: a regular-expression engine in pure Python.

`miniregex` is a standard-library-only backtracking regex engine whose results
are identical to CPython's `re` (no flags) for every supported pattern: which
strings match, the overall span, and every group's value and span, including
`re`'s quirks around non-participating groups, captures inside repetitions and
empty iterations of unbounded repeats. It never imports `re`.

## Usage

```python
from miniregex import compile, RegexError

p = compile(r"(a|b)*c")
m = p.match("abc")          # anchored at the start; None if no match
m.span(), m.group(1)        # ((0, 3), 'b')  -- last iteration wins, like re

p.search("xxabc").span()    # (2, 5)
p.fullmatch("ab")           # None (must consume the whole text)
compile(r"a*").findall("baaa")   # ['', 'aaa', '']  -- re's empty-match rules

try:
    compile("a**")
except RegexError as exc:
    print(exc)              # multiple repeat at position 2
```

`Match` supports `group(n=0)`, `groups()`, `span(n=0)`, `start(n=0)`, `end(n=0)`
and `m[n]`. A non-participating group yields `None` / `(-1, -1)`; an invalid
group index raises `IndexError`, as in `re`.

## Supported syntax

- Literals, `.` (anything but `\n`), escaped metacharacters
  (`\. \\ \* \+ \? \( \) \[ \] \{ \} \| \^ \$ \-`, any escaped non-alphanumeric),
  control escapes `\n \t \r \f \v \a`, ASCII classes `\d \D \w \W \s \S`.
- Sets `[...]`, `[^...]` with ranges, classes and escapes; `]` as first member,
  `-` as first or last member.
- Anchors `^` and `$` (no multiline; `$` also matches before a final `\n`).
- Quantifiers `* + ? {n} {n,} {,m} {n,m} {,}`, each optionally lazy (`?`).
- Alternation `|`, capturing groups `( )`, non-capturing groups `(?: )`.

Anything `re` rejects raises `RegexError`. Constructs `re` accepts but this
engine does not implement (lookarounds, named groups, backreferences,
possessive quantifiers, atomic groups, inline flags, `\b \B \A \Z`, `\x..`,
`\u....`, octal escapes) also raise `RegexError` rather than misbehaving.

## Design

- `_parser.py`: recursive-descent parser producing a tuple AST; mirrors
  `sre_parse` on edge cases (`{` that is not a quantifier is a literal,
  "nothing to repeat" vs "multiple repeat", set parsing rules).
- `_compiler.py`: compiles the AST to a flat instruction list
  (CHAR/ANY/SET/BOL/EOL/SPLIT/JMP/SAVE/REPEAT/UNTIL/MATCH).
- `_engine.py`: backtracking VM with an explicit choice-point stack (no
  recursion, so text length never hits the Python recursion limit). Captures
  and repeat counters are immutable values saved in each choice point, and
  `REPEAT`/`UNTIL` reproduce sre's `MAX_UNTIL`/`MIN_UNTIL` control flow
  including its "stop after an empty iteration" rule.

## Development

```sh
uv run pytest -q
uv run ruff check .
```
