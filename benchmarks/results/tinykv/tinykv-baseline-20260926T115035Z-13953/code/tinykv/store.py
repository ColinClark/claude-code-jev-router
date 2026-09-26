"""Persistent JSON-backed key-value store with per-key TTL and multi-process safety."""

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
    """A small persistent key-value store.

    Data lives in a single JSON file. Every write is atomic (temp file plus
    ``os.replace``) and every read-modify-write runs under an exclusive
    ``fcntl`` lock on a sidecar lock file, so concurrent writers in separate
    processes never lose updates.

    Each key has an optional expiry timestamp. Expired keys are never returned
    and are physically removed on the next write.
    """

    def __init__(self, path: str | os.PathLike[str], *, clock: Callable[[], float] = time.time):
        self.path = os.fspath(path)
        self.lock_path = self.path + ".lock"
        self._clock = clock

    # -- public API ---------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for ``key``, or ``default`` if missing or expired."""
        data = self._read()
        entry = data.get(key)
        if entry is None or self._expired(entry):
            return default
        return entry["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store ``value`` under ``key``; ``ttl`` is a lifetime in seconds."""
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be a positive number of seconds")
        # Fail early, before taking the lock, on non-serializable values.
        json.dumps(value)
        with self._locked():
            data = self._read()
            self._purge(data)
            expires = self._clock() + ttl if ttl is not None else None
            data[key] = {"value": value, "expires": expires}
            self._write(data)

    def update(
        self, key: str, fn: Callable[[Any], Any], default: Any = None, ttl: float | None = None
    ) -> Any:
        """Atomically replace ``key`` with ``fn(current)`` and return the new value.

        ``current`` is ``default`` when the key is missing or expired. The whole
        read-modify-write happens under the exclusive lock, so concurrent
        updaters in other processes are serialized and no update is lost.
        """
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be a positive number of seconds")
        with self._locked():
            data = self._read()
            self._purge(data)
            entry = data.get(key)
            current = default if entry is None else entry["value"]
            new_value = fn(current)
            json.dumps(new_value)
            expires = self._clock() + ttl if ttl is not None else None
            data[key] = {"value": new_value, "expires": expires}
            self._write(data)
            return new_value

    def delete(self, key: str) -> bool:
        """Remove ``key``. Return True if a live key was removed."""
        with self._locked():
            data = self._read()
            self._purge(data)
            removed = data.pop(key, _MISSING) is not _MISSING
            self._write(data)
            return removed

    def keys(self) -> list[str]:
        """Return the live (non-expired) keys in insertion order."""
        data = self._read()
        return [k for k, entry in data.items() if not self._expired(entry)]

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self.get(key, _MISSING) is not _MISSING

    # -- internals ----------------------------------------------------------

    def _expired(self, entry: dict[str, Any]) -> bool:
        expires = entry.get("expires")
        return expires is not None and expires <= self._clock()

    def _purge(self, data: dict[str, dict[str, Any]]) -> None:
        for key in [k for k, entry in data.items() if self._expired(entry)]:
            del data[key]

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            with open(self.path, encoding="utf-8") as fh:
                raw = fh.read()
        except FileNotFoundError:
            return {}
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f"{self.path}: expected a JSON object at top level")
        return data

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".tinykv-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self.path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold an exclusive advisory lock for the duration of the block."""
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
