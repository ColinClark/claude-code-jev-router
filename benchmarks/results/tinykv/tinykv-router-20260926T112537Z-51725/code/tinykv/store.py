"""A small persistent JSON key-value store with per-key TTL.

On-disk format is a single JSON object mapping each key to an entry::

    {"<key>": {"value": <json value>, "expires_at": <unix timestamp or null>}}

Concurrency model:

* Every read-modify-write (``set``, ``delete``, ``update``) holds an exclusive
  ``fcntl.flock`` on a sidecar lock file (``<path>.lock``) and re-reads the data
  file from disk while holding it. The data file itself is never locked because
  ``os.replace`` swaps its inode on every write.
* Reads (``get``, ``keys``) hold a shared lock on the same sidecar file.
* Writes go to a temp file in the same directory, are flushed and fsynced, and
  then atomically moved into place with ``os.replace``.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

__all__ = ["Store"]

_MISSING = object()


def _validate_key(key: Any) -> None:
    if not isinstance(key, str):
        raise TypeError(f"key must be a str, not {type(key).__name__}")


def _validate_ttl(ttl: Any) -> float | None:
    if ttl is None:
        return None
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)):
        raise TypeError(f"ttl must be an int or float, not {type(ttl).__name__}")
    if not math.isfinite(ttl) or ttl <= 0:
        raise ValueError(f"ttl must be a finite number > 0, got {ttl!r}")
    return float(ttl)


def _validate_value(value: Any) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"value is not JSON-serializable: {exc}") from exc


class Store:
    """Persistent key-value store backed by a JSON file."""

    def __init__(self, path: str | os.PathLike[str], clock: Callable[[], float] = time.time):
        self.path = os.fspath(path)
        self.lock_path = self.path + ".lock"
        self._clock = clock

    # ------------------------------------------------------------------ public API

    def get(self, key: str, default: Any = None) -> Any:
        """Return the live value for ``key`` or ``default`` if missing/expired."""
        _validate_key(key)
        with self._locked(fcntl.LOCK_SH):
            data = self._read()
        entry = data.get(key)
        if entry is None or self._is_expired(entry, self._clock()):
            return default
        return entry["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store ``value`` under ``key``; ``ttl`` (seconds) replaces any previous TTL."""
        _validate_key(key)
        ttl = _validate_ttl(ttl)
        _validate_value(value)
        with self._locked(fcntl.LOCK_EX):
            now = self._clock()
            data = self._read()
            self._prune(data, now)
            data[key] = self._make_entry(value, ttl, now)
            self._write(data)

    def delete(self, key: str) -> bool:
        """Remove ``key``. Return True if a live key was removed."""
        _validate_key(key)
        with self._locked(fcntl.LOCK_EX):
            now = self._clock()
            data = self._read()
            pruned = self._prune(data, now)
            removed = data.pop(key, None) is not None
            if removed or pruned:
                self._write(data)
        return removed

    def keys(self) -> list[str]:
        """Return the sorted list of live keys."""
        with self._locked(fcntl.LOCK_SH):
            data = self._read()
        now = self._clock()
        return sorted(k for k, entry in data.items() if not self._is_expired(entry, now))

    def update(
        self,
        key: str,
        fn: Callable[[Any], Any],
        default: Any = None,
        ttl: float | None = None,
    ) -> Any:
        """Atomically replace ``key``'s value with ``fn(current)`` and return it.

        ``current`` is the live value, or ``default`` if the key is missing or
        expired. The whole read-modify-write happens under the exclusive lock, so
        concurrent updates (across threads or processes) never lose writes.
        ``ttl`` has the same semantics as in :meth:`set`.
        """
        _validate_key(key)
        ttl = _validate_ttl(ttl)
        with self._locked(fcntl.LOCK_EX):
            now = self._clock()
            data = self._read()
            self._prune(data, now)
            entry = data.get(key)
            current = default if entry is None else entry["value"]
            new_value = fn(current)
            _validate_value(new_value)
            data[key] = self._make_entry(new_value, ttl, now)
            self._write(data)
        return new_value

    # ------------------------------------------------------------------ internals

    @contextmanager
    def _locked(self, mode: int) -> Iterator[None]:
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, mode)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"corrupt store file {self.path!r}: top level is not an object")
        return data

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        # Serialize first so a bad value can never produce a partial temp file.
        payload = json.dumps(data, allow_nan=False, sort_keys=True)
        directory = os.path.dirname(os.path.abspath(self.path))
        fd, tmp_path = tempfile.mkstemp(
            dir=directory, prefix=f".{os.path.basename(self.path)}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise
        self._fsync_dir(directory)

    @staticmethod
    def _fsync_dir(directory: str) -> None:
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)

    @staticmethod
    def _make_entry(value: Any, ttl: float | None, now: float) -> dict[str, Any]:
        return {"value": value, "expires_at": None if ttl is None else now + ttl}

    @staticmethod
    def _is_expired(entry: dict[str, Any], now: float) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and expires_at <= now

    def _prune(self, data: dict[str, dict[str, Any]], now: float) -> bool:
        expired = [k for k, entry in data.items() if self._is_expired(entry, now)]
        for k in expired:
            del data[k]
        return bool(expired)
