# tinykv

A small persistent key-value store: one JSON file, per-key TTL, atomic writes,
and an exclusive `fcntl` lock so concurrent writers in separate processes never
lose updates. Standard library only at runtime; Python 3.12+.

## Library

```python
from tinykv import Store

s = Store("data.db.json")
s.set("name", "alice")
s.set("session", {"id": 7}, ttl=60)   # seconds
s.get("name")                          # "alice"
s.get("missing", default=None)
s.keys()                               # live keys only
s.delete("name")
s.update("hits", lambda n: n + 1, default=0)  # atomic read-modify-write
```

Expired keys are never returned and are dropped from the file on the next write.
Every write goes to a temp file in the same directory followed by `os.replace`,
and every read-modify-write holds an exclusive lock on `<path>.lock`.

## CLI

```
python -m tinykv --db PATH set KEY VALUE [--ttl SECONDS]
python -m tinykv --db PATH get KEY      # exit 1 if missing or expired
python -m tinykv --db PATH del KEY
python -m tinykv --db PATH keys
```

`VALUE` is parsed as JSON when possible (`42`, `true`, `{"a":1}`), otherwise
stored as a string.

## Development

```
uv sync
uv run pytest
uv run ruff check .
```
