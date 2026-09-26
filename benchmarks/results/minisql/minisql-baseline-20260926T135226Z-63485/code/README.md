# minisql

An in-memory SQL database engine in pure Python (standard library only) whose results
match SQLite's for the supported subset.

```python
from minisql import Database, SQLError

db = Database()
db.execute("CREATE TABLE emp (id INTEGER, name TEXT, salary REAL)")
db.execute("INSERT INTO emp VALUES (1, 'Ada', 120.5), (2, 'Bob', NULL)")
db.execute("SELECT name, salary FROM emp ORDER BY salary DESC")  # [('Ada', 120.5), ('Bob', None)]
```

`Database().execute(sql)` runs one statement. SELECT returns a list of tuples; other
statements return `[]`. Invalid SQL, unknown tables/columns and ambiguous names raise `SQLError`.

## Supported SQL

- `CREATE TABLE` (INTEGER / REAL / TEXT, SQLite type-affinity rules), `DROP TABLE`
- `INSERT INTO t [(cols)] VALUES (...), ...` and `INSERT ... SELECT`
- `UPDATE ... SET ... [WHERE]`, `DELETE FROM ... [WHERE]`
- `SELECT [DISTINCT] ... FROM t [AS a]` with any number of `[INNER] JOIN`, `LEFT [OUTER] JOIN`,
  `CROSS JOIN` or comma joins, `WHERE`, `GROUP BY`, `HAVING`, `ORDER BY` (expressions, output
  aliases, column positions), `LIMIT n [OFFSET m]` / `LIMIT m, n`
- Expressions: column references, literals, arithmetic, `||`, comparisons, `AND/OR/NOT`,
  `IS [NOT] NULL`, `IS [NOT]`, `[NOT] IN (list)`, `[NOT] BETWEEN`, `[NOT] LIKE [ESCAPE]`,
  `CASE`, `CAST`, and the functions `abs coalesce ifnull nullif length lower upper typeof`
  and multi-argument `min`/`max`
- Aggregates: `COUNT(*)`, `COUNT/SUM/AVG/MIN/MAX/TOTAL([DISTINCT] expr)`

Not supported: subqueries, `USING`/`NATURAL` joins, constraints, indexes, transactions.

## Layout

- `src/minisql/lexer.py`, `parser.py`, `ast.py` - tokenizer and recursive-descent parser
- `src/minisql/values.py` - SQLite value semantics (affinity, arithmetic, ordering, LIKE)
- `src/minisql/aggregates.py` - aggregate accumulators (SQLite's summation algorithm)
- `src/minisql/engine.py` - name resolution, expression compilation and execution

## Development

```sh
uv run pytest        # includes differential tests against the stdlib sqlite3 module
uv run ruff check .
```

REAL-to-TEXT conversion follows SQLite's classic `%!.15g` rendering (SQLite <= 3.47);
newer SQLite releases render some values with up to 17 significant digits.
