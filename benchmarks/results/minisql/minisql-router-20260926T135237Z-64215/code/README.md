# minisql

Benchmark task: an in-memory SQL engine in pure Python.

## Usage

```python
from minisql import Database, SQLError

db = Database()
db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
db.execute("INSERT INTO t VALUES (1, 'x'), (2, NULL)")
db.execute("SELECT a, b FROM t ORDER BY a DESC")  # [(2, None), (1, 'x')]
```

Pure Python (standard library only). Supports CREATE/DROP TABLE, INSERT (VALUES or SELECT),
UPDATE, DELETE and SELECT with DISTINCT, inner/left/cross joins, WHERE, GROUP BY, HAVING,
ORDER BY (expressions, aliases, positions, NULLS FIRST/LAST), LIMIT/OFFSET, aggregates and a
set of scalar functions, following SQLite's typing, affinity and NULL semantics.

REAL-to-text conversion follows SQLite <= 3.50 (`%!.15g`) by default;
`minisql.values.set_real_text_mode("roundtrip")` approximates newer SQLite releases.

## Development

```sh
uv sync
uv run pytest -q      # differential tests against sqlite3
uv run ruff check .
```
