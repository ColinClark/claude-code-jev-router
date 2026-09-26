# minisql

Benchmark task: an in-memory SQL engine in pure Python.

## Usage

```python
from minisql import Database, SQLError

db = Database()
db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
db.execute("INSERT INTO t VALUES (1, 'x'), (2, NULL)")
db.execute("SELECT a, b FROM t ORDER BY a")  # [(1, 'x'), (2, None)]
```

Development: `uv sync`, then `uv run pytest -q` (differential tests against the stdlib
`sqlite3` module) and `uv run ruff check .`.
