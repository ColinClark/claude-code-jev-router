# minisql

An in-memory SQL database engine in pure Python (standard library only), with semantics
matched against SQLite.

```python
from minisql import Database, SQLError

db = Database()
db.execute("CREATE TABLE t (id INTEGER, name TEXT, score REAL)")
db.execute("INSERT INTO t VALUES (1, 'a', 1.5), (2, 'b', NULL)")
db.execute("SELECT name, score FROM t WHERE score IS NOT NULL ORDER BY id")  # [('a', 1.5)]
```

Development: `uv run pytest` and `uv run ruff check .`. Set `MINISQL_FUZZ_ITERATIONS` to run
more randomized differential tests against `sqlite3`.
