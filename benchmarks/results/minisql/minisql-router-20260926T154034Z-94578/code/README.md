# minisql

An in-memory SQL database engine in pure Python (standard library only), matching SQLite's
results for the supported subset.

```python
from minisql import Database, SQLError

db = Database()
db.execute("CREATE TABLE t (id INTEGER, name TEXT, score REAL)")
db.execute("INSERT INTO t VALUES (1, 'a', 2.5), (2, 'b', NULL)")
db.execute("SELECT name, score FROM t ORDER BY score DESC")  # [('a', 2.5), ('b', None)]
```

Supported: `CREATE TABLE`, `INSERT ... VALUES`, `UPDATE`, `DELETE`, and `SELECT [DISTINCT]` with
`[INNER] JOIN` / `LEFT [OUTER] JOIN`, `WHERE`, `GROUP BY`, `HAVING`, `ORDER BY`, `LIMIT/OFFSET`;
aggregates `COUNT/SUM/AVG/MIN/MAX` (plus `TOTAL`, `GROUP_CONCAT`) and a few scalar functions
(`ABS`, `LOWER`, `UPPER`, `LENGTH`, `TYPEOF`, `COALESCE`, `IFNULL`, `NULLIF`, `CASE`).

Layout: `tokenizer.py` → `parser.py` (AST in `ast.py`) → `engine.py` (name resolution, closure
compilation, joins, grouping, ordering); SQLite value semantics live in `values.py` and
`aggregates.py`.

REAL-to-TEXT conversion follows SQLite 3.47 (`%!.15g`), the version bundled with the project's
Python 3.12 interpreter; newer SQLite releases render some floats with up to 17 digits.

## Development

```sh
uv run pytest       # includes differential tests and a seeded fuzzer against sqlite3
uv run ruff check .
```
