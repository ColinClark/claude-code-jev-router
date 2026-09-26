"""A small persistent JSON-backed key-value store with TTL support.

The store is a single JSON file mapping ``key -> {"value": ..., "expires_at": float | null}``.
Writes are atomic (temp file in the same directory + ``os.replace``) and every
read-modify-write is serialized across processes with an exclusive ``fcntl.flock``
on a sibling ``<path>.lock`` file. A separate lock file is used because
``os.replace`` swaps the store file's inode, so locking the store file itself
would not serialize writers that open it after a replace.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any


class Store:
    """Persistent JSON key-value store with optional per-key TTL."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    # -- internal helpers -------------------------------------------------

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            with open(self.path, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            return {}
        if not text.strip():
            return {}
        data = json.loads(text)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _expired(entry: dict[str, Any], now: float) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and expires_at <= now

    def _live(self) -> dict[str, dict[str, Any]]:
        now = time.time()
        return {k: e for k, e in self._read().items() if not self._expired(e, now)}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
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
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)  # closing the fd releases the flock

    # -- public API -------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        entry = self._read().get(key)
        if entry is None or self._expired(entry, time.time()):
            return default
        return entry.get("value")

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        json.dumps(value)  # fail fast on non-serializable values, before locking
        with self._locked():
            data = self._live()
            expires_at = None if ttl is None else time.time() + ttl
            data[key] = {"value": value, "expires_at": expires_at}
            self._write(data)

    def delete(self, key: str) -> None:
        with self._locked():
            data = self._live()
            data.pop(key, None)
            self._write(data)

    def keys(self) -> list[str]:
        return list(self._live().keys())
