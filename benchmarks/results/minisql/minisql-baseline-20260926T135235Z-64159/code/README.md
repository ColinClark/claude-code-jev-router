# minisql

An in-memory SQL database engine in pure Python (standard library only) whose results match
SQLite's for the supported subset.

```python
from minisql import Database, SQLError

db = Database()
db.execute("CREATE TABLE emp (id INTEGER, name TEXT, salary REAL)")
db.execute("INSERT INTO emp VALUES (1, 'Ada', 5000.0), (2, 'Bob', NULL)")
db.execute("SELECT name, coalesce(salary, 0) FROM emp ORDER BY name")
# [('Ada', 5000.0), ('Bob', 0)]
```

`Database.execute(sql)` runs one statement. SELECT returns rows as tuples; other statements
return `[]`. Invalid SQL, unknown tables or columns and ambiguous column names raise `SQLError`.

## Supported SQL

- `CREATE TABLE t (col TYPE, ...)` (INTEGER, REAL, TEXT; other names get SQLite's type
  affinity), `DROP TABLE`.
- `INSERT INTO t [(cols)] VALUES (...), ...` and `INSERT INTO t [(cols)] SELECT ...`.
- `UPDATE t SET col = expr, ... [WHERE ...]`, `DELETE FROM t [WHERE ...]`.
- `SELECT [DISTINCT] ... FROM t [[AS] a] [INNER|LEFT [OUTER]|CROSS] JOIN ... ON ...`
  (also comma joins), `WHERE`, `GROUP BY`, `HAVING`, `ORDER BY expr|alias|position [ASC|DESC]`,
  `LIMIT n [OFFSET m]` / `LIMIT m, n`.
- Expressions: literals, qualified/unqualified columns, `+ - * / %`, unary `-`/`+`, `||`,
  `= == != <> < <= > >=`, `AND OR NOT`, `IS [NOT]`, `IS [NOT] NULL`, `[NOT] IN (...)`,
  `[NOT] BETWEEN`, `[NOT] LIKE`, `CASE`, `CAST`.
- Aggregates: `COUNT(*)`, `COUNT([DISTINCT] x)`, `SUM`, `AVG`, `MIN`, `MAX`, `TOTAL`,
  `GROUP_CONCAT`. Scalar functions: `abs coalesce ifnull nullif length lower upper typeof
  substr round min max`.

SQLite semantics are reproduced for: type affinity on storage and in comparisons, NULL and
three-valued logic, integer vs. real arithmetic (truncating division, C-style modulo, NULL on
division by zero, overflow to REAL), ASCII-only case-insensitive LIKE, NULLs first in ascending
order, numbers before text, aggregates over empty input, SUM integer overflow errors, and
LEFT JOIN NULL padding.

## Layout

- `src/minisql/tokenizer.py`, `parser.py`, `ast.py`: SQL text to syntax tree.
- `src/minisql/values.py`: value semantics (affinity, comparison, arithmetic, REAL-to-text).
- `src/minisql/engine.py`: name resolution, expression compilation to closures, execution.

## Development

```sh
uv run pytest        # unit tests plus differential tests against sqlite3
uv run ruff check .
```

## Known differences

- REAL-to-text conversion (`||`, storing a REAL in a TEXT column) follows SQLite 3.47's
  `%!.15g` algorithm (the version bundled with the pinned Python). Newer SQLite releases print up
  to 17 digits for values that do not round-trip at 15 digits.
- Row order without ORDER BY, and the choice among tied or duplicate rows, is unspecified.
