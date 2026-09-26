# router-demo

Scratch project for exercising the Claude Code smart router.

## tinykv

A small persistent key-value store (Python 3.12+, stdlib only).

```python
from tinykv import Store
s = Store("data.db.json")
s.set("k", {"any": "json"}, ttl=60)   # ttl in seconds, optional
s.get("k"); s.keys(); s.delete("k")
```

```sh
python -m tinykv --db data.db.json set KEY VALUE [--ttl SECONDS]   # VALUE parsed as JSON, else string
python -m tinykv --db data.db.json get KEY                         # exit 1 if missing/expired
python -m tinykv --db data.db.json del KEY
python -m tinykv --db data.db.json keys
```

Writes are serialized across processes with `fcntl.flock` on `<db>.lock` and committed
via temp file + `os.replace`. Expired keys are hidden on read and purged on the next write.

Dev: `uv run pytest` and `uv run ruff check .`
