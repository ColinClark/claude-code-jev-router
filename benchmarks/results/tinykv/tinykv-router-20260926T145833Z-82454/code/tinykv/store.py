"""JSON-file backed key-value store with per-key TTL and multi-process safety.

On-disk format: ``{"key": {"v": <value>, "e": <expires_at or null>}}``.

Writers take an exclusive ``fcntl.flock`` on a sidecar ``<path>.lock`` file for the
whole read-modify-write cycle. The lock lives on a separate file because the data file
is replaced atomically (``os.replace``) on every write, which swaps its inode; a lock
held on the old inode would not exclude a writer that opened the new one.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_MISSING = object()


class Store:
    def __init__(self, path: str | os.PathLike[str], *, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self._lock_path = self.path.with_name(self.path.name + ".lock")
        self._clock = clock

    # -- public API ---------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        entry = self._load().get(key)
        if entry is None or self._expired(entry, self._clock()):
            return default
        return entry["v"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive")
        # Fail before touching the file if the value can't be stored.
        json.dumps(value)
        with self._write() as data:
            expires = None if ttl is None else self._clock() + ttl
            data[key] = {"v": value, "e": expires}

    def delete(self, key: str) -> bool:
        """Remove ``key``. Returns True if a live key was removed."""
        with self._write() as data:
            return data.pop(key, None) is not None

    def keys(self) -> list[str]:
        now = self._clock()
        return sorted(k for k, entry in self._load().items() if not self._expired(entry, now))

    def __contains__(self, key: str) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _expired(entry: dict[str, Any], now: float) -> bool:
        expires = entry.get("e")
        return expires is not None and expires <= now

    def _load(self) -> dict[str, Any]:
        # Readers don't need the lock: writers publish via atomic os.replace, so a reader
        # always sees either the previous or the next complete file.
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    @contextmanager
    def _write(self) -> Iterator[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._lock_path, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = self._load()
                # Lazy expiry: purge expired entries (before the caller's change, so a
                # delete of an expired key reports False).
                now = self._clock()
                for k in [k for k, e in data.items() if self._expired(e, now)]:
                    del data[k]
                yield data
                self._atomic_dump(data)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _atomic_dump(self, data: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
