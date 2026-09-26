# minisql

An in-memory SQL database engine in pure Python (standard library only) whose results match SQLite.

```python
from minisql import Database, SQLError

db = Database()
db.execute("CREATE TABLE t (id INTEGER, name TEXT, score REAL)")
db.execute("INSERT INTO t VALUES (1, 'a', 2.5), (2, 'b', NULL)")
db.execute("SELECT name, score FROM t WHERE score IS NOT NULL ORDER BY id")  # [('a', 2.5)]
```

Supports CREATE TABLE / INSERT / UPDATE / DELETE and SELECT with DISTINCT, inner and left joins,
WHERE, GROUP BY, HAVING, ORDER BY, LIMIT/OFFSET, aggregates (COUNT, SUM, AVG, MIN, MAX, TOTAL,
GROUP_CONCAT), CASE and a few scalar functions, following SQLite's type affinity, NULL and
arithmetic rules.

Layout: `src/minisql/tokenizer.py` → `parser.py` (AST) → `engine.py` (name resolution, compilation
to closures, execution); `values.py` holds SQLite value semantics.

```sh
uv run pytest        # differential tests against sqlite3, including a random query fuzzer
uv run ruff check .
```

The Python version is pinned in `.python-version` (3.12). Float-to-text formatting follows the
SQLite bundled with it (3.47, `%.15g`); SQLite 3.49 and later format floats with more digits.
