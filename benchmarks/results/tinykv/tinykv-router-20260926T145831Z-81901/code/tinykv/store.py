"""A persistent JSON-backed key-value store with per-key TTL.

On-disk format: a JSON object mapping each key to
``{"value": <json value>, "expires_at": <unix seconds or null>}``.

Writers serialize on an exclusive ``fcntl`` lock held on a sidecar
``<path>.lock`` file for the whole read-modify-write cycle. The data file
itself is replaced atomically (temp file in the same directory, then
``os.replace``), so readers always see a complete snapshot. The lock lives on a
separate file because ``os.replace`` swaps the data file's inode, which would
make a lock held on the data file meaningless to the next opener.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

_MISSING = object()


class Store:
    def __init__(self, path: str | os.PathLike[str], clock: Callable[[], float] = time.time):
        self.path = os.fspath(path)
        self._lock_path = self.path + ".lock"
        self._clock = clock

    # Public API

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for ``key``, or ``default`` if missing or expired."""
        with self._locked(fcntl.LOCK_SH):
            entry = self._load().get(key)
        if entry is None or self._expired(entry, self._clock()):
            return default
        return entry["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store ``value`` under ``key``, expiring after ``ttl`` seconds if given."""
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive")
        json.dumps(value)  # fail fast on non-serializable values, before locking
        with self._mutate() as (data, now):
            data[key] = {"value": value, "expires_at": None if ttl is None else now + ttl}

    def delete(self, key: str) -> bool:
        """Remove ``key``. Returns True if a live key was removed."""
        with self._mutate() as (data, _now):
            return data.pop(key, None) is not None

    def keys(self) -> list[str]:
        """Return the sorted list of live (non-expired) keys."""
        with self._locked(fcntl.LOCK_SH):
            data = self._load()
        now = self._clock()
        return sorted(k for k, e in data.items() if not self._expired(e, now))

    def __contains__(self, key: str) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    # Internals

    @staticmethod
    def _expired(entry: dict[str, Any], now: float) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and expires_at <= now

    @contextmanager
    def _locked(self, mode: int) -> Iterator[None]:
        with open(self._lock_path, "a") as lock_file:
            fcntl.flock(lock_file, mode)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    @contextmanager
    def _mutate(self) -> Iterator[tuple[dict[str, Any], float]]:
        """Read-modify-write under the exclusive lock, dropping expired keys."""
        with self._locked(fcntl.LOCK_EX):
            now = self._clock()
            data = {k: e for k, e in self._load().items() if not self._expired(e, now)}
            yield data, now
            self._write(data)

    def _load(self) -> dict[str, Any]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tinykv-", suffix=".tmp")
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
