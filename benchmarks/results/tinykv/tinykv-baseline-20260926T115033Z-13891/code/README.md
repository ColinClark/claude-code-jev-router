# tinykv

A small persistent key-value store: one JSON file, per-key TTLs, atomic writes and
`fcntl` file locking so several processes can write at once without losing updates.
Python 3.12+, standard library only at runtime.

## Library

```python
from tinykv import Store

s = Store("data.json")
s.set("greeting", {"text": "hi"})
s.set("session", "abc123", ttl=60)  # seconds; expired keys are never returned
s.get("greeting")  # {'text': 'hi'}
s.get("missing", default=None)
s.keys()  # sorted live keys
s.delete("greeting")  # True if a live key was removed
```

Expiry is lazy: reads skip expired keys, and the next write drops them from disk.
Every write locks `<path>.lock` exclusively, re-reads the file, applies the change and
replaces the file atomically (temp file in the same directory + `os.replace`).

## CLI

```sh
python -m tinykv --db data.json set KEY VALUE [--ttl SECONDS]
python -m tinykv --db data.json get KEY      # exit 1 if missing or expired
python -m tinykv --db data.json del KEY
python -m tinykv --db data.json keys
```

`VALUE` is parsed as JSON when possible (`42`, `true`, `'{"a": 1}'`), otherwise stored
as a string. `get` prints strings verbatim and other values as JSON.

## Development

```sh
uv sync
uv run pytest
uv run ruff check .
```
