Build `miniregex`, a regular-expression engine in pure Python, in this repository.

Setup:
- Python 3.12+, standard library only at runtime, and you must NOT use the `re` module (or any other regex
  library) in the implementation. Tests may use `re` to compare results. Set it up as a uv project
  (pyproject.toml) with pytest and ruff as dev dependencies.
- Public API: `from miniregex import compile, RegexError`.
  - `compile(pattern: str) -> Pattern`; invalid patterns raise `RegexError`.
  - `Pattern.fullmatch(text)`, `Pattern.match(text)` (anchored at the start) and `Pattern.search(text)`
    return `None` or a `Match`.
  - `Pattern.findall(text)` returns a list like `re.findall` (whole-match strings when there are no groups;
    the group string when there is one group; tuples of groups when there are several).
  - `Match.group(n=0)`, `Match.groups()`, `Match.span(n=0)`, `Match.start(n=0)`, `Match.end(n=0)`.

Semantics: for every supported pattern and text, results must be identical to Python's `re` module with no
flags: which strings match, the overall match span, and every group's value and span (including `None` for
groups that did not participate, and the value from the *last* iteration for groups inside repetitions).

Syntax to support:
- Literals, `.` (any character except `\n`), escapes `\. \\ \* \+ \? \( \) \[ \] \{ \} \| \^ \$ \-`,
  and the classes `\d \D \w \W \s \S` (ASCII meaning is fine: `\d` = 0-9, `\w` = [A-Za-z0-9_],
  `\s` = space, tab, newline, carriage return, form feed, vertical tab).
- Character sets `[...]` with ranges, negation `[^...]`, escapes and the classes above inside sets, and a
  literal `-` at the start or end of a set, or `]` as the first character.
- Anchors `^` and `$` (no multiline; `$` also matches before a final `\n` at the end, like `re`).
- Quantifiers `* + ?` and `{n}`, `{n,}`, `{n,m}`, `{,m}`, each optionally followed by `?` (lazy).
- Alternation `|`, capturing groups `( )`, non-capturing groups `(?: )`.

Tests: write a thorough pytest suite (fuzzing against `re` is encouraged). `uv run pytest` and
`uv run ruff check .` must pass.

When done, summarize what you built and the checks you ran, with exit codes.
