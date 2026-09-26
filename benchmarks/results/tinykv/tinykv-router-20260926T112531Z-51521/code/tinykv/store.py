"""File-backed JSON key-value store with per-key TTL and multi-process safety.

On-disk format: a single JSON object mapping each key to an entry
``{"value": <json>, "expires_at": <unix timestamp float> | null}``.

Concurrency model:

* Every mutation holds an exclusive ``fcntl.flock`` on a sidecar lock file
  (``<path>.lock``) for the whole read-modify-write. The data file itself is never
  locked because ``os.replace`` swaps its inode, which would make a lock on it useless.
* The data file is always re-read from disk inside the lock; nothing is cached.
* Writes are atomic: a temp file in the same directory is written, flushed, fsynced
  and then ``os.replace``-d onto the target, so readers never see a partial file.
* Reads take a shared lock on the same sidecar. ``os.replace`` alone already guarantees
  a reader sees a complete file, so the shared lock is not needed for integrity; it is
  taken so that a read observes a state strictly before or after any concurrent
  mutation. If the lock file cannot be created (e.g. read-only directory), reads fall
  back to an unlocked read, which is still consistent thanks to the atomic replace.

POSIX only (uses ``fcntl``).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

__all__ = ["Store", "StoreCorruptError"]

_MISSING = object()


class StoreCorruptError(ValueError):
    """The database file exists but does not contain a valid store document."""


def _check_key(key: object) -> None:
    if not isinstance(key, str):
        raise TypeError(f"key must be str, not {type(key).__name__}")


def _check_ttl(ttl: object) -> None:
    if ttl is None:
        return
    if isinstance(ttl, bool) or not isinstance(ttl, int | float):
        raise TypeError(f"ttl must be an int or float number of seconds, not {type(ttl).__name__}")
    if not math.isfinite(ttl) or ttl <= 0:
        raise ValueError(f"ttl must be a finite number of seconds > 0, got {ttl!r}")


def _check_value(key: str, value: Any) -> None:
    """Raise if ``value`` cannot be stored as strict JSON. Never touches the file."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise TypeError(f"value for key {key!r} is not JSON-serializable: {exc}") from exc


class Store:
    """A JSON-file key-value store.

    ``clock`` returns the current wall-clock time in seconds since the epoch; it is
    injectable for tests. Expiry is stored as an absolute timestamp so it is honoured
    across processes and instances.
    """

    def __init__(self, path: str | os.PathLike[str], clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._clock = clock

    def __repr__(self) -> str:
        return f"Store({str(self.path)!r})"

    # ------------------------------------------------------------------ public API

    def get(self, key: str, default: Any = None) -> Any:
        _check_key(key)
        with self._shared_lock():
            data = self._read()
        entry = data.get(key)
        if entry is None or self._expired(entry, self._clock()):
            return default
        return entry["value"]

    def keys(self) -> list[str]:
        with self._shared_lock():
            data = self._read()
        now = self._clock()
        return sorted(k for k, entry in data.items() if not self._expired(entry, now))

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        _check_key(key)
        _check_ttl(ttl)
        _check_value(key, value)
        with self._exclusive_lock():
            data, now = self._read_live()
            data[key] = self._entry(value, ttl, now)
            self._write(data)

    def delete(self, key: str) -> bool:
        """Remove ``key``. Returns True only if a live (unexpired) key was removed."""
        _check_key(key)
        with self._exclusive_lock():
            raw = self._read()
            data, now = self._purge(raw)
            removed = data.pop(key, _MISSING) is not _MISSING
            if removed or len(data) != len(raw):
                self._write(data)
        return removed

    def update(
        self,
        key: str,
        fn: Callable[[Any], Any],
        default: Any = None,
        ttl: float | None = None,
    ) -> Any:
        """Atomically replace ``key`` with ``fn(current)`` and return the new value.

        ``current`` is the live value, or ``default`` if the key is missing or expired.
        The whole read-modify-write happens under the exclusive lock, so concurrent
        updates from any process are serialized. ``fn`` must not call back into a
        Store on the same path (that would deadlock). As with ``set``, ``ttl=None``
        stores the key without expiry. If ``fn`` raises or returns a value that is
        not JSON-serializable, the file is left unchanged.
        """
        _check_key(key)
        _check_ttl(ttl)
        with self._exclusive_lock():
            data, now = self._read_live()
            entry = data.get(key)
            new_value = fn(default if entry is None else entry["value"])
            _check_value(key, new_value)
            data[key] = self._entry(new_value, ttl, now)
            self._write(data)
        return new_value

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _expired(entry: dict[str, Any], now: float) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and now >= expires_at

    @staticmethod
    def _entry(value: Any, ttl: float | None, now: float) -> dict[str, Any]:
        return {"value": value, "expires_at": None if ttl is None else now + ttl}

    def _purge(self, data: dict[str, Any]) -> tuple[dict[str, Any], float]:
        now = self._clock()
        return {k: e for k, e in data.items() if not self._expired(e, now)}, now

    def _read_live(self) -> tuple[dict[str, Any], float]:
        return self._purge(self._read())

    def _read(self) -> dict[str, Any]:
        try:
            with open(self.path, encoding="utf-8") as fh:
                text = fh.read()
        except FileNotFoundError:
            return {}
        if not text.strip():
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StoreCorruptError(f"{self.path}: invalid JSON: {exc}") from exc
        if not isinstance(data, dict) or not all(
            isinstance(e, dict) and "value" in e and "expires_at" in e for e in data.values()
        ):
            raise StoreCorruptError(f"{self.path}: not a tinykv store document")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, allow_nan=False, ensure_ascii=False, sort_keys=True)
        directory = self.path.parent
        fd, tmp_name = tempfile.mkstemp(
            dir=directory, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)
            raise
        self._fsync_dir(directory)

    @staticmethod
    def _fsync_dir(directory: Path) -> None:
        """Best-effort durability of the rename itself."""
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

    @contextlib.contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)  # closing the descriptor releases the flock

    @contextlib.contextmanager
    def _shared_lock(self) -> Iterator[None]:
        try:
            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            # Missing or read-only directory: atomic replace still guarantees that a
            # lockless reader sees a complete file (or none at all).
            fd = None
        if fd is None:
            yield
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            yield
        finally:
            os.close(fd)
