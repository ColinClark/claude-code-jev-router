# minisql

Benchmark task: an in-memory SQL engine in pure Python.

## Usage

```python
from minisql import Database, SQLError

db = Database()
db.execute("CREATE TABLE t (id INTEGER, name TEXT)")
db.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b')")
db.execute("SELECT name FROM t WHERE id > 1")  # [('b',)]
```

Pure Python (standard library only). Results are checked against SQLite with a
differential test harness: `uv run pytest`.
