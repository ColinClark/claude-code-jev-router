"""A small persistent key-value store backed by a JSON file.

On-disk format::

    {"key": {"value": <json value>, "expires_at": <float epoch seconds> | null}}

Concurrency model:

* Every operation takes an ``fcntl.flock`` on a sidecar lock file (``<path>.lock``),
  never on the data file itself. Writes replace the data file via ``os.replace``,
  which swaps the inode, so a lock held on the data file would not exclude later
  writers.
* Reads take a shared lock; writes take an exclusive lock around the full
  read-modify-write and always re-read the data file from disk inside the lock.
* Writes are atomic: data is written to a temp file in the same directory,
  flushed and fsynced, then moved onto the target with ``os.replace``.
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
from pathlib import Path
from typing import Any

__all__ = ["Store"]

_MISSING = object()


class Store:
    """A JSON-file key-value store with per-key TTL and multi-process locking."""

    def __init__(self, path: str | os.PathLike[str], clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._clock = clock

    # ------------------------------------------------------------------ public API

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for ``key``, or ``default`` if missing or expired."""
        _check_key(key)
        with self._locked(fcntl.LOCK_SH):
            data = self._read()
        value = self._live_value(data, key, self._clock())
        return default if value is _MISSING else value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store ``value`` under ``key``, optionally expiring after ``ttl`` seconds."""
        _check_key(key)
        _check_ttl(ttl)
        with self._locked(fcntl.LOCK_EX):
            data = self._read()
            now = self._clock()
            self._purge_expired(data, now)
            data[key] = self._entry(value, ttl, now)
            self._write(data)

    def delete(self, key: str) -> bool:
        """Remove ``key``. Return True if a live (non-expired) entry existed."""
        _check_key(key)
        with self._locked(fcntl.LOCK_EX):
            data = self._read()
            now = self._clock()
            purged = self._purge_expired(data, now)
            existed = data.pop(key, _MISSING) is not _MISSING
            if existed or purged:
                self._write(data)
        return existed

    def keys(self) -> list[str]:
        """Return the sorted list of live (non-expired) keys."""
        with self._locked(fcntl.LOCK_SH):
            data = self._read()
        now = self._clock()
        return sorted(k for k, entry in data.items() if not _is_expired(entry, now))

    def update(
        self,
        key: str,
        fn: Callable[[Any], Any],
        default: Any = None,
        ttl: float | None = None,
    ) -> Any:
        """Atomically replace the value of ``key`` with ``fn(current)``.

        ``current`` is the live value, or ``default`` if the key is missing or
        expired. The whole read-modify-write runs under the exclusive lock, so
        concurrent updaters (threads or processes) never lose each other's writes.
        ``ttl`` has the same meaning as in :meth:`set` (``None`` = no expiry).
        Returns the new value.
        """
        _check_key(key)
        _check_ttl(ttl)
        with self._locked(fcntl.LOCK_EX):
            data = self._read()
            now = self._clock()
            current = self._live_value(data, key, now)
            new_value = fn(default if current is _MISSING else current)
            self._purge_expired(data, now)
            data[key] = self._entry(new_value, ttl, now)
            self._write(data)
        return new_value

    # ------------------------------------------------------------------ internals

    @contextmanager
    def _locked(self, operation: int) -> Iterator[None]:
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, operation)
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
            raise ValueError(f"corrupt store file {self.path}: top-level JSON is not an object")
        return data

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        # Serialize first so an unserializable value never touches the disk.
        payload = json.dumps(data, sort_keys=True)
        parent = self.path.parent
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(tmp_name, self.path.stat().st_mode & 0o7777)
            except FileNotFoundError:
                pass
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
        _fsync_dir(parent)

    @staticmethod
    def _entry(value: Any, ttl: float | None, now: float) -> dict[str, Any]:
        return {"value": value, "expires_at": None if ttl is None else now + ttl}

    @staticmethod
    def _live_value(data: dict[str, dict[str, Any]], key: str, now: float) -> Any:
        entry = data.get(key)
        if entry is None or _is_expired(entry, now):
            return _MISSING
        return entry["value"]

    @staticmethod
    def _purge_expired(data: dict[str, dict[str, Any]], now: float) -> bool:
        expired = [k for k, entry in data.items() if _is_expired(entry, now)]
        for k in expired:
            del data[k]
        return bool(expired)


def _is_expired(entry: dict[str, Any], now: float) -> bool:
    expires_at = entry.get("expires_at")
    return expires_at is not None and expires_at <= now


def _check_key(key: object) -> None:
    if not isinstance(key, str):
        raise TypeError(f"key must be str, not {type(key).__name__}")


def _check_ttl(ttl: object) -> None:
    if ttl is None:
        return
    if isinstance(ttl, bool) or not isinstance(ttl, int | float):
        raise TypeError(f"ttl must be int, float or None, not {type(ttl).__name__}")
    if not math.isfinite(ttl) or ttl <= 0:
        raise ValueError(f"ttl must be a finite number > 0, got {ttl!r}")


def _fsync_dir(directory: Path) -> None:
    """Best-effort fsync of the directory so the rename itself is durable."""
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
