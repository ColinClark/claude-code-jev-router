"""A small persistent JSON key-value store with per-key TTLs.

On-disk format: a JSON object mapping each key to
``{"value": <json>, "expires_at": <unix seconds> | null}``.

Writes take an exclusive ``fcntl`` lock on a sidecar ``<path>.lock`` file,
re-read the current file, apply the change and atomically replace the data
file. The lock lives on a separate file because ``os.replace`` swaps the data
file's inode, which would make a lock held on the data file itself useless.
Reads need no lock: thanks to the atomic replace they always see a complete
snapshot.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from typing import Any


class Store:
    def __init__(self, path: str | os.PathLike[str], clock: Callable[[], float] = time.time):
        self.path = os.fspath(path)
        self.lock_path = self.path + ".lock"
        self._clock = clock

    # -- public API ---------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for ``key``, or ``default`` if missing or expired."""
        entry = self._load().get(key)
        if entry is None or self._expired(entry, self._clock()):
            return default
        return entry["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store ``value`` under ``key``; expire it after ``ttl`` seconds if given."""
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive")
        # Fail before touching the file if the value isn't JSON-serializable.
        json.dumps(value)
        with self._write() as (data, now):
            data[key] = {"value": value, "expires_at": None if ttl is None else now + ttl}

    def delete(self, key: str) -> bool:
        """Remove ``key``. Return True if a live (non-expired) key was removed."""
        with self._write() as (data, now):
            entry = data.pop(key, None)
            return entry is not None and not self._expired(entry, now)

    def keys(self) -> list[str]:
        """Return the live keys, sorted."""
        now = self._clock()
        return sorted(k for k, e in self._load().items() if not self._expired(e, now))

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _expired(entry: dict[str, Any], now: float) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and expires_at <= now

    def _load(self) -> dict[str, Any]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    @contextlib.contextmanager
    def _write(self) -> Iterator[tuple[dict[str, Any], float]]:
        """Locked read-modify-write; expired entries are purged before saving."""
        with open(self.lock_path, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = self._load()
                now = self._clock()
                for k in [k for k, e in data.items() if self._expired(e, now)]:
                    del data[k]
                yield data, now
                self._save(data)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _save(self, data: dict[str, Any]) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tinykv-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise
