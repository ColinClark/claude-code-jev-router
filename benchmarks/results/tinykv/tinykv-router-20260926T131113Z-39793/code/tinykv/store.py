"""Persistent JSON-file key-value store with TTL and multi-process safety."""

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
    """A key-value store persisted to a JSON file.

    Every operation re-reads the file from disk under an ``fcntl.flock`` held on
    a separate lock file (``path + ".lock"``). Writes are atomic: a temp file in
    the same directory is written, fsynced and then ``os.replace``d over the
    data file. Because ``os.replace`` swaps the data file's inode, the lock is
    taken on the dedicated lock file rather than on the data file itself.

    On-disk format: ``{key: {"value": <json>, "expires_at": <float|null>}}``.
    """

    def __init__(self, path: str | os.PathLike[str], clock: Callable[[], float] = time.time):
        self.path = os.fspath(path)
        self.lock_path = self.path + ".lock"
        self._clock = clock

    # ----------------------------------------------------------------- locking
    @contextlib.contextmanager
    def _locked(self, exclusive: bool) -> Iterator[None]:
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    # --------------------------------------------------------------------- I/O
    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = f.read()
        except FileNotFoundError:
            return {}
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f"corrupt tinykv file {self.path!r}: top level is not an object")
        return data

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tinykv-", suffix=".tmp")
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
        # Best effort: persist the directory entry for the rename.
        with contextlib.suppress(OSError):
            dfd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)

    def _is_live(self, entry: dict[str, Any], now: float) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is None or expires_at > now

    def _purge(self, data: dict[str, dict[str, Any]], now: float) -> dict[str, dict[str, Any]]:
        return {k: e for k, e in data.items() if self._is_live(e, now)}

    # ---------------------------------------------------------------- public API
    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for ``key``, or ``default`` if missing or expired."""
        with self._locked(exclusive=False):
            data = self._read()
        entry = data.get(key)
        if entry is None or not self._is_live(entry, self._clock()):
            return default
        return entry["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store ``value`` under ``key``, optionally expiring after ``ttl`` seconds."""
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive")
        json.dumps(value)  # fail early on non-JSON-serializable values
        with self._locked(exclusive=True):
            now = self._clock()
            data = self._purge(self._read(), now)
            data[key] = {"value": value, "expires_at": None if ttl is None else now + ttl}
            self._write(data)

    def delete(self, key: str) -> bool:
        """Delete ``key``. Return True if a live entry existed."""
        with self._locked(exclusive=True):
            now = self._clock()
            original = self._read()
            data = self._purge(original, now)
            existed = key in data
            data.pop(key, None)
            if existed or len(data) != len(original):
                self._write(data)
            return existed

    def update(self, key: str, fn: Callable[[Any], Any], default: Any = None) -> Any:
        """Atomically replace the value of ``key`` with ``fn(current)``.

        ``current`` is ``default`` when the key is missing or expired. Any existing
        TTL on a live key is preserved. Returns the new value.
        """
        with self._locked(exclusive=True):
            now = self._clock()
            data = self._purge(self._read(), now)
            entry = data.get(key)
            current = default if entry is None else entry["value"]
            new_value = fn(current)
            json.dumps(new_value)
            expires_at = None if entry is None else entry.get("expires_at")
            data[key] = {"value": new_value, "expires_at": expires_at}
            self._write(data)
            return new_value

    def keys(self) -> list[str]:
        """Return the list of live (non-expired) keys."""
        with self._locked(exclusive=False):
            data = self._read()
        now = self._clock()
        return [k for k, e in data.items() if self._is_live(e, now)]
