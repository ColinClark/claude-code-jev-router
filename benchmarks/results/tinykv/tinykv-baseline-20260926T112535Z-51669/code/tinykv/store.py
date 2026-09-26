"""A small persistent, TTL-aware, multi-process-safe JSON key-value store."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Callable
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

_MISSING = object()


class Store:
    """A JSON-file-backed key-value store with per-key TTL and lazy expiry.

    Safe for concurrent use across multiple processes: every read-modify-write
    cycle is guarded by an exclusive `flock` on a sidecar lock file, and every
    write is applied atomically via a temp-file-then-`os.replace` swap.
    """

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def _locked(self, mode: int):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, mode)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            with open(self.path) as f:
                content = f.read()
        except FileNotFoundError:
            return {}
        if not content.strip():
            return {}
        return json.loads(content)

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        directory = self.path.parent if str(self.path.parent) else Path(".")
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=f".{self.path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp_path, self.path)
        except BaseException:
            with suppress(OSError):
                os.unlink(tmp_path)
            raise

    @staticmethod
    def _is_expired(entry: dict[str, Any], now: float) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and expires_at <= now

    def _drop_expired(
        self, data: dict[str, dict[str, Any]], now: float | None = None
    ) -> dict[str, dict[str, Any]]:
        if now is None:
            now = time.time()
        return {k: v for k, v in data.items() if not self._is_expired(v, now)}

    def get(self, key: str, default: Any = _MISSING) -> Any:
        with self._locked(fcntl.LOCK_SH):
            data = self._load()
        now = time.time()
        entry = data.get(key)
        if entry is None or self._is_expired(entry, now):
            if default is _MISSING:
                raise KeyError(key)
            return default
        return entry["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        with self._locked(fcntl.LOCK_EX):
            data = self._load()
            data = self._drop_expired(data)
            expires_at = time.time() + ttl if ttl is not None else None
            data[key] = {"value": value, "expires_at": expires_at}
            self._save(data)

    def delete(self, key: str) -> None:
        with self._locked(fcntl.LOCK_EX):
            data = self._load()
            data = self._drop_expired(data)
            data.pop(key, None)
            self._save(data)

    def keys(self) -> list[str]:
        with self._locked(fcntl.LOCK_SH):
            data = self._load()
        now = time.time()
        return [k for k, v in data.items() if not self._is_expired(v, now)]

    def update(
        self, key: str, func: Callable[[Any], Any], default: Any = None
    ) -> Any:
        """Atomically read-modify-write a single key under an exclusive lock.

        Guarantees no lost updates across concurrent processes: the whole
        read/apply/write cycle happens while holding the exclusive flock.
        """
        with self._locked(fcntl.LOCK_EX):
            data = self._load()
            data = self._drop_expired(data)
            entry = data.get(key)
            current = entry["value"] if entry is not None else default
            new_value = func(current)
            data[key] = {"value": new_value, "expires_at": None}
            self._save(data)
        return new_value
