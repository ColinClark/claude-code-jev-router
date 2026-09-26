"""A tiny JSON-file-backed key-value store with lazy TTL expiry.

On-disk format (a single JSON object)::

    {"<key>": {"value": <any JSON value>, "expires_at": <float unix timestamp | null>}}

Concurrency model:

* Every read-modify-write cycle (``set``, ``delete``) holds an exclusive ``fcntl.flock``
  on a sibling lock file (``<path>.lock``) for the whole read -> modify -> write-back
  sequence, and reads the data file fresh after acquiring the lock. A sibling file is
  used instead of ``path`` itself because ``os.replace`` swaps in a new inode, which
  would silently invalidate a lock held on the old one.
* Writes go to a temp file in the same directory, are flushed and fsynced, and then
  atomically swapped into place with ``os.replace``. Readers therefore always see
  either the old or the new complete file, so ``get`` and ``keys`` (which never write)
  do not need the lock.
"""

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class Store:
    """Persistent key-value store backed by a JSON file at ``path``.

    A missing file is treated as an empty store; it is created on the first write.
    Independent ``Store`` instances (in the same or different processes) pointed at the
    same path are safe to use concurrently: no in-memory cache is kept.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock_path = self.path.with_name(self.path.name + ".lock")

    # ------------------------------------------------------------------ public API

    def get(self, key: str) -> Any:
        """Return the value stored under ``key``.

        Returns ``None`` if the key is missing or expired. Because ``None`` is also a
        valid JSON value, a stored ``None`` is indistinguishable from a missing key
        here; use ``keys()`` to check for presence.
        """
        entry = self._read().get(key)
        if entry is None or self._is_expired(entry, time.time()):
            return None
        return entry["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store ``value`` (must be JSON-serializable) under ``key``.

        ``ttl`` is the number of seconds from now until the key expires; ``None``
        means it never expires. The absolute expiry timestamp is what gets persisted.
        Raises ``TypeError``/``ValueError`` (and leaves the file untouched) if the value
        cannot be serialized.
        """
        with self._locked():
            now = time.time()
            data = self._sweep(self._read(), now)
            expires_at = None if ttl is None else now + ttl
            data[key] = {"value": value, "expires_at": expires_at}
            self._write(data)

    def delete(self, key: str) -> None:
        """Remove ``key`` if present; do nothing if it is absent."""
        with self._locked():
            data = self._sweep(self._read(), time.time())
            data.pop(key, None)
            self._write(data)

    def keys(self) -> list[str]:
        """Return a list of all non-expired keys."""
        now = time.time()
        return [k for k, entry in self._read().items() if not self._is_expired(entry, now)]

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _is_expired(entry: dict[str, Any], now: float) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and expires_at <= now

    def _sweep(self, data: dict[str, Any], now: float) -> dict[str, Any]:
        return {k: e for k, e in data.items() if not self._is_expired(e, now)}

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold an exclusive flock on the sibling lock file for the enclosed block."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _read(self) -> dict[str, Any]:
        """Read the data file fresh from disk; a missing or empty file is an empty store."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        if not text.strip():
            return {}
        data = json.loads(text)
        if not isinstance(data, dict):
            raise TypeError(f"{self.path}: expected a JSON object at top level")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        """Atomically replace the data file with ``data``. Caller must hold the lock."""
        # Serialize first so an unserializable value fails before touching the disk.
        payload = json.dumps(data).encode("utf-8")
        directory = self.path.parent
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=self.path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
        self._fsync_dir(directory)

    @staticmethod
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
