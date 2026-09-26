"""A small persistent, process-safe JSON key-value store."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


class Store:
    """A JSON-file-backed key-value store with per-key TTL and lazy expiry.

    Safe for concurrent use across multiple processes: writes are guarded by
    an exclusive file lock around a read-modify-write cycle, and persisted
    atomically via a temp file + os.replace in the same directory.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _read_raw(self) -> dict[str, dict[str, Any]]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_raw(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp_path, self.path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _is_expired(entry: dict[str, Any], now: float) -> bool:
        expires_at = entry.get("expires_at")
        return expires_at is not None and now >= expires_at

    def _with_lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(self.lock_path, "a+")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return lock_file

    def get(self, key: str) -> Any:
        data = self._read_raw()
        entry = data.get(key)
        if entry is None:
            return None
        if self._is_expired(entry, time.time()):
            return None
        return entry["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        lock_file = self._with_lock()
        try:
            data = self._read_raw()
            now = time.time()
            data = {k: v for k, v in data.items() if not self._is_expired(v, now)}
            entry: dict[str, Any] = {"value": value}
            if ttl is not None:
                entry["expires_at"] = now + ttl
            data[key] = entry
            self._write_raw(data)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    def delete(self, key: str) -> bool:
        lock_file = self._with_lock()
        try:
            data = self._read_raw()
            now = time.time()
            data = {k: v for k, v in data.items() if not self._is_expired(v, now)}
            existed = key in data
            data.pop(key, None)
            self._write_raw(data)
            return existed
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    def keys(self) -> list[str]:
        data = self._read_raw()
        now = time.time()
        return [k for k, entry in data.items() if not self._is_expired(entry, now)]
