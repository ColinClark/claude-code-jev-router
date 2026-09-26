"""Persistent JSON-backed key-value store with per-key TTL, atomic writes and file locking.

On-disk format is a single JSON object mapping each key to a record::

    {"key": {"value": <json>, "expires": <unix timestamp or null>}}

Every read or write takes a lock on a sibling ``<path>.lock`` file (shared for reads,
exclusive for writes). The lock lives on a separate file because the data file itself
is replaced on each write via ``os.replace``, which would silently break a lock held on
the old inode.
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

Record = dict[str, Any]
Data = dict[str, Record]


class Store:
    """A small persistent key-value store.

    Args:
        path: Location of the JSON data file. It is created on first write.
        clock: Callable returning the current time in seconds. Defaults to ``time.time``;
            tests can inject a fake clock to exercise TTL expiry without sleeping.
    """

    def __init__(self, path: str | os.PathLike[str], clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._clock = clock

    # -- public API -------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for ``key``, or ``default`` if it is missing or expired."""
        with self._locked(fcntl.LOCK_SH):
            data = self._read()
        record = data.get(key)
        if record is None or self._expired(record):
            return default
        return record["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store ``value`` under ``key``; ``ttl`` is a lifetime in seconds (None = no expiry)."""
        if not isinstance(key, str):
            raise TypeError(f"key must be a str, not {type(key).__name__}")
        if ttl is not None:
            if isinstance(ttl, bool) or not isinstance(ttl, int | float):
                raise TypeError("ttl must be a number of seconds or None")
            if ttl <= 0:
                raise ValueError("ttl must be positive")
        # Fail before touching the file if the value cannot be serialized.
        json.dumps(value)
        expires = None if ttl is None else self._clock() + ttl
        with self._locked(fcntl.LOCK_EX):
            data = self._purge_expired(self._read())
            data[key] = {"value": value, "expires": expires}
            self._write(data)

    def delete(self, key: str) -> bool:
        """Remove ``key``. Returns True if a live (non-expired) key was removed."""
        with self._locked(fcntl.LOCK_EX):
            data = self._purge_expired(self._read())
            existed = data.pop(key, None) is not None
            self._write(data)
        return existed

    def keys(self) -> list[str]:
        """Return the sorted list of live (non-expired) keys."""
        with self._locked(fcntl.LOCK_SH):
            data = self._read()
        return sorted(k for k, rec in data.items() if not self._expired(rec))

    # -- internals --------------------------------------------------------------------

    def _expired(self, record: Record) -> bool:
        expires = record.get("expires")
        return expires is not None and expires <= self._clock()

    def _purge_expired(self, data: Data) -> Data:
        return {k: rec for k, rec in data.items() if not self._expired(rec)}

    @contextmanager
    def _locked(self, mode: int) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, mode)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _read(self) -> Data:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f"{self.path}: expected a JSON object at top level")
        return data

    def _write(self, data: Data) -> None:
        """Atomically replace the data file: temp file in the same directory, then rename."""
        directory = self.path.parent
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, separators=(",", ":"))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
        # Best effort: make the rename itself durable.
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
