# router-demo

Scratch project for exercising the Claude Code smart router.

## tinykv usage

```sh
uv sync
uv run python -m tinykv --db data.db.json set greeting hello
uv run python -m tinykv --db data.db.json set counter 3 --ttl 60
uv run python -m tinykv --db data.db.json get greeting   # exits 1 if missing/expired
uv run python -m tinykv --db data.db.json keys
uv run python -m tinykv --db data.db.json del greeting
```

Run checks with `uv run pytest` and `uv run ruff check .`.
