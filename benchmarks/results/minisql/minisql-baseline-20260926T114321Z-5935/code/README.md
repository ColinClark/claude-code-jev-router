# minisql

Benchmark task: an in-memory SQL engine in pure Python.

```python
from minisql import Database, SQLError

db = Database()
db.execute("CREATE TABLE t (id INTEGER, name TEXT, score REAL)")
db.execute("INSERT INTO t VALUES (1, 'a', 1.5), (2, 'b', NULL)")
db.execute("SELECT name, score FROM t WHERE id > 1 ORDER BY name")  # [('b', None)]
```

Results aim to match SQLite exactly (values, Python types and ORDER BY order), including
type affinity, integer/real arithmetic, three-valued logic, LIKE case rules, NULL ordering and
aggregate edge cases. Only the standard library is used at runtime.

## Layout

- `src/minisql/lexer.py`, `parser.py`, `ast.py`: tokenizer and recursive-descent parser.
- `src/minisql/values.py`: SQLite value semantics (affinity, conversions, arithmetic, comparison, LIKE).
- `src/minisql/compiler.py`: compiles expressions to Python closures; name resolution.
- `src/minisql/aggregates.py`: aggregate functions (SQLite's compensated SUM, bare-column rules).
- `src/minisql/engine.py`: `Database` and statement execution (nested-loop and hash joins).

## Development

```sh
uv run pytest
uv run ruff check .
```

Most tests run each statement on both minisql and `sqlite3` and compare results, including
randomized differential tests.

REAL-to-TEXT conversion (e.g. `1.5 || ''`) uses SQLite's classic `%!.15g` format, as in the
SQLite 3.47 bundled with the pinned Python 3.12. Some newer SQLite builds print more digits;
the formatting test skips itself when run against such a build.
