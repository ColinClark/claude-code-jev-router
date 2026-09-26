# minisql

Benchmark task: an in-memory SQL engine in pure Python.

## Usage

```python
from minisql import Database, SQLError

db = Database()
db.execute("CREATE TABLE t (id INTEGER, name TEXT)")
db.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b')")
db.execute("SELECT name FROM t WHERE id > 1 ORDER BY name")  # [('b',)]
```

Pure standard-library Python (no `sqlite3` at runtime). Results follow SQLite semantics
(type affinity, NULL logic, integer division, sort order); the test suite compares every
query against `sqlite3`.

## Development

```sh
uv sync
uv run pytest -q
uv run ruff check .
```
