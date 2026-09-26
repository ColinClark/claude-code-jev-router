# minisql

Benchmark task: an in-memory SQL engine in pure Python.

## Usage

```python
from minisql import Database, SQLError

db = Database()
db.execute("CREATE TABLE t (id INTEGER, name TEXT, score REAL)")
db.execute("INSERT INTO t VALUES (1, 'a', 2.5), (2, 'b', NULL)")
db.execute("SELECT name, score FROM t WHERE score IS NOT NULL ORDER BY id")  # [('a', 2.5)]
```

Results match SQLite (values, Python types, NULL semantics, ordering). Where SQLite versions
differ (REAL-to-TEXT formatting changed after 3.47), minisql follows SQLite 3.47, the version
bundled with the project's pinned Python 3.12.

## Layout

- `src/minisql/tokenizer.py`, `parser.py`, `ast.py`: SQL text to syntax tree
- `src/minisql/values.py`: SQLite value semantics (affinity, comparison, arithmetic, LIKE)
- `src/minisql/engine.py`: expression compilation and statement execution

## Development

```sh
uv run pytest        # includes differential tests against sqlite3 and seeded fuzzing
uv run ruff check .
```
