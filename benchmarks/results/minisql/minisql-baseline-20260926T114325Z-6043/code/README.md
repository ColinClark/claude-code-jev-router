# minisql

Benchmark task: an in-memory SQL engine in pure Python.

```python
from minisql import Database, SQLError

db = Database()
db.execute("CREATE TABLE t (id INTEGER, name TEXT, score REAL)")
db.execute("INSERT INTO t VALUES (1, 'a', 2.5), (2, 'b', NULL)")
db.execute("SELECT name, score FROM t WHERE score IS NOT NULL ORDER BY id")  # [('a', 2.5)]
```

`Database.execute(sql)` runs one statement and returns a list of tuples (empty for
non-SELECT statements). Errors raise `SQLError`. Results follow SQLite's semantics: type
affinity, NULL handling, integer/real arithmetic, comparison and ordering rules.

Supported: `CREATE TABLE` (with optional `NOT NULL`, `PRIMARY KEY`, `UNIQUE`, `DEFAULT`),
`DROP TABLE`, `INSERT`, `UPDATE`, `DELETE`, and `SELECT [DISTINCT]` with inner/left/cross joins,
`WHERE`, `GROUP BY`, `HAVING`, `ORDER BY`, `LIMIT`/`OFFSET`; aggregates `COUNT SUM AVG MIN MAX
TOTAL` (with `DISTINCT`) and scalar `ABS COALESCE IFNULL NULLIF LENGTH LOWER UPPER TYPEOF MIN MAX`.

Layout: `tokenizer.py` → `parser.py` (AST in `ast.py`) → `engine.py` (expressions are compiled
to closures over flat rows); value semantics live in `values.py`, aggregates in `aggregates.py`.

## Development

```sh
uv run pytest        # includes differential tests against sqlite3
uv run ruff check .
```

The tests compare against the `sqlite3` module of the pinned interpreter (`.python-version`,
SQLite 3.47). REAL-to-TEXT conversion mimics that version's `%!.15g` formatting; newer SQLite
releases (e.g. 3.53) render some reals with up to 17 significant digits instead.
