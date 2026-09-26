"""A small persistent JSON key-value store with per-key TTL.

On-disk format (UTF-8 JSON)::

    {"version": 1, "data": {"<key>": {"value": <json>, "expires_at": <float|null>}}}

Concurrency model:

* Every mutation (``set``/``delete``/``update``) takes an exclusive ``fcntl.flock`` on a
  sidecar lock file (``<path>.lock``) and holds it across read -> modify -> atomic replace.
  The data file itself is never locked because ``os.replace`` swaps its inode.
* Reads (``get``/``keys``) take a shared lock on the same sidecar file.
* State is always re-read from disk inside the lock; nothing is cached in memory.
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
from typing import Any

FORMAT_VERSION = 1

_MISSING = object()


class Store:
    """A JSON-file-backed key-value store, safe for use from multiple processes."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = os.path.abspath(os.fspath(path))
        self.lock_path = self.path + ".lock"
        self._clock = clock

    # ------------------------------------------------------------------ public API

    def get(self, key: str, default: Any = None) -> Any:
        """Return the live value for ``key`` or ``default`` if missing/expired."""
        _check_key(key)
        with self._locked(fcntl.LOCK_SH):
            data = self._read()
        entry = data.get(key)
        if entry is None or self._is_expired(entry, self._clock()):
            return default
        return entry["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store ``value`` under ``key``, optionally expiring after ``ttl`` seconds."""
        _check_key(key)
        _check_ttl(ttl)
        _check_serializable(value)
        with self._locked(fcntl.LOCK_EX):
            data = self._read()
            now = self._clock()
            self._prune(data, now)
            data[key] = {"value": value, "expires_at": _expiry(now, ttl)}
            self._write(data)

    def delete(self, key: str) -> bool:
        """Remove ``key``. Return True if a live key was removed."""
        _check_key(key)
        with self._locked(fcntl.LOCK_EX):
            data = self._read()
            now = self._clock()
            existed = key in data and not self._is_expired(data[key], now)
            before = len(data)
            data.pop(key, None)
            self._prune(data, now)
            if len(data) != before:
                self._write(data)
            return existed

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
        """Atomically replace ``key``'s value with ``fn(current)`` and return the new value.

        ``current`` is the live value, or ``default`` if the key is missing or expired.
        The exclusive lock is held while ``fn`` runs, so concurrent updates never lose
        writes. ``ttl`` has the same meaning as in :meth:`set` (``None`` = no expiry).
        If ``fn`` raises or returns a non-serializable value, the file is not modified.
        """
        _check_key(key)
        _check_ttl(ttl)
        with self._locked(fcntl.LOCK_EX):
            data = self._read()
            now = self._clock()
            entry = data.get(key)
            if entry is None or self._is_expired(entry, now):
                current = default
            else:
                current = entry["value"]
            new_value = fn(current)
            _check_serializable(new_value)
            self._prune(data, now)
            data[key] = {"value": new_value, "expires_at": _expiry(now, ttl)}
            self._write(data)
            return new_value

    # ------------------------------------------------------------------ internals

    @contextlib.contextmanager
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
                raw = json.load(f)
        except FileNotFoundError:
            return {}
        if (
            not isinstance(raw, dict)
            or raw.get("version") != FORMAT_VERSION
            or not isinstance(raw.get("data"), dict)
        ):
            raise ValueError(f"{self.path}: unrecognized tinykv file format")
        return raw["data"]

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        payload = json.dumps(
            {"version": FORMAT_VERSION, "data": data},
            allow_nan=False,
            sort_keys=True,
        )
        directory = os.path.dirname(self.path)
        fd, tmp_path = tempfile.mkstemp(
            dir=directory, prefix="." + os.path.basename(self.path) + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_path)
            raise
        _fsync_dir(directory)

    @staticmethod
    def _is_expired(entry: dict[str, Any], now: float) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and expires_at <= now

    @classmethod
    def _prune(cls, data: dict[str, dict[str, Any]], now: float) -> None:
        for k in [k for k, entry in data.items() if cls._is_expired(entry, now)]:
            del data[k]


def _check_key(key: object) -> None:
    if not isinstance(key, str):
        raise TypeError(f"key must be str, not {type(key).__name__}")


def _check_ttl(ttl: object) -> None:
    if ttl is None:
        return
    if isinstance(ttl, bool) or not isinstance(ttl, int | float):
        raise TypeError(f"ttl must be int or float, not {type(ttl).__name__}")
    if not math.isfinite(ttl) or ttl <= 0:
        raise ValueError(f"ttl must be a finite number > 0, got {ttl!r}")


def _check_serializable(value: object) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise type(exc)(f"value is not JSON-serializable: {exc}") from exc


def _expiry(now: float, ttl: float | None) -> float | None:
    return None if ttl is None else float(now) + float(ttl)


def _fsync_dir(directory: str) -> None:
    """Best-effort fsync of the directory so the rename itself is durable."""
    try:
        dfd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)
