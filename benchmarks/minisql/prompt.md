Build `minisql`, an in-memory SQL database engine in pure Python, in this repository.

Setup:
- Python 3.12+, standard library only at runtime. You must NOT use `sqlite3` or any other database or SQL
  library in the implementation (tests may use `sqlite3` to compare results). Set it up as a uv project
  (pyproject.toml) with pytest and ruff as dev dependencies.
- Public API: `from minisql import Database, SQLError`. `Database().execute(sql: str) -> list[tuple]`
  runs one statement. SELECT returns its rows as tuples; other statements return `[]`. Invalid SQL, unknown
  tables or columns, and ambiguous column names raise `SQLError`.

Semantics: for everything below, results must match what SQLite returns for the same statements on the
same data: the same values (and Python types: int, float, str, None) and the same row order when ORDER BY
is given. Without ORDER BY, row order is unspecified. All values in a column have the column's declared
type or are NULL.

Statements to support:
- `CREATE TABLE name (col TYPE, ...)` with types INTEGER, REAL, TEXT.
- `INSERT INTO name [(col, ...)] VALUES (...), (...)`. Omitted columns are NULL.
- `UPDATE name SET col = expr [, ...] [WHERE expr]` and `DELETE FROM name [WHERE expr]`.
- `SELECT [DISTINCT] select_list FROM table [[AS] alias] join* [WHERE expr] [GROUP BY expr, ...]
  [HAVING expr] [ORDER BY expr [ASC|DESC], ...] [LIMIT n [OFFSET m]]`
  - select_list: `*`, `alias.*`, or expressions with optional `AS name`.
  - join: `[INNER] JOIN t [[AS] a] ON expr` or `LEFT [OUTER] JOIN t [[AS] a] ON expr`, any number of them.
  - ORDER BY may reference output column names (aliases) or expressions.
- Expressions: qualified and unqualified column references; integer, real, string ('...' with '' escape)
  and NULL literals; unary minus; `+ - * /` and `%`; `||` string concatenation; comparisons
  `= == != <> < <= > >=`; `AND OR NOT`; `IS NULL`, `IS NOT NULL`; `[NOT] IN (list)`;
  `[NOT] BETWEEN a AND b`; `[NOT] LIKE` with `%` and `_`; parentheses.
- Aggregates: `COUNT(*)`, `COUNT(expr)`, `COUNT(DISTINCT expr)`, `SUM`, `AVG`, `MIN`, `MAX`, usable in
  SELECT, HAVING and ORDER BY, with or without GROUP BY.
- Keywords are case-insensitive; identifiers are case-insensitive.

SQLite behaviors to be careful about (all must match): NULL handling and three-valued logic in every
operator and aggregate, integer vs. real arithmetic (integer division, modulo, division by zero), LIKE case
rules, NULL ordering in ORDER BY, aggregate results over empty inputs, and LEFT JOIN rows with no match.

Tests: write a thorough pytest suite (compare against `sqlite3` where useful). `uv run pytest` and
`uv run ruff check .` must pass.

When done, summarize what you built and the checks you ran, with exit codes.
