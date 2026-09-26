Build `tinykv`, a small persistent key-value store, in this repository.

Requirements:
- Python 3.12+, standard library only at runtime. Set it up as a uv project (pyproject.toml) with pytest and ruff as dev dependencies.
- Library `tinykv/store.py` with a `Store(path)` class: `get`, `set(key, value, ttl=None)`, `delete`, `keys()`. Values are JSON-serializable.
- Per-key TTL in seconds with lazy expiry: expired keys are never returned and are dropped on the next write.
- Persistence to a JSON file with atomic writes (write a temp file in the same directory, then os.replace).
- Safe with concurrent writers from multiple processes: use an exclusive file lock (fcntl) around read-modify-write so no update is lost.
- CLI: `python -m tinykv --db PATH set KEY VALUE [--ttl SECONDS]`, `get KEY`, `del KEY`, `keys`. `get` on a missing or expired key exits with status 1.
- pytest tests covering: basic CRUD, TTL expiry (without real sleeps where possible), persistence across Store instances, a multi-process concurrency test proving no lost updates, and the CLI.
- `uv run pytest` and `uv run ruff check .` must pass.

When done, summarize what you built and the checks you ran, with exit codes.
