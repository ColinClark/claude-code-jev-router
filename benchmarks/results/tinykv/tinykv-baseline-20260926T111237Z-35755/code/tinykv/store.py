"""Persistent JSON-backed key-value store with per-key TTL.

Layout on disk: ``{"key": {"v": <value>, "e": <expires_at epoch seconds or null>}}``.

Writes take an exclusive ``fcntl.flock`` on a sidecar ``<path>.lock`` file for the
whole read-modify-write cycle, then atomically replace the data file. The lock lives
on a separate file because ``os.replace`` swaps the data file's inode, so a lock held
on the data file itself would not serialize writers. Reads need no lock: the data
file is only ever replaced atomically, so readers always see a complete snapshot.
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
    def __init__(self, path: str | os.PathLike[str], *, clock: Callable[[], float] = time.time):
        self.path = os.fspath(path)
        self.lock_path = self.path + ".lock"
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
        json.dumps(value)  # fail fast on non-serializable values, before taking the lock
        with self._write() as (data, now):
            data[key] = {"v": value, "e": None if ttl is None else now + ttl}

    def delete(self, key: str) -> bool:
        """Delete ``key``; return True if a live key was removed."""
        with self._write() as (data, _now):
            return data.pop(key, None) is not None

    def keys(self) -> list[str]:
        now = self._clock()
        return sorted(k for k, e in self._load().items() if not self._expired(e, now))

    def __contains__(self, key: str) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _expired(entry: dict[str, Any], now: float) -> bool:
        exp = entry.get("e")
        return exp is not None and exp <= now

    def _load(self) -> dict[str, Any]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"corrupt tinykv database: {self.path}")
        return data

    @contextmanager
    def _write(self) -> Iterator[tuple[dict[str, Any], float]]:
        """Exclusive read-modify-write. Expired keys are purged before the caller runs."""
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        with open(self.lock_path, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                now = self._clock()
                data = {k: e for k, e in self._load().items() if not self._expired(e, now)}
                yield data, now
                self._atomic_dump(data, directory)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _atomic_dump(self, data: dict[str, Any], directory: str) -> None:
        fd, tmp = tempfile.mkstemp(prefix=".tinykv-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
