Customers reported the problems described in ISSUE.md against the `billing` package in this repository.

Fix them, and make sure the whole `billing` package conforms to docs/SPEC.md, which is the source of truth
for its behavior. Keep the public API unchanged. Add regression tests for every bug you fix.
`uv run pytest` and `uv run ruff check .` must pass.

When done, list each bug you found and fixed, and the checks you ran with exit codes.
