"""Key-value store implementation for tinykv.

Data is persisted as a single JSON object mapping each key to a record of the
form ``{"value": <json value>, "expires_at": <unix timestamp float or null>}``.

Concurrency: every read-modify-write cycle (``set``/``delete``) holds an
exclusive ``fcntl.flock`` on a dedicated sibling lock file (``<path>.lock``)
for the whole cycle. A dedicated lock file is used rather than the data file
itself because writes replace the data file via ``os.replace``; a lock on the
old inode would not exclude a process that opened the new one.

Writes are atomic: data is written to a temp file in the same directory as the
target, flushed and fsynced, then moved into place with ``os.replace``. Readers
(``get``/``keys``) therefore never observe a partially written file and do not
need the lock.

Expiry is lazy: expired keys are treated as absent on read and are physically
removed from the file on the next ``set`` or ``delete``.
"""

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
    """A JSON-file-backed key-value store with per-key TTL."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    # -- public API ---------------------------------------------------------

    def get(self, key: str) -> Any:
        """Return the value stored under ``key``.

        Raises ``KeyError`` if the key is missing or expired.
        """
        record = self._read().get(key)
        if record is None or self._is_expired(record, time.time()):
            raise KeyError(key)
        return record["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store ``value`` under ``key``.

        ``ttl`` is a number of seconds after which the key expires; ``None``
        means no expiry. ``value`` must be JSON-serializable.
        """
        if ttl is not None and (isinstance(ttl, bool) or not isinstance(ttl, (int, float))):
            raise TypeError(f"ttl must be a number of seconds or None, not {type(ttl).__name__}")
        with self._locked():
            now = time.time()
            data = self._purge_expired(self._read(), now)
            data[key] = {"value": value, "expires_at": None if ttl is None else now + ttl}
            self._write(data)

    def delete(self, key: str) -> None:
        """Remove ``key`` from the store.

        Raises ``KeyError`` if the key is missing or expired, mirroring
        ``dict.__delitem__``. Expired keys are still purged from disk first.
        """
        with self._locked():
            data = self._read()
            live = self._purge_expired(data, time.time())
            if key not in live:
                if len(live) != len(data):
                    self._write(live)
                raise KeyError(key)
            del live[key]
            self._write(live)

    def keys(self) -> list[str]:
        """Return a list of all non-expired keys."""
        return list(self._purge_expired(self._read(), time.time()))

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _is_expired(record: dict[str, Any], now: float) -> bool:
        expires_at = record.get("expires_at")
        return expires_at is not None and now >= expires_at

    @classmethod
    def _purge_expired(cls, data: dict[str, Any], now: float) -> dict[str, Any]:
        return {k: r for k, r in data.items() if not cls._is_expired(r, now)}

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold an exclusive flock on the sibling lock file for the block."""
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o666)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _read(self) -> dict[str, Any]:
        """Load the data file; a missing or empty file is an empty store.

        A non-empty file that is not a valid JSON object raises ``ValueError``.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        if not text.strip():
            return {}
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        raise ValueError(f"{self.path}: expected a JSON object at top level")

    def _write(self, data: dict[str, Any]) -> None:
        """Atomically replace the data file with ``data``."""
        # Serialize first so an unserializable value never leaves a temp file behind.
        payload = json.dumps(data)
        directory = self.path.parent
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)
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
